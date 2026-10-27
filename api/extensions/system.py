from __future__ import annotations

import platform

from fastapi import APIRouter, Query

from configs.configs import APP_NAME, APP_VERSION, DEFAULT_MODEL, DEFAULT_PROVIDER, WORKSPACE_DIR, prefix
from configs.models import PROVIDERS, list_models
from configs.secrets import is_configured, secret_source
from core.harness import get_harness
from extensions.common import ok

router = APIRouter(prefix=prefix, tags=["system"])


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
            "default_provider": DEFAULT_PROVIDER,
            "default_model": DEFAULT_MODEL,
            "providers": [
                {
                    "name": name,
                    "models": conf.models,
                    "default_model": conf.default_model,
                    "configured": is_configured(f"{name.upper()}_API_KEY") if name != "mock" else True,
                    "key_source": secret_source(f"{name.upper()}_API_KEY") if name != "mock" else "builtin",
                }
                for name, conf in PROVIDERS.items()
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
