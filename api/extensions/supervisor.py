from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from configs.configs import prefix
from configs.models import resolve
from core.harness import harness_instance
from core.storage import now
from harness.supervisor import act as supervisor_act
from harness.supervisor import snapshot

router = APIRouter(prefix=prefix, tags=["supervisor"])

PAGE_SIZE = 20
HISTORY_TURNS = 12


def _envelope(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"code": 200, "data": data, "message": message}


class ActBody(BaseModel):
    session_id: str
    action: str


class ChatBody(BaseModel):
    message: str
    chat_id: str = ""
    model: str = ""


@router.get("/supervisor/overview")
async def overview():
    harness = harness_instance()
    return _envelope(await snapshot(harness.storage))


@router.get("/supervisor/console")
async def console(page: int = 1):
    harness = harness_instance()
    snap = await snapshot(harness.storage)
    items = snap["items"]
    total = len(items)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, pages))
    start = (page - 1) * PAGE_SIZE
    return _envelope(
        {
            **snap,
            "items": items[start : start + PAGE_SIZE],
            "page": page,
            "pages": pages,
            "total": total,
        }
    )


@router.post("/supervisor/act")
async def act(body: ActBody):
    harness = harness_instance()
    result = await supervisor_act(harness, body.session_id, body.action)
    return {"code": 200 if result.get("ok") else 500, "data": result, "message": result.get("message", "")}


async def _list_chats(harness):
    return await harness.storage._fetch(
        "SELECT c.id, c.title, c.model, c.created_at, c.updated_at,"
        " (SELECT COUNT(*) FROM supervisor_messages m WHERE m.chat_id=c.id) AS message_count,"
        " (SELECT content FROM supervisor_messages m WHERE m.chat_id=c.id ORDER BY m.created_at DESC LIMIT 1) AS last_message"
        " FROM supervisor_chats c ORDER BY c.updated_at DESC"
    )


@router.get("/supervisor/chats")
async def list_chats():
    harness = harness_instance()
    return _envelope(await _list_chats(harness))


@router.post("/supervisor/chats")
async def create_chat():
    harness = harness_instance()
    cid = uuid.uuid4().hex
    ts = now()
    await harness.storage._write(
        "INSERT INTO supervisor_chats(id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
        (cid, "New conversation", "", ts, ts),
    )
    return _envelope({"id": cid, "title": "New conversation", "created_at": ts, "updated_at": ts})


def _decode_actions(value: Any) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


@router.get("/supervisor/chats/{chat_id}/messages")
async def chat_messages(chat_id: str):
    harness = harness_instance()
    rows = await harness.storage._fetch(
        "SELECT * FROM supervisor_messages WHERE chat_id=? ORDER BY created_at ASC, rowid ASC", (chat_id,)
    )
    for row in rows:
        row["actions"] = _decode_actions(row.get("actions"))
        try:
            row["usage"] = json.loads(row.get("usage") or "{}")
        except (ValueError, TypeError):
            row["usage"] = {}
    return _envelope(rows)


@router.delete("/supervisor/chats/{chat_id}")
async def delete_chat(chat_id: str):
    harness = harness_instance()
    await harness.storage._write("DELETE FROM supervisor_messages WHERE chat_id=?", (chat_id,))
    await harness.storage._write("DELETE FROM supervisor_chats WHERE id=?", (chat_id,))
    return _envelope({"deleted": chat_id})


def _system_prompt(snap: dict[str, Any]) -> str:
    lines = []
    for item in snap.get("items", []):
        lines.append(
            f"- [{item['id'][:8]}] {item['kind']} | {item['title'][:40]} | status={item['status']} "
            f"health={item['health']} plan={item['plan_done']}/{item['plan_total']} "
            f"tokens={item['context_tokens']}" + (f" ({item['reason']})" if item.get("reason") else "")
        )
    return (
        "You are HaoYuan Supervisor, the operations lead for all AI coding sessions. "
        "Answer questions about task health, progress, blockers and next actions. Be concise and concrete. "
        "You may use Markdown (short lists, bold, code) to make the answer easy to scan.\n"
        "You may append action tokens on their own line: [[ACTION:resume:<session_id>]] or [[ACTION:cancel:<session_id>]]. "
        "Only resume sessions with status=error.\n\n"
        f"Summary: {json.dumps(snap.get('summary', {}), ensure_ascii=False)}\n"
        "Sessions:\n" + ("\n".join(lines) or "(none)")
    )


