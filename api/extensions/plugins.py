from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import get_harness
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["plugins"])


class ToggleBody(BaseModel):
    enabled: bool = True


@router.get("/plugins")
async def list_plugins():
    harness = await get_harness()
    return ok(harness.plugin_status())


@router.get("/plugins/contributions")
async def contributions():
    harness = await get_harness()
    nav, commands = [], []
    for plugin in harness.plugin_status():
        frontend = plugin.get("frontend") or {}
        for item in frontend.get("nav") or []:
            nav.append({**item, "plugin": plugin["name"]})
        for item in frontend.get("commands") or []:
            commands.append({**item, "plugin": plugin["name"]})
    return ok({"nav": nav, "commands": commands})


@router.get("/plugins/{name}")
async def get_plugin(name: str):
    harness = await get_harness()
    plugin = harness.plugins.get(name)
    if not plugin:
        return fail("plugin not found", 404)
    return ok(plugin)


@router.post("/plugins/{name}/toggle")
async def toggle_plugin(name: str, body: ToggleBody):
    harness = await get_harness()
    plugin = harness.plugins.get(name)
    if not plugin:
        return fail("plugin not found", 404)
    loaded = await harness.set_plugin_enabled(name, body.enabled)
    await harness.call_hook("plugin.toggled", name, body.enabled)
    status = harness.plugins.get(name) or {}
    error = status.get("error") or ""
    if body.enabled and not loaded:
        message = f"{name} 启用失败: {error or '未知错误'}"
    elif body.enabled:
        message = f"{name} 已启用并即时生效"
    else:
        message = f"{name} 已停用并即时生效"
    return ok(
        {
            "name": name,
            "enabled": body.enabled,
            "loaded": bool(status.get("loaded")),
            "restart_required": False,
            "error": error,
            "message": message,
        }
    )
