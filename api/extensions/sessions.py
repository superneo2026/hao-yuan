from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from configs.configs import DEFAULT_PROVIDER, prefix
from configs.models import list_models, resolve
from core.harness import get_harness
from core.storage import now
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["sessions"])

THINKING_LEVELS = ("", "auto", "off", "low", "high")

DEFAULT_SESSION_TITLES = {
    "",
    "New task",
    "New coding task",
    "New plan",
    "New storyboard",
    "Robot task",
    "New conversation",
    "Untitled",
    "新建任务",
    "新任务",
    "新对话",
    "新会话",
    "新建会话",
    "未命名会话",
    "新方案",
    "新分镜",
    "机器人任务",
}
TITLE_LANGUAGES = {
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "en": "English",
}
_title_tasks: set[asyncio.Task] = set()


def _is_default_title(title: str) -> bool:
    return (title or "").strip() in DEFAULT_SESSION_TITLES


def _fallback_title(content: str, locale: str = "") -> str:
    text = re.sub(r"```[\s\S]*?```", " ", content or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:你好|您好|嗨|哈喽|hi|hello|hey)[，,。.!！?？\s]*", "", text, flags=re.I)
    text = re.sub(r"^(?:请|麻烦|帮我|帮忙|给我|please|can you|could you|help me)\s*", "", text, flags=re.I)
    text = text.strip(" \t\r\n\"'`“”‘’#*-")
    if not text:
        return ""
    limit = 24 if re.search(r"[\u4e00-\u9fff]", text) else 56
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _clean_title(title: str) -> str:
    value = re.sub(r"\s+", " ", title or "").strip()
    value = value.strip(" \t\r\n\"'`“”‘’#*-")
    value = re.sub(r"^(?:标题|title)\s*[：:]\s*", "", value, flags=re.I)
    value = re.sub(r"[。.!！?？]+$", "", value).strip()
    return value[:80]


async def _generate_session_title(harness, session: dict[str, Any], content: str, locale: str) -> None:
    language = TITLE_LANGUAGES.get(locale)
    if not language:
        return
    provider = session.get("provider") or DEFAULT_PROVIDER
    model = session.get("model") or ""
    title = ""
    if provider != "mock":
        messages = [
            {
                "role": "system",
                "content": (
                    f"Write a very short conversation title in {language} "
                    "(at most 8 words or 24 Chinese characters). "
                    "Reply with the title only, without quotes, numbering, or trailing punctuation."
                ),
            },
            {"role": "user", "content": (content or "")[:2000]},
        ]
        try:
            title = _clean_title(await harness.gateway.complete_text(provider, model, messages, thinking="off"))
        except Exception:
            title = ""
    if not title:
        title = _fallback_title(content)
    if not title:
        return
    try:
        current = await harness.storage.get_session(session["id"])
        if not current or not _is_default_title(current.get("title")):
            return
        await harness.storage.update_session(session["id"], title=title)
        await harness.events.emit(session["id"], "session.updated", {"title": title})
    except Exception:
        return


def _spawn_title_task(harness, session: dict[str, Any], content: str, locale: str) -> None:
    task = asyncio.create_task(_generate_session_title(harness, session, content, locale))
    _title_tasks.add(task)
    task.add_done_callback(_title_tasks.discard)


class SessionCreate(BaseModel):
    kind: str = "auto"
    title: str = ""
    provider: str = DEFAULT_PROVIDER
    model: str = ""
    workspace: str = ""
    template_id: str = ""
    thinking: str = ""
    gate_mode: str = ""
    gate_allow: list[str] = []
    skills: list[str] = []
    meta: dict[str, Any] = {}


class MessageSend(BaseModel):
    content: str
    locale: str = ""


class TitleBody(BaseModel):
    title: str


class ModelBody(BaseModel):
    provider: str = ""
    model: str = ""


class ThinkingBody(BaseModel):
    thinking: str = ""


class WorkspaceBody(BaseModel):
    workspace: str = ""


class GateBody(BaseModel):
    mode: str = ""
    allow: list[str] = []


class ConfirmBody(BaseModel):
    call_id: str
    ok: bool = True


def _pending(harness, session_id: str):
    return harness.manager.get_pending(session_id)


