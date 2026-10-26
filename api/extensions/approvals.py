from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import get_harness
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["approvals"])


class ResolveBody(BaseModel):
    approved: bool = True
    reason: str = ""


@router.get("/approvals")
async def list_approvals(status: str | None = Query("pending"), session_id: str | None = None):
    harness = await get_harness()
    return ok(await harness.storage.list_approvals(status=status, session_id=session_id))


@router.post("/approvals/{approval_id}/resolve")
async def resolve(approval_id: str, body: ResolveBody):
    harness = await get_harness()
    approval = await harness.storage.get_approval(approval_id)
    if not approval:
        return fail("approval not found", 404)
    if approval["status"] != "pending":
        return fail(f"approval already resolved: {approval['status']}", 409)
    resolved = await harness.manager.resolve_approval(approval_id, body.approved, body.reason, "rest")
    return ok({"approval": resolved, "session_id": approval["session_id"]})
