from __future__ import annotations

from fastapi import APIRouter

from configs.configs import prefix
from harness import embodied

router = APIRouter(prefix=prefix, tags=["embodied"])


@router.get("/embodied/status")
async def status():
    return {
        "code": 200,
        "data": {"ok": True, "state": embodied.STATE.snapshot(), "recent": embodied.STATE.history[-10:]},
    }


@router.get("/embodied/history")
async def history():
    return {"code": 200, "data": embodied.STATE.history}


@router.post("/embodied/estop")
async def estop():
    embodied.STATE.estop = True
    embodied.STATE.speed = 0
    embodied.STATE.moving = False
    result = {"estop": True, "state": embodied.STATE.snapshot()}
    embodied.STATE.record("estop", result)
    return {"code": 200, "data": result, "message": "emergency stop triggered"}


@router.post("/embodied/reset-estop")
async def reset_estop():
    embodied.STATE.estop = False
    result = {"estop": False, "state": embodied.STATE.snapshot()}
    embodied.STATE.record("reset_estop", result)
    return {"code": 200, "data": result, "message": "emergency stop reset"}
