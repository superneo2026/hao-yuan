from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import get_harness
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["skills"])


class SkillBody(BaseModel):
    name: str = ""
    title: str = ""
    description: str = ""
    kinds: list[str] = ["*"]
    triggers: list[str] = []
    body: str = ""


@router.get("/skills")
async def list_skills():
    harness = await get_harness()
    return ok(harness.skills.list())


@router.get("/skills/{name}")
async def get_skill(name: str):
    harness = await get_harness()
    skill = harness.skills.get(name)
    if not skill:
        return fail("skill not found", 404)
    return ok(skill.to_dict(include_body=True))


@router.post("/skills")
async def create_skill(body: SkillBody):
    harness = await get_harness()
    try:
        result = harness.skills.save(body.name, body.title, body.description, body.kinds, body.triggers, body.body)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok(result)


@router.put("/skills/{name}")
async def update_skill(name: str, body: SkillBody):
    harness = await get_harness()
    try:
        result = harness.skills.save(name, body.title, body.description, body.kinds, body.triggers, body.body)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok(result)


@router.delete("/skills/{name}")
async def delete_skill(name: str):
    harness = await get_harness()
    try:
        deleted = harness.skills.delete(name)
    except ValueError as exc:
        return fail(str(exc), 400)
    return ok({"deleted": deleted})
