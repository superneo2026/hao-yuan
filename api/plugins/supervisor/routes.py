from __future__ import annotations

import json
import re
import uuid
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from configs.configs import prefix
from core.harness import harness_instance
from core.storage import now
from harness.supervisor import act as supervisor_act
from harness.supervisor import snapshot

router = APIRouter(prefix=prefix, tags=["supervisor"])

PAGE_SIZE = 20


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
        "SELECT id, title, model, created_at, updated_at FROM supervisor_chats ORDER BY updated_at DESC"
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


@router.get("/supervisor/chats/{chat_id}/messages")
async def chat_messages(chat_id: str):
    harness = harness_instance()
    rows = await harness.storage._fetch(
        "SELECT * FROM supervisor_messages WHERE chat_id=? ORDER BY created_at ASC", (chat_id,)
    )
    for row in rows:
        try:
            row["actions"] = json.loads(row.get("actions") or "[]")
        except (ValueError, TypeError):
            row["actions"] = []
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
        "Answer questions about task health, progress, blockers and next actions. Be concise and concrete.\n"
        "You may append action tokens on their own line: [[ACTION:resume:<session_id>]] or [[ACTION:cancel:<session_id>]]. "
        "Only resume sessions with status=error.\n\n"
        f"Summary: {json.dumps(snap.get('summary', {}), ensure_ascii=False)}\n"
        "Sessions:\n" + ("\n".join(lines) or "(none)")
    )


async def _run_reply(harness, chat_id: str, message: str, model: str):
    snap = await snapshot(harness.storage)
    history = []
    if chat_id:
        history = await harness.storage._fetch(
            "SELECT role, content FROM supervisor_messages WHERE chat_id=? ORDER BY created_at DESC LIMIT 12",
            (chat_id,),
        )
        history = list(reversed(history))
    provider, model_name = __import__("configs.models", fromlist=["resolve"]).resolve("", model)
    messages = [{"role": "system", "content": _system_prompt(snap)}]
    for row in history:
        if row["role"] in ("user", "assistant"):
            messages.append({"role": row["role"], "content": row.get("content") or ""})
    messages.append({"role": "user", "content": message})
    reply = await harness.gateway.complete_text(provider, model_name, messages, thinking="off")
    actions = []
    for action, sid in re.findall(r"\[\[ACTION:(\w+):([0-9a-f_]+)\]\]", reply):
        result = await supervisor_act(harness, sid, action)
        actions.append({"action": action, "session_id": sid, **result})
    clean = re.sub(r"\s*\[\[ACTION:.*?\]\]", "", reply).strip()
    if chat_id:
        exists = await harness.storage._one("SELECT id FROM supervisor_chats WHERE id=?", (chat_id,))
        ts = now()
        if not exists:
            await harness.storage._write(
                "INSERT INTO supervisor_chats(id, title, model, created_at, updated_at) VALUES (?,?,?,?,?)",
                (chat_id, message[:20], model_name, ts, ts),
            )
        await harness.storage._write(
            "INSERT INTO supervisor_messages(id, chat_id, role, content, actions, created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, chat_id, "user", message, "[]", ts),
        )
        await harness.storage._write(
            "INSERT INTO supervisor_messages(id, chat_id, role, content, actions, created_at) VALUES (?,?,?,?,?,?)",
            (uuid.uuid4().hex, chat_id, "assistant", clean, json.dumps(actions, ensure_ascii=False), now()),
        )
        await harness.storage._write("UPDATE supervisor_chats SET updated_at=?, title=? WHERE id=?", (now(), message[:20], chat_id))
    return {"reply": clean, "actions": actions, "summary": snap["summary"], "model": model_name, "provider": provider}


@router.post("/supervisor/chat")
async def chat(body: ChatBody):
    harness = harness_instance()
    if not body.message.strip():
        return {"code": 500, "data": None, "message": "message is empty"}
    result = await _run_reply(harness, body.chat_id, body.message, body.model)
    return _envelope(result)


@router.post("/supervisor/chat/stream")
async def chat_stream(body: ChatBody):
    harness = harness_instance()
    if not body.message.strip():
        return {"code": 500, "message": "message is empty"}

    async def generator():
        result = await _run_reply(harness, body.chat_id, body.message, body.model)
        yield "event: done\ndata: " + json.dumps(result, ensure_ascii=False) + "\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")
