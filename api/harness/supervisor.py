from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from configs.configs import (
    SUPERVISOR_AUTO_CANCEL_SEC,
    SUPERVISOR_AUTO_RESUME,
    SUPERVISOR_DAILY_COST_CAP,
    SUPERVISOR_INTERVAL,
    SUPERVISOR_RESUME_BACKOFF_SEC,
    SUPERVISOR_RESUME_KEYWORDS,
    SUPERVISOR_RESUME_MAX,
    SUPERVISOR_RESUME_MAX_BACKOFF_SEC,
    SUPERVISOR_STALE_SEC,
)


_RESUME_STATE: dict[str, dict[str, float]] = {}


def _resumable_error(error: str) -> bool:
    text = (error or "").lower()
    return any(keyword.lower() in text for keyword in SUPERVISOR_RESUME_KEYWORDS)


def _resume_delay(attempts: int) -> float:
    if SUPERVISOR_RESUME_BACKOFF_SEC <= 0:
        return 0.0
    delay = SUPERVISOR_RESUME_BACKOFF_SEC * (2 ** max(0, attempts - 1))
    return min(delay, SUPERVISOR_RESUME_MAX_BACKOFF_SEC)


def reset_resume_state(session_id: str | None = None) -> None:
    if session_id is None:
        _RESUME_STATE.clear()
    else:
        _RESUME_STATE.pop(session_id, None)


async def _auto_resume(harness, item: dict[str, Any]) -> bool:
    """Resume an interrupted long-running session with backoff and a cost cap."""
    if not SUPERVISOR_AUTO_RESUME or item.get("health") != "error":
        return False
    session_id = item["id"]
    if not _resumable_error(item.get("error") or item.get("reason") or ""):
        return False
    state = _RESUME_STATE.setdefault(session_id, {"attempts": 0.0, "next_at": 0.0})
    current = time.time()
    if current < state["next_at"]:
        return False
    if SUPERVISOR_RESUME_MAX > 0 and state["attempts"] >= SUPERVISOR_RESUME_MAX:
        state["next_at"] = current + SUPERVISOR_RESUME_MAX_BACKOFF_SEC
        await harness.events.emit(
            session_id,
            "supervisor.alert",
            {
                "health": "resume-exhausted",
                "reason": f"auto-resume stopped after {int(state['attempts'])} attempts",
                "attempts": int(state["attempts"]),
            },
        )
        return False
    if SUPERVISOR_DAILY_COST_CAP > 0:
        usage = await harness.storage.usage_today()
        spent = float(usage.get("cost_est") or 0)
        if spent >= SUPERVISOR_DAILY_COST_CAP:
            state["next_at"] = current + SUPERVISOR_RESUME_MAX_BACKOFF_SEC
            await harness.events.emit(
                session_id,
                "supervisor.alert",
                {
                    "health": "cost-capped",
                    "reason": f"daily cost cap reached ({spent:.4f} >= {SUPERVISOR_DAILY_COST_CAP:.4f})",
                    "cost_est": spent,
                },
            )
            return False
    session = await harness.storage.get_session(session_id)
    if not session or session.get("status") != "error":
        return False
    harness.manager.mark_resume(session_id)
    await harness.storage.update_session(session_id, status="idle", error="")
    if not harness.manager.enqueue(session_id):
        return False
    state["attempts"] += 1
    delay = _resume_delay(int(state["attempts"]))
    state["next_at"] = current + delay
    await harness.events.emit(
        session_id,
        "supervisor.alert",
        {
            "health": "auto-resumed",
            "reason": (item.get("error") or item.get("reason") or "resumed")[:120],
            "attempt": int(state["attempts"]),
            "backoff_sec": delay,
        },
    )
    return True


async def _cancel_stale(harness, session_id: str) -> None:
    await harness.manager.cancel(session_id)
    deadline = time.time() + 15
    while harness.manager.is_active(session_id) and time.time() < deadline:
        await asyncio.sleep(0.2)
    await harness.storage.update_session(session_id, status="error", error="stale: no progress")
    await harness.events.emit(
        session_id,
        "supervisor.alert",
        {"health": "cancelled", "reason": "auto-cancelled after no progress"},
    )


def _parse_ts(value: str) -> float:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return 0.0


