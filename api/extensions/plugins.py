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
    await harness.set_plugin_enabled(name, body.enabled)
    return ok(
        {
            "name": name,
            "enabled": body.enabled,
            "restart_required": True,
            "message": "Plugin state saved. Restart the API to load or unload plugin routes and tools.",
        }
    )
