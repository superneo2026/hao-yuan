from __future__ import annotations

import platform

from fastapi import APIRouter, Body, Query

from configs.configs import APP_NAME, APP_VERSION, WORKSPACE_DIR, prefix
from configs import models as models_mod
from configs.models import list_models
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
