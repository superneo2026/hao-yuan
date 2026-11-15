from __future__ import annotations

import json
import os
from pathlib import Path

try:
    from configs import secrets_local as _local
except ImportError:
    _local = None


def config_path() -> Path:
    """全局配置文件路径（与 opencode 类似的固定用户级路径）。"""
    override = os.getenv("HAOYUAN_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "haoyuan" / "config.json"


def _read_global_config() -> dict:
    try:
        with config_path().open("r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


_GLOBAL_CONFIG = _read_global_config()


def global_config(name: str, default: str = "") -> str:
    value = _GLOBAL_CONFIG.get(name)
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _get(name: str, default: str = "") -> str:
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
