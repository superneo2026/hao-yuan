from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

try:
    from configs import secrets_local as _local
except ImportError:
    _local = None


CONFIG_TEMPLATE: dict = {
    "_help": (
        "HaoYuan 全局配置。优先级：环境变量 > 本文件 > api/configs/secrets_local.py。"
        "内置渠道可用 DEEPSEEK_* / ZHIPU_* / MIMO_* 字段；任意 OpenAI 兼容渠道写到 providers 对象，"
        "例如 providers: {\"my-provider\": {\"base_url\": \"https://...\", \"api_key\": \"...\", "
        "\"models\": [\"model-a\", \"model-b\"], \"default_model\": \"model-a\"}}。"
        "网页设置页与保存会双向同步本文件。"
    ),
    "PROVIDER": "",
    "MODEL": "",
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "ZHIPU_API_KEY": "",
    "ZHIPU_BASE_URL": "https://open.bigmodel.cn/api/coding/paas/v4",
    "ZHIPU_MODEL": "glm-5.3-flash",
    "MIMO_API_KEY": "",
    "MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
    "MIMO_MODEL": "mimo-v2.6-flash",
    "providers": {},
}


def config_path() -> Path:
    """全局配置文件路径（与 opencode 类似的固定用户级路径）。"""
    override = os.getenv("HAOYUAN_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "haoyuan" / "config.json"


def _stamp() -> tuple[int, int] | None:
    try:
        info = config_path().stat()
        return (int(info.st_mtime_ns), int(info.st_size))
    except OSError:
        return None


def _read_global_config() -> dict:
    try:
        with config_path().open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_GLOBAL_CONFIG: dict = _read_global_config()
_CONFIG_STAMP: tuple[int, int] | None = _stamp()


def reload_global_config() -> dict:
    """重新读取配置文件；网页保存或外部编辑器修改后可立即生效。"""
    global _GLOBAL_CONFIG, _CONFIG_STAMP
    _GLOBAL_CONFIG = _read_global_config()
    _CONFIG_STAMP = _stamp()
    return _GLOBAL_CONFIG


def _ensure_fresh() -> None:
    if _stamp() != _CONFIG_STAMP:
        reload_global_config()


def config_stamp() -> tuple[int, int] | None:
    return _stamp()


def global_config_snapshot() -> dict:
    _ensure_fresh()
    return dict(_GLOBAL_CONFIG)


def ensure_config_file() -> tuple[Path, bool]:
    """首次安装时生成可编辑的全局配置模板；已存在则不覆盖。"""
    path = config_path()
    if path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path, False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(CONFIG_TEMPLATE, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        reload_global_config()
    except OSError:
        return path, False
    return path, True


def save_global_config(data: dict) -> Path:
    """原子写入全局配置，避免半截文件导致解析失败。"""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
    reload_global_config()
    return path


def global_config(name: str, default: str = "") -> str:
    _ensure_fresh()
    value = _GLOBAL_CONFIG.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _get(name: str, default: str = "") -> str:
    _ensure_fresh()
    env_value = os.getenv(name)
    if env_value is not None and env_value.strip():
        return env_value.strip()
    global_value = _GLOBAL_CONFIG.get(name)
    if global_value is not None and str(global_value).strip():
        return str(global_value).strip()
    if _local is not None:
        local_value = getattr(_local, name, None)
        if local_value is not None and str(local_value).strip():
            return str(local_value).strip()
    return default


DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL", "deepseek-flash")

ZHIPU_API_KEY = _get("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = _get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4").rstrip("/")

MIMO_API_KEY = _get("MIMO_API_KEY", "")
MIMO_BASE_URL = _get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1").rstrip("/")
MIMO_MODEL = _get("MIMO_MODEL", "mimo-v2.6-flash")

FEISHU_APP_ID = _get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = _get("FEISHU_APP_SECRET", "")


def get_secret(name: str, default: str = "") -> str:
    return _get(name, default)


def secret_source(name: str) -> str:
    _ensure_fresh()
    if os.getenv(name, "").strip():
        return "env"
    if _GLOBAL_CONFIG.get(name) is not None and str(_GLOBAL_CONFIG.get(name) or "").strip():
        return str(config_path())
    if _local is not None and str(getattr(_local, name, "") or "").strip():
        return "configs/secrets_local.py"
    return "default"


def is_configured(name: str) -> bool:
    return bool(_get(name, ""))


def mask_secret(value: str | None, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible * 2) + value[-visible:]
