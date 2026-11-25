# hao-yuan/api/core/telemetry.py
"""匿名使用统计心跳（透明、可关闭）。

- 上报内容只有：本地随机生成的 install_id（UUID）、机器标识哈希 device_id（用于同一台机器多个实例去重）、客户端版本、操作系统类型
- 不包含：用户名、邮箱、文件内容、路径、对话内容等任何个人数据
- 服务端会记录来源 IP（用于区分设备/排查来源，保留 90 天）与 IP 单向哈希
- 关闭方式：设置环境变量 HAOYUAN_TELEMETRY=0（或 off/false/no）
- 声明与说明见插件中心 /api/plugin-center/privacy 与 README
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import platform
import secrets
import uuid
from pathlib import Path

import httpx

from configs.configs import APP_VERSION, DATA_DIR, PLUGIN_CENTER_APP_KEY, PLUGIN_CENTER_URL

HEARTBEAT_PATH = "/api/plugin-center/telemetry/heartbeat"
OFFLINE_PATH = "/api/plugin-center/telemetry/offline"
INTERVAL_SEC = 60
STARTUP_DELAY_SEC = 2
TIMEOUT_SEC = 6.0
STATE_PATH = DATA_DIR / "telemetry.json"
CENTER_URL_PATH = DATA_DIR / "plugin_center_url.txt"

_task: asyncio.Task | None = None


def enabled() -> bool:
    import os

    return os.getenv("HAOYUAN_TELEMETRY", "1").strip().lower() not in {"0", "off", "false", "no"}


def remember_center_url(url: str) -> None:
    """记住用户实际使用的插件中心地址（由插件市场调用方传入）。

    默认 HAOYUAN_PLUGIN_CENTER_URL 是 127.0.0.1，很多用户只在网页里把插件中心
    改成公网地址；心跳若仍打 127.0.0.1 会静默失败，导致该设备永远不在线。
    """
    text = str(url or "").strip().rstrip("/")
    if not text.startswith(("http://", "https://")):
        return
    try:
        CENTER_URL_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = CENTER_URL_PATH.with_suffix(".tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(CENTER_URL_PATH)
    except OSError:
        pass


def center_url() -> str:
    import os

    explicit = os.getenv("HAOYUAN_PLUGIN_CENTER_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    try:
        saved = CENTER_URL_PATH.read_text(encoding="utf-8").strip()
        if saved:
            return saved.rstrip("/")
    except OSError:
        pass
    return PLUGIN_CENTER_URL.rstrip("/")


def _load_install_id() -> str:
    try:
        if STATE_PATH.is_file():
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            install_id = str(data.get("install_id", "")).strip()
            if install_id:
                return install_id
    except (OSError, ValueError):
        pass
    install_id = str(uuid.uuid4())
    try:
        from datetime import datetime

        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE_PATH.with_suffix(f".{secrets.token_hex(4)}.tmp")
        temp.write_text(
            json.dumps({"install_id": install_id, "created_at": datetime.now().isoformat()}, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(STATE_PATH)
    except OSError:
        pass
    return install_id


def _raw_machine_id() -> str:
    """取一个稳定的机器标识，让同一台设备上的多个豪源实例共享同一个 device_id。"""
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
                if value:
                    return f"win:{value}"
        except Exception:
            pass
    if system in {"Linux", "Darwin"}:
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                value = Path(path).read_text(encoding="utf-8").strip()
                if value:
                    return f"{system.lower()}:{value}"
            except OSError:
                continue
    # 兜底：主机名 + 网卡地址（MAC）
    return f"{platform.node()}:{uuid.getnode()}"


_device_id_cache: str | None = None


def _device_id() -> str:
    global _device_id_cache
    if _device_id_cache is None:
        raw = _raw_machine_id()
        _device_id_cache = hashlib.sha256(f"{PLUGIN_CENTER_APP_KEY}:{raw}".encode("utf-8")).hexdigest()[:32]
    return _device_id_cache


def _payload() -> bytes:
    body = {
        "install_id": _load_install_id(),
        "device_id": _device_id(),
        "interval": INTERVAL_SEC,
        "version": APP_VERSION,
        "platform": f"{platform.system()} {platform.release()}",
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def _send_once(client: httpx.AsyncClient) -> bool:
    body = _payload()
    sign = hmac.new(PLUGIN_CENTER_APP_KEY.encode("utf-8"), body, hashlib.sha256).hexdigest()
    url = f"{center_url()}{HEARTBEAT_PATH}"
    response = await client.post(url, content=body, headers={"X-Haoyuan-Sign": sign})
    return response.status_code == 200


async def _loop() -> None:
    await asyncio.sleep(STARTUP_DELAY_SEC)
    interval = INTERVAL_SEC
    async with httpx.AsyncClient(timeout=TIMEOUT_SEC, trust_env=False) as client:
        while True:
            try:
                if await _send_once(client):
                    pass  # 心跳成功，静默
            except Exception:
                pass  # 统计不干扰主功能，失败静默（含网络不可达/插件中心未启动）
            await asyncio.sleep(interval)


def start() -> None:
    global _task
    if not enabled() or _task is not None:
        return
    _task = asyncio.create_task(_loop())
    print(
        "[Telemetry] anonymous usage heartbeat enabled "
        f"(install_id={_load_install_id()[:8]}…, device_id={_device_id()[:8]}…) → {center_url()}{HEARTBEAT_PATH}；"
        "设置 HAOYUAN_TELEMETRY=0 可关闭。详见插件中心 /api/plugin-center/privacy",
        flush=True,
    )


async def _send_offline() -> None:
    """正常退出时上报下线，让统计端立即把该实例从在线列表移除。"""
    if not enabled():
        return
    try:
        body = json.dumps(
            {"install_id": _load_install_id(), "device_id": _device_id()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        sign = hmac.new(PLUGIN_CENTER_APP_KEY.encode("utf-8"), body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            await client.post(f"{center_url()}{OFFLINE_PATH}", content=body, headers={"X-Haoyuan-Sign": sign})
    except Exception:
        pass  # 下线上报失败不影响退出


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    await _send_offline()


class _Telemetry:
    """命名空间封装，供 main.py 以 telemetry.start() / telemetry.stop() 调用。"""

    start = staticmethod(start)
    stop = staticmethod(stop)
    enabled = staticmethod(enabled)


telemetry = _Telemetry()
