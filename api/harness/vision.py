from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from configs.models import PROVIDERS, resolve

_ALLOWED_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_CACHE_TTL = 3600.0
_CACHE_MAX = 64
_CACHE: dict[str, tuple[float, str]] = {}


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _mime(path: Path) -> str:
    return _ALLOWED_MIME.get(path.suffix.lower(), "")


def _cache_get(key: str) -> str | None:
    item = _CACHE.get(key)
    if not item:
        return None
    created, value = item
    if time.monotonic() - created > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: str) -> None:
    if len(_CACHE) >= _CACHE_MAX:
        # Drop the oldest entry; the cache is only an optimization.
        oldest = min(_CACHE, key=lambda name: _CACHE[name][0])
        _CACHE.pop(oldest, None)
    _CACHE[key] = (time.monotonic(), value)


def sidecar_config() -> dict[str, str] | None:
    """Return the Qwen-VL sidecar config if one is usable, else None."""
    if os.getenv("HAOYUAN_VL_DISABLE", "").strip().lower() in {"1", "true", "yes"}:
        return None
    conf = PROVIDERS.get("aliyun")
    if conf and conf.api_key:
        model = next((item for item in conf.models if "vl" in item.lower()), "")
        if model:
            return {"base_url": conf.base_url.rstrip("/"), "api_key": conf.api_key, "model": model}
    key = (
        os.getenv("HAOYUAN_VL_API_KEY", "").strip()
        or os.getenv("DASHSCOPE_API_KEY", "").strip()
        or os.getenv("ALIYUN_API_KEY", "").strip()
    )
    if key:
        return {
            "base_url": (
                os.getenv("HAOYUAN_VL_BASE_URL", "").strip()
                or os.getenv("DASHSCOPE_BASE_URL", "").strip()
                or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ).rstrip("/"),
            "api_key": key,
            "model": os.getenv("HAOYUAN_VL_MODEL", "").strip() or "qwen-vl-max",
        }
    return None


def vision_mode(session: dict[str, Any]) -> str:
    """native = main model accepts images; sidecar = Qwen-VL tool; none = text-only."""
    provider, _model = resolve(session.get("provider"), session.get("model"))
    conf = PROVIDERS.get(provider)
    if conf and conf.supports_vision:
        return "native"
    if sidecar_config():
        return "sidecar"
    return "none"


def native_image_result(path: str, prompt: str) -> dict[str, Any]:
    return {"ok": True, "mode": "native", "path": path, "prompt": prompt}


def native_attachment_message(result: Any, workspace: str) -> list[dict[str, Any]] | None:
    """Build an OpenAI-compatible user content array for a native image attachment."""
    if not isinstance(result, dict) or result.get("mode") != "native":
        return None
    raw_path = str(result.get("path") or "")
    if not raw_path:
        return None
    try:
        root = Path(workspace).resolve()
        target = Path(raw_path)
        if not target.is_absolute():
            target = root / target
        target = target.resolve()
        if target != root and not target.is_relative_to(root):
            return None
        if not target.is_file():
            return None
        mime = _mime(target)
        if not mime:
            return None
        size = target.stat().st_size
        if size <= 0 or size > _MAX_IMAGE_BYTES:
            return None
        data = base64.b64encode(target.read_bytes()).decode("ascii")
    except OSError:
        return None
    prompt = str(result.get("prompt") or "").strip()
    text = f"[image attachment] {raw_path}"
    if prompt:
        text += f"\nInstruction: {prompt}"
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}},
    ]


async def describe_via_sidecar(path: str, prompt: str, max_tokens: int = 800) -> str:
    cfg = sidecar_config()
    if not cfg:
        return "[vision] no Qwen-VL sidecar is configured"
    image = Path(path)
    mime = _mime(image)
    if not mime:
        return f"[vision] unsupported image type: {image.suffix or '(none)'}"
    try:
        raw = image.read_bytes()
    except OSError as exc:
        return f"[vision] cannot read image: {exc}"
    if not raw:
        return "[vision] image is empty"
    if len(raw) > _MAX_IMAGE_BYTES:
        return f"[vision] image too large ({len(raw)} bytes); compress or resize it first"
    digest = hashlib.sha1(raw).hexdigest()
    key = hashlib.sha1(f"{digest}|{prompt}|{cfg['model']}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if cached:
        return cached
    data_url = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt or "请描述这张图片的内容、布局和明显问题。"},
                ],
            }
        ],
        "max_tokens": max(64, min(int(max_tokens), 2000)),
        "temperature": 0.1,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    url = f"{cfg['base_url']}/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code >= 400:
                return f"[vision] sidecar HTTP {response.status_code}: {response.text[:300]}"
            data = response.json()
    except Exception as exc:
        return f"[vision] sidecar failed: {type(exc).__name__}: {exc}"
    try:
        message = (data.get("choices") or [{}])[0].get("message") or {}
        text = _content_text(message.get("content")).strip()
    except (AttributeError, IndexError, TypeError):
        text = ""
    if not text:
        return "[vision] sidecar returned an empty description"
    _cache_set(key, text)
    return text
