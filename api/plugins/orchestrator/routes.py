from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import harness_instance
from harness import orchestrator

router = APIRouter(prefix=prefix, tags=["orchestrator"])


class OrchestrationBody(BaseModel):
    goal: str
    workspace: str
    provider: str = ""
    model: str = ""
    tasks: list[dict[str, Any]] | None = None


class TaskBody(BaseModel):
    status: str
    result: str = ""


@router.post("/orchestrations")
async def create(body: OrchestrationBody):
    harness = harness_instance()
    try:
        data = await orchestrator.create_orchestration(
            harness, body.goal, body.workspace, body.provider, body.model, body.tasks
        )
        return {"code": 200, "data": data}
    except Exception as exc:
        return {"code": 500, "data": None, "message": f"{type(exc).__name__}: {exc}"}


@router.get("/orchestrations")
async def listing():
    harness = harness_instance()
    return {"code": 200, "data": await orchestrator.list_orchestrations(harness)}


@router.get("/orchestrations/{oid}")
async def detail(oid: str):
    harness = harness_instance()
    data = await orchestrator.get_orchestration(harness, oid)
    if not data:
        return {"code": 404, "data": None, "message": "orchestration not found"}
    return {"code": 200, "data": data}


@router.post("/orchestrations/{oid}/advance")
async def advance(oid: str):
    harness = harness_instance()
    return {"code": 200, "data": await orchestrator.advance(harness, oid)}


@router.post("/orchestrations/{oid}/tasks/{tid}")
async def mark(oid: str, tid: str, body: TaskBody):
    harness = harness_instance()
    await orchestrator.mark_task(harness, oid, tid, body.status, body.result)
    return {"code": 200, "data": await orchestrator.get_orchestration(harness, oid)}


@router.post("/orchestrations/{oid}/merge")
async def merge(oid: str):
    harness = harness_instance()
    ok = await orchestrator.merge_all(harness, oid)
    return {"code": 200 if ok else 500, "data": {"merged": ok}}