async def session_health(storage, session: dict[str, Any]) -> dict[str, Any]:
    session_id = session["id"]
    last = await storage.last_event(session_id)
    last_type = (last or {}).get("type", "")
    last_ts = _parse_ts((last or {}).get("created_at", "")) if last else 0.0
    idle_sec = int(datetime.now().timestamp() - last_ts) if last_ts else -1
    plan_done = plan_total = 0
    try:
        plan = json.loads(session.get("plan") or "{}")
        steps = plan.get("steps") or []
        plan_total = len(steps)
        plan_done = sum(1 for step in steps if step.get("s") == "done")
    except (ValueError, TypeError):
        pass
    health = "ok"
    reason = ""
    status = session.get("status")
    if status == "running" and idle_sec > SUPERVISOR_STALE_SEC:
        health = "stale"
        reason = f"running with no events for {idle_sec // 60} minutes"
    elif status == "error":
        health = "error"
        reason = (session.get("error") or "task failed")[:120]
    elif status == "waiting_input":
        health = "waiting"
        reason = "waiting for approval"
    first = await storage.first_user_message(session_id)
    try:
        skills = json.loads(session.get("skills_used") or "[]")
    except (ValueError, TypeError):
        skills = []
    return {
        "id": session_id,
        "kind": session.get("kind"),
        "title": session.get("title"),
        "status": status,
        "health": health,
        "reason": reason,
        "error": session.get("error") or "",
        "first_question": (first or {}).get("content", "")[:60] if first else "",
        "skills_used": skills,
        "last_event": last_type,
        "idle_sec": idle_sec,
        "plan_done": plan_done,
        "plan_total": plan_total,
        "context_tokens": session.get("context_tokens") or 0,
        "workspace": session.get("workspace") or "",
        "updated_at": session.get("updated_at"),
    }


async def snapshot(storage) -> dict[str, Any]:
    rows = await storage._fetch(
        "SELECT * FROM sessions WHERE status != 'archived' AND (hidden=0 OR status IN ('running','queued','waiting_input'))"
        " ORDER BY updated_at DESC"
    )
    items = []
    for row in rows:
        try:
            items.append(await session_health(storage, row))
        except Exception as exc:
            logging.getLogger(__name__).warning("supervisor health failed for %s: %s", row.get("id"), exc)
    alerts = [item for item in items if item["health"] in ("stale", "error")]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stale_sec": SUPERVISOR_STALE_SEC,
        "summary": {
            "total": len(items),
            "active": sum(1 for item in items if item["status"] in ("running", "queued")),
            "waiting": sum(1 for item in items if item["health"] == "waiting"),
            "alerts": len(alerts),
            "done": sum(1 for item in items if item["status"] == "done"),
        },
        "alerts": alerts,
        "items": items,
    }


async def act(harness, session_id: str, action: str) -> dict[str, Any]:
    session = await harness.storage.get_session(session_id)
    if not session:
        return {"ok": False, "message": "session not found"}
    if action == "cancel":
        ok = await harness.manager.cancel(session_id)
        message = "stopped" if ok else "no active task"
    elif action == "resume":
        if session["status"] != "error" or session.get("error") == "用户取消":
            return {"ok": False, "message": "only interrupted error sessions can resume"}
        harness.manager.mark_resume(session_id)
        await harness.storage.update_session(session_id, status="idle", error="")
        ok = harness.manager.enqueue(session_id)
        message = "re-queued" if ok else "already active"
    elif action == "ack":
        ok, message = True, "acknowledged"
    else:
        return {"ok": False, "message": f"unsupported action: {action}"}
    await harness.events.emit(session_id, "supervisor.action", {"action": action, "ok": bool(ok), "message": message})
    return {"ok": bool(ok), "message": message}


async def watch_loop(harness) -> None:
    while True:
        try:
            await asyncio.sleep(SUPERVISOR_INTERVAL)
            snap = await snapshot(harness.storage)
            for item in snap["items"]:
                if item["id"] not in _RESUME_STATE:
                    continue
                progressing = item.get("status") == "done" or (
                    item.get("status") in ("running", "queued")
                    and item.get("idle_sec", -1) < SUPERVISOR_STALE_SEC
                )
                if progressing:
                    reset_resume_state(item["id"])
            for item in snap["alerts"]:
                if (
                    item["health"] == "stale"
                    and SUPERVISOR_AUTO_CANCEL_SEC
                    and item.get("idle_sec", 0) >= SUPERVISOR_AUTO_CANCEL_SEC
                ):
                    await _cancel_stale(harness, item["id"])
                    item = {**item, "health": "error", "error": "stale: no progress"}
                if item["health"] == "error":
                    await _auto_resume(harness, item)
            await harness.events.emit("*", "supervisor.snapshot", snap)
        except asyncio.CancelledError:
            raise
        except Exception:
            continue
