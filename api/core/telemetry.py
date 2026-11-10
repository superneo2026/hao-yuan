# hao-yuan/api/core/telemetry.py
"""匿名使用统计心跳（透明、可关闭）。

- 上报内容只有：本地随机生成的 install_id（UUID）、客户端版本、操作系统类型
- 不包含：用户名、邮箱、文件内容、路径、对话内容等任何个人数据
- 服务端只记录 IP 的单向哈希，不存明文
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
INTERVAL_SEC = 300
STARTUP_DELAY_SEC = 2
TIMEOUT_SEC = 6.0
STATE_PATH = DATA_DIR / "telemetry.json"

_task: asyncio.Task | None = None


def enabled() -> bool:
    import os

    return os.getenv("HAOYUAN_TELEMETRY", "1").strip().lower() not in {"0", "off", "false", "no"}


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


def _payload() -> bytes:
    body = {
        "install_id": _load_install_id(),
        "version": APP_VERSION,
        "platform": f"{platform.system()} {platform.release()}",
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def _send_once(client: httpx.AsyncClient) -> bool:
    body = _payload()
    sign = hmac.new(PLUGIN_CENTER_APP_KEY.encode("utf-8"), body, hashlib.sha256).hexdigest()
    url = f"{PLUGIN_CENTER_URL.rstrip('/')}{HEARTBEAT_PATH}"
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
        f"(install_id={_load_install_id()[:8]}…) → {PLUGIN_CENTER_URL}{HEARTBEAT_PATH}；"
        "设置 HAOYUAN_TELEMETRY=0 可关闭。详见插件中心 /api/plugin-center/privacy",
        flush=True,
    )


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None


class _Telemetry:
    """命名空间封装，供 main.py 以 telemetry.start() / telemetry.stop() 调用。"""

    start = staticmethod(start)
    stop = staticmethod(stop)
    enabled = staticmethod(enabled)


telemetry = _Telemetry()
