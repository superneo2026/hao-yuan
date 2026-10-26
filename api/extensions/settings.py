from __future__ import annotations

import json
import os

from fastapi import APIRouter
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import get_harness
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["settings"])

MODES = ("ask", "allow_list", "allow_all")


class GateBody(BaseModel):
    mode: str = "ask"
    allow: list[str] = []


class WorkspaceBody(BaseModel):
    workspace: str = ""


class ValueBody(BaseModel):
    value: str = ""


@router.get("/settings")
async def read_settings():
    harness = await get_harness()
    all_values = await harness.storage.all_settings()
    gate_mode = all_values.get("gate_mode", "ask")
    try:
        gate_allow = json.loads(all_values.get("gate_allow") or "[]")
    except (ValueError, TypeError):
        gate_allow = []
    return ok(
        {
            "gate": {"mode": gate_mode, "allow": gate_allow},
            "default_workspace": all_values.get("default_workspace", ""),
            "theme": all_values.get("theme", "light"),
            "checkpoints": all_values.get("checkpoints", "1"),
            "auto_resume": all_values.get("auto_resume", "1"),
            "raw": all_values,
        }
    )


@router.put("/settings/gate")
async def write_gate(body: GateBody):
    if body.mode not in MODES:
        return fail(f"mode must be one of {MODES}")
    harness = await get_harness()
    await harness.storage.set_setting("gate_mode", body.mode)
    await harness.storage.set_setting("gate_allow", json.dumps(body.allow, ensure_ascii=False))
    await harness.events.emit("*", "settings.updated", {"gate": {"mode": body.mode, "allow": body.allow}})
    return ok({"mode": body.mode, "allow": body.allow})


@router.put("/settings/workspace")
async def write_workspace(body: WorkspaceBody):
    workspace = (body.workspace or "").strip()
    if workspace and not os.path.isdir(workspace):
        return fail(f"workspace does not exist: {workspace}")
    harness = await get_harness()
    await harness.storage.set_setting("default_workspace", workspace)
    return ok({"workspace": workspace})


@router.put("/settings/{key}")
async def write_setting(key: str, body: ValueBody):
    allowed = {"theme", "default_agent", "checkpoints", "auto_resume"}
    if key not in allowed:
        return fail(f"setting key must be one of {sorted(allowed)}", 400)
    harness = await get_harness()
    await harness.storage.set_setting(key, body.value)
    return ok({"key": key, "value": body.value})