RUN_TERMINAL_STATUSES = {"done", "error", "cancelled", "completed", "failed", "idle"}
SESSION_TERMINAL_STATUSES = {"done", "error", "cancelled", "idle"}


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _elapsed_seconds(start: str, end: str) -> float:
    began = _parse_ts(start)
    if not began:
        return 0.0
    finished = _parse_ts(end) or datetime.now()
    return round(max(0.0, (finished - began).total_seconds()), 1)


def _message_usage(row: dict[str, Any]) -> dict[str, Any]:
    prompt = int(row.get("prompt_tokens") or 0)
    completion = int(row.get("completion_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "cached_tokens": int(row.get("cached_tokens") or 0),
        "reasoning_tokens": int(row.get("reasoning_tokens") or 0),
        "cost_est": float(row.get("cost_est") or 0),
    }


@router.get("/models")
async def models():
    return ok({"providers": list_models()})


@router.get("/agents")
async def agents():
    harness = await get_harness()
    return ok(harness.agents.list())


@router.get("/tools")
async def tools():
    harness = await get_harness()
    return ok([spec.model_dump() for spec in harness.tools.list_specs()])


@router.post("/sessions")
async def create_session(body: SessionCreate):
    harness = await get_harness()
    if body.kind not in ("auto", "dev", "coding", "plan", "video", "robot", "general"):
        return fail("kind must be auto/dev/plan/video/robot/general")
    if body.thinking not in THINKING_LEVELS:
        return fail("thinking must be empty/auto/off/low/high")
    if body.workspace and not os.path.isdir(body.workspace):
        return fail(f"workspace does not exist: {body.workspace}")
    provider, model = resolve(body.provider, body.model)
    title = body.title or {
        "auto": "New task",
        "dev": "New coding task",
        "coding": "New coding task",
        "plan": "New plan",
        "video": "New storyboard",
        "robot": "Robot task",
        "general": "New conversation",
    }.get(body.kind, "New task")
    session = await harness.manager.create_session(
        kind=body.kind,
        title=title,
        provider=provider,
        model=model,
        workspace=body.workspace.strip(),
        template_id=body.template_id,
        thinking=body.thinking,
        gate_mode=body.gate_mode if body.gate_mode in ("", "ask", "allow_list", "allow_all") else "",
        gate_allow=body.gate_allow,
        skills=body.skills,
        meta=body.meta,
    )
    await harness.events.emit(session["id"], "session.created", {"session": session})
    return ok(session)


@router.get("/sessions")
async def list_sessions(include_hidden: bool = True):
    harness = await get_harness()
    sessions = await harness.manager.list_sessions(include_hidden=include_hidden)
    for session in sessions:
        session["pending"] = _pending(harness, session["id"])
    return ok(sessions)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    harness = await get_harness()
    session = await harness.manager.get_session(session_id)
    if not session:
        return fail("session not found", 404)
    first = await harness.storage.first_user_message(session_id)
    session["first_question"] = (first or {}).get("content", "")[:200] if first else ""
    session["pending"] = _pending(harness, session_id)
    last_event = await harness.storage.last_event(session_id)
    session["last_event_id"] = int(last_event["id"]) if last_event else 0
    runs = await harness.storage._fetch(
        "SELECT id, status, provider, model, output, error, step_count, created_at, updated_at"
        " FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT 20",
        (session_id,),
    )
    for run in runs:
        # Single canonical lowercase status; callers should not have to normalise.
        status = str(run.get("status") or "").lower()
        run["status"] = status
        run["finished"] = status in RUN_TERMINAL_STATUSES
        run["started_at"] = run.get("created_at") or ""
        run["finished_at"] = run.get("updated_at") if run["finished"] else ""
        run["elapsed_s"] = _elapsed_seconds(run.get("created_at") or "", run.get("updated_at") or "")
    session["status"] = str(session.get("status") or "").lower()
    session["active"] = harness.manager.is_active(session_id)
    latest = runs[0] if runs else {}
    session["started_at"] = latest.get("created_at") or session.get("created_at") or ""
    session["finished_at"] = latest.get("finished_at") or ""
    session["elapsed_s"] = (
        latest.get("elapsed_s")
        if latest
        else _elapsed_seconds(session.get("created_at") or "", session.get("updated_at") or "")
    )
    session["finished"] = session["status"] in SESSION_TERMINAL_STATUSES and not session["active"]
    session["checkpoint"] = await harness.storage.latest_checkpoint(session_id)
    return ok({"session": session, "runs": runs})


@router.patch("/sessions/{session_id}")
async def patch_session(session_id: str, body: dict[str, Any]):
    harness = await get_harness()
    session = await harness.manager.get_session(session_id)
    if not session:
        return fail("session not found", 404)
    active = harness.manager.is_active(session_id) or session["status"] in ("running", "queued", "waiting_input")
    fields: dict[str, Any] = {}
    if "title" in body and body["title"]:
        fields["title"] = str(body["title"]).strip()[:200]
    if "workspace" in body:
        if active:
            return fail("stop the session before changing workspace")
        workspace = str(body.get("workspace") or "").strip()
        if workspace and not os.path.isdir(workspace):
            return fail(f"workspace does not exist: {workspace}")
        fields["workspace"] = workspace
    if "thinking" in body:
        if body["thinking"] not in THINKING_LEVELS:
            return fail("invalid thinking level")
        fields["thinking"] = body["thinking"]
    if "model" in body or "provider" in body:
        if active:
            return fail("stop the session before switching model")
        provider, model = resolve(body.get("provider") or session["provider"], body.get("model") or "")
        fields["provider"] = provider
        fields["model"] = model
    if "gate_mode" in body:
        mode = body["gate_mode"]
        if mode not in ("", "ask", "allow_list", "allow_all"):
            return fail("invalid gate mode")
        fields["gate_mode"] = mode
        fields["gate_allow"] = json.dumps(body.get("gate_allow") or [], ensure_ascii=False) if body.get("gate_allow") else ""
    if "skills" in body:
        fields["skills"] = json.dumps([s for s in body.get("skills") or [] if isinstance(s, str)], ensure_ascii=False)
    if "kind" in body and body["kind"] in ("auto", "dev", "coding", "plan", "video", "robot", "general"):
        fields["kind"] = body["kind"]
    if fields:
        await harness.storage.update_session(session_id, **fields)
        await harness.events.emit(session_id, "session.updated", fields)
    return ok(await harness.manager.get_session(session_id))


@router.delete("/sessions/{session_id}")
async def hide_session(session_id: str):
    harness = await get_harness()
    if not await harness.manager.get_session(session_id):
        return fail("session not found", 404)
    await harness.manager.archive(session_id)
    return ok({"hidden": session_id})


@router.post("/sessions/{session_id}/unhide")
async def unhide_session(session_id: str):
    harness = await get_harness()
    if not await harness.manager.get_session(session_id):
        return fail("session not found", 404)
    await harness.manager.unhide(session_id)
    return ok(await harness.manager.get_session(session_id))


@router.delete("/sessions/{session_id}/purge")
async def purge_session(session_id: str):
    harness = await get_harness()
    if not await harness.manager.get_session(session_id):
        return fail("session not found", 404)
    await harness.manager.purge(session_id)
    await harness.storage.vacuum()
    return ok({"purged": session_id})


@router.post("/sessions/{session_id}/clear")
async def clear_session(session_id: str):
    harness = await get_harness()
    if not await harness.manager.get_session(session_id):
        return fail("session not found", 404)
    await harness.manager.cancel(session_id)
    harness.manager.clear_pending(session_id)
    await harness.storage.delete_messages(session_id)
    await harness.storage.delete_events(session_id)
    await harness.storage.clear_checkpoints(session_id)
    await harness.storage.update_session(session_id, summary="", summary_upto=0, plan="", status="idle", error="")
    await harness.events.emit(session_id, "session.cleared", {"id": session_id})
    return ok({"cleared": session_id})


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    harness = await get_harness()
    rows = await harness.storage.list_messages(session_id)
    for row in rows:
        row["usage"] = _message_usage(row)
    return ok(rows)


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageSend):
    harness = await get_harness()
    content = (body.content or "").strip()
    if not content:
        return fail("message is empty")
    session = await harness.manager.get_session(session_id)
    if not session:
        return fail("session not found", 404)
    active = harness.manager.is_active(session_id) or session["status"] in ("running", "queued", "waiting_input")
    if not active:
        try:
            plan = json.loads(session.get("plan") or "{}")
            steps = plan.get("steps") or []
            if steps and all(step.get("s") in ("done", "failed", "skipped") for step in steps):
                plan["steps"] = []
                await harness.storage.update_session(session_id, plan=json.dumps(plan, ensure_ascii=False))
        except (ValueError, TypeError):
            pass
    message = await harness.storage.add_message(session_id, "", "user", content)
    await harness.events.emit(
        session_id,
        "message.saved",
        {"msg_id": message["id"], "role": "user", "content": content, "appended": active},
    )
    if body.locale and _is_default_title(session.get("title")):
        first = await harness.storage.first_user_message(session_id)
        if first and first["id"] == message["id"]:
            _spawn_title_task(harness, session, content, body.locale)
    if not active:
        harness.manager.enqueue(session_id)
    return ok({"msg_id": message["id"], "session_id": session_id, "appended": active})


