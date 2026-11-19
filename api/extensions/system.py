from __future__ import annotations

import platform
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Body, Query

from configs.configs import APP_NAME, APP_VERSION, WORKSPACE_DIR, prefix
from configs import models as models_mod
from configs.models import list_models
from core.harness import get_harness
from extensions.common import ok

router = APIRouter(prefix=prefix, tags=["system"])


def _is_anthropic(provider: str, base_url: str) -> bool:
    return provider.strip().lower() in {"claude", "anthropic"} or "anthropic.com" in base_url.lower()


_OPENAI_NON_CHAT = (
    "embedding",
    "embed-",
    "whisper",
    "tts",
    "dall-e",
    "moderation",
    "audio",
    "transcribe",
    "speech",
    "sora",
    "rerank",
    "image",
)


def _model_timestamp(item: dict) -> float:
    for key in ("created", "created_at"):
        value = item.get(key)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            continue
    return 0.0


def _extract_model_ids(payload: Any, provider: str = "", base_url: str = "") -> list[str]:
    """兼容 OpenAI / Anthropic / 自定义的 /models 响应结构，并按发布时间倒序。"""
    items = payload
    if isinstance(payload, dict):
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("models") or payload.get("data") or []
    if isinstance(items, dict):
        items = list(items.values())
    entries: list[tuple[str, float]] = []
    seen: set[str] = set()
    filter_non_chat = provider.strip().lower() == "openai" or "openai.com" in base_url.lower()
    for item in items if isinstance(items, list) else []:
        created = 0.0
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
            created = _model_timestamp(item)
        else:
            model_id = ""
        model_id = str(model_id or "").strip()
        if not model_id or model_id in seen:
            continue
        if filter_non_chat and any(token in model_id.lower() for token in _OPENAI_NON_CHAT):
            continue
        seen.add(model_id)
        entries.append((model_id, created))
    if any(created for _, created in entries):
        entries.sort(key=lambda entry: (-entry[1], entry[0]))
    else:
        entries.sort(key=lambda entry: entry[0])
    return [model_id for model_id, _ in entries]


@router.get("/setup")
async def setup():
    return ok({"ready": True})


@router.get("/ping")
async def ping(msg: str = Query("hello")):
    return ok({"message": msg})


@router.get("/health")
async def health():
    harness = await get_harness()
    return ok(
        {
            "status": "ok",
            "name": APP_NAME,
            "version": APP_VERSION,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "default_provider": models_mod.auto_default()[0],
            "default_model": models_mod.auto_default()[1],
            "providers": [
                {
                    "name": name,
                    "models": conf.models,
                    "default_model": conf.default_model,
                    "configured": bool(conf.api_key) if name != "mock" else True,
                    "key_source": conf.key_source if name != "mock" else "builtin",
                    "builtin": conf.builtin,
                }
                for name, conf in models_mod.get_providers().items()
            ],
            "workspace_root": str(WORKSPACE_DIR),
            "tools": len(harness.tools.list_specs()),
            "agents": harness.agents.names(),
            "skills": len(harness.skills.list()),
            "plugins": harness.plugin_status(),
        }
    )


@router.get("/info")
async def info():
    harness = await get_harness()
    return ok(
        {
            "name": APP_NAME,
            "version": APP_VERSION,
            "description": "HaoYuan - an autonomous AI studio with a plugin architecture, with coding as a core specialty.",
            "models": list_models(),
            "tools": [spec.model_dump() for spec in harness.tools.list_specs()],
            "agents": harness.agents.list(),
        }
    )


@router.get("/config")
async def read_config():
    return ok(models_mod.describe_config())


@router.put("/config")
async def write_config(body: dict = Body(...)):
    try:
        view = models_mod.update_config(
            body.get("providers") or [],
            body.get("removed") or [],
            body.get("default_provider"),
            body.get("default_model"),
        )
    except ValueError as exc:
        return {"code": 400, "data": None, "message": str(exc)}
    return ok(view)


@router.post("/config")
async def write_config_post(body: dict = Body(...)):
    return await write_config(body)


@router.get("/config/raw")
async def read_config_raw():
    return ok(models_mod.raw_config_view())


@router.post("/config/discover-models")
async def discover_models(body: dict = Body(...)):
    """按渠道的 Base URL + 密钥读取服务商最新的模型列表。"""
    provider = str(body.get("provider") or "").strip()
    base_url = str(body.get("base_url") or "").strip().rstrip("/")
    api_key = str(body.get("api_key") or "").strip()
    if provider and (not base_url or not api_key):
        conf = models_mod.get_providers().get(provider)
        if conf:
            base_url = base_url or conf.base_url
            api_key = api_key or conf.api_key
    if not base_url.startswith(("http://", "https://")):
        return {"code": 400, "data": None, "message": "base_url must start with http:// or https://"}
    anthropic = _is_anthropic(provider, base_url)
    headers = {"Accept": "application/json"}
    if anthropic:
        # Anthropic 原生 /models 使用 x-api-key；limit 直接取最大页，避免漏掉新模型。
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    url = f"{base_url}/models?limit=1000" if anthropic else f"{base_url}/models"
    items: list[Any] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
            for _ in range(20):
                response = await client.get(url, headers=headers)
                if response.status_code >= 400:
                    return {
                        "code": 400,
                        "data": None,
                        "message": f"读取模型列表失败：HTTP {response.status_code} {response.text[:300]}",
                    }
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                    items.extend(payload["data"])
                elif isinstance(payload, dict) and isinstance(payload.get("models"), list):
                    items.extend(payload["models"])
                elif isinstance(payload, list):
                    items.extend(payload)
                else:
                    items.append(payload)
                if not anthropic or not isinstance(payload, dict) or not payload.get("has_more"):
                    break
                last_id = payload.get("last_id")
                if not last_id:
                    break
                url = f"{base_url}/models?limit=1000&after_id={last_id}"
    except Exception as exc:  # noqa: BLE001 - 把网络/解析错误转为可展示提示
        return {"code": 400, "data": None, "message": f"读取模型列表失败：{exc}"}
    models = _extract_model_ids(items, provider=provider, base_url=base_url)
    if not models:
        return {"code": 400, "data": None, "message": "服务商未返回模型列表，请手动填写模型名。"}
    return ok({"models": models, "base_url": base_url})