async def _ensure_chat(harness, chat_id: str, title: str, model_name: str) -> str:
    cid = chat_id.strip() or uuid.uuid4().hex
    ts = now()
    exists = await harness.storage._one("SELECT id FROM supervisor_chats WHERE id=?", (cid,))
    if not exists:
        await harness.storage._write(
            "INSERT INTO supervisor_chats(id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, (title or "New conversation")[:40], model_name, ts, ts),
        )
    else:
        await harness.storage._write(
            "UPDATE supervisor_chats SET updated_at=?, model=? WHERE id=?", (ts, model_name, cid)
        )
    return cid


async def _history(harness, chat_id: str) -> list[dict[str, Any]]:
    rows = await harness.storage._fetch(
        "SELECT role, content FROM supervisor_messages WHERE chat_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (chat_id, HISTORY_TURNS),
    )
    return [row for row in reversed(rows) if row.get("role") in ("user", "assistant")]


async def _stream_reply(
    harness, chat_id: str, message: str, model: str
) -> AsyncGenerator[dict[str, Any], None]:
    provider, model_name = resolve("", model)
    chat_id = await _ensure_chat(harness, chat_id, message, model_name)
    history = await _history(harness, chat_id)
    snap = await snapshot(harness.storage)

    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(snap)}]
    messages.extend({"role": row["role"], "content": row.get("content") or ""} for row in history)
    messages.append({"role": "user", "content": message})

    user_ts = now()
    await harness.storage._write(
        "INSERT INTO supervisor_messages(id, chat_id, role, content, actions, model, provider, usage, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, chat_id, "user", message, "[]", model_name, provider, "{}", user_ts),
    )
    yield {
        "type": "meta",
        "chat_id": chat_id,
        "provider": provider,
        "model": model_name,
        "created_at": user_ts,
    }

    parts: list[str] = []
    usage: dict[str, Any] = {}
    finish_reason = "stop"
    try:
        async for event in harness.gateway.stream(provider, model_name, messages, tools=None, thinking="off"):
            etype = event.get("type")
            if etype == "delta":
                text = event.get("text") or ""
                if text:
                    parts.append(text)
                    yield {"type": "delta", "text": text}
            elif etype == "reasoning":
                text = event.get("text") or ""
                if text:
                    yield {"type": "reasoning", "text": text}
            elif etype == "message":
                usage = event.get("usage") or {}
                provider = event.get("provider") or provider
                model_name = event.get("model") or model_name
                finish_reason = event.get("finish_reason") or finish_reason
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        await harness.storage._write(
            "INSERT INTO supervisor_messages(id, chat_id, role, content, actions, model, provider, usage, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, chat_id, "assistant", f"⚠️ {error}", "[]", model_name, provider, "{}", now()),
        )
        yield {"type": "error", "chat_id": chat_id, "message": error, "model": model_name, "provider": provider}
        return

    full = "".join(parts)
    actions = []
    for action, sid in re.findall(r"\[\[ACTION:(\w+):([0-9a-f_]+)\]\]", full):
        result = await supervisor_act(harness, sid, action)
        actions.append({"action": action, "session_id": sid, **result})
    clean = re.sub(r"\s*\[\[ACTION:.*?\]\]", "", full).strip()

    await harness.storage._write(
        "INSERT INTO supervisor_messages(id, chat_id, role, content, actions, model, provider, usage, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            uuid.uuid4().hex,
            chat_id,
            "assistant",
            clean,
            json.dumps(actions, ensure_ascii=False),
            model_name,
            provider,
            json.dumps(usage, ensure_ascii=False),
            now(),
        ),
    )
    await harness.storage._write(
        "UPDATE supervisor_chats SET updated_at=?, title=?, model=? WHERE id=?",
        (now(), message[:40], model_name, chat_id),
    )
    yield {
        "type": "done",
        "reply": clean,
        "chat_id": chat_id,
        "actions": actions,
        "model": model_name,
        "provider": provider,
        "usage": usage,
        "finish_reason": finish_reason,
        "summary": snap.get("summary", {}),
    }


@router.post("/supervisor/chat")
async def chat(body: ChatBody):
    harness = harness_instance()
    if not body.message.strip():
        return {"code": 500, "data": None, "message": "message is empty"}
    result: dict[str, Any] = {}
    async for event in _stream_reply(harness, body.chat_id, body.message.strip(), body.model):
        if event.get("type") == "done":
            result = event
        elif event.get("type") == "error":
            return {"code": 500, "data": event, "message": event.get("message") or "chat failed"}
    if not result:
        return {"code": 500, "data": None, "message": "model returned no reply"}
    return _envelope(result)


@router.post("/supervisor/chat/stream")
async def chat_stream(body: ChatBody):
    harness = harness_instance()
    if not body.message.strip():
        return {"code": 500, "message": "message is empty"}

    async def generator():
        async for event in _stream_reply(harness, body.chat_id, body.message.strip(), body.model):
            yield f"event: {event.get('type', 'message')}\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