@router.get("/sessions/{session_id}/events")
async def get_events(session_id: str, after_id: int = 0, limit: int = 2000):
    harness = await get_harness()
    return ok(await harness.events.replay(session_id, after_id=after_id, limit=limit))


@router.get("/sessions/{session_id}/stream")
async def stream_events(session_id: str, request: Request, after_id: int = 0):
    harness = await get_harness()
    header_last = request.headers.get("last-event-id", "").strip()
    if after_id == 0 and header_last.isdigit():
        after_id = int(header_last)

    async def generator():
        cursor = after_id
        idle = 0
        while True:
            events = await harness.events.replay(session_id, after_id=cursor)
            for event in events:
                cursor = event["id"]
                idle = 0
                yield (
                    f"id: {event['id']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                )
            session = await harness.storage.get_session(session_id)
            if events:
                continue
            idle += 1
            if idle % 15 == 0:
                yield ": ping\n\n"
            if session and session["status"] in ("done", "error", "idle") and not harness.manager.is_active(session_id):
                yield f"data: {json.dumps({'type': 'stream.end', 'status': session['status'], 'last_seq': cursor}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str):
    harness = await get_harness()
    cancelled = await harness.manager.cancel(session_id)
    if not cancelled:
        session = await harness.manager.get_session(session_id)
        if session and session["status"] in ("running", "queued", "waiting_input"):
            await harness.storage.update_session(session_id, status="error", error="用户取消")
    return ok({"cancelled": cancelled})


@router.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str):
    harness = await get_harness()
    session = await harness.manager.get_session(session_id)
    if not session:
        return fail("session not found", 404)
    if harness.manager.is_active(session_id):
        return ok({"resumed": False, "reason": "already active"})
    if session["status"] not in ("error", "idle"):
        return ok({"resumed": False, "reason": "only error/idle sessions can resume"})
    has_user = await harness.storage.first_user_message(session_id)
    if not has_user:
        return ok({"resumed": False, "reason": "no user message"})
    harness.manager.mark_resume(session_id)
    await harness.storage.update_session(session_id, status="idle", error="")
    queued = harness.manager.enqueue(session_id)
    return ok({"resumed": queued})


@router.post("/sessions/{session_id}/confirm")
async def confirm(session_id: str, body: ConfirmBody):
    harness = await get_harness()
    resolved = await harness.manager.resolve_by_call(session_id, body.call_id, body.ok)
    return ok({"resolved": resolved})


@router.get("/sessions/{session_id}/artifacts")
async def artifacts(session_id: str):
    harness = await get_harness()
    return ok(await harness.storage.list_artifacts(session_id))


@router.get("/sessions/{session_id}/pending")
async def pending(session_id: str):
    harness = await get_harness()
    return ok(harness.manager.get_pending(session_id))


@router.post("/voice-chat")
async def voice_chat(body: MessageSend):
    harness = await get_harness()
    content = (body.content or "").strip()
    if not content:
        return fail("message is empty")
    provider, model = resolve("", "")
    reply = await harness.gateway.complete_text(
        provider,
        model,
        [
            {"role": "system", "content": "You are a voice assistant. Reply in spoken Chinese, at most 3 short sentences. No markdown."},
            {"role": "user", "content": content},
        ],
        thinking="off",
    )
    return ok({"reply": reply, "model": {"provider": provider, "model": model}})
