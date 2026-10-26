from __future__ import annotations

import json
import re
from typing import Any

from configs.configs import (
    CONTEXT_COMPACT_TOKENS,
    CONTEXT_HARD_LIMIT,
    CONTEXT_HARD_TRUNCATE_CHARS,
    CONTEXT_KEEP_RECENT,
    CONTEXT_SUMMARY_MAX_CHARS,
    DIGEST_HEAD_CHARS,
    DIGEST_TAIL_CHARS,
    MID_COMPACT_EVERY,
    MID_COMPACT_MIN_MSGS,
    MID_COMPACT_TOKENS,
    STRUCTURED_DIGEST_ENABLED,
    TOOL_AGING_CHARS,
    TOOL_AGING_KEEP,
)
from core.gateway import ModelGateway
from core.storage import Storage

AGED_MARK = "\n...[aged: full result remains in session history; re-read the target if needed]"
TRUNC_MARK = "\n...[truncated by hard context budget; use a precise tool call to fetch details]"

_DIGEST_KEEP_RE = re.compile(
    r'File\s+"[^"]+",\s*line\s+\d+|'
    r"[\w./\\-]+\.(?:py|js|ts|tsx|java|go|rs):\d+|"
    r"^\s*E\s{1,3}\S.*$|"
    r"^(?:FAILED|ERROR|Traceback|AssertionError|\w*(?:Error|Exception):).*$|"
    r"^\$\s.*$",
    re.M,
)

SUMMARIZE_PROMPT = (
    "You are a conversation memory compressor for a coding agent. Compress the given history into a compact, "
    "fact-complete working memory. Keep: goal, completed changes, key file paths, decisions, open problems, "
    "and next steps. Drop small talk, repetition, and raw tool output. Use concise bullet points in the "
    "language of the conversation. If an existing summary is given, merge and deduplicate. Max 400 words."
)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages:
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
        ascii_count = sum(1 for char in content if ord(char) < 128)
        total += ascii_count // 4 + (len(content) - ascii_count) + 8
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            total += len(function.get("arguments") or "") // 4 + 12
    return total


def structured_digest(text: str, head: int | None = None, tail: int | None = None) -> str:
    head = DIGEST_HEAD_CHARS if head is None else head
    tail = DIGEST_TAIL_CHARS if tail is None else tail
    if len(text) <= head + tail + 200:
        return text
    if not STRUCTURED_DIGEST_ENABLED:
        return text[: head + tail]
    try:
        keep_lines, used = [], 0
        for line in text.splitlines():
            if _DIGEST_KEEP_RE.search(line + "\n") or _DIGEST_KEEP_RE.match(line):
                if used + len(line) + 1 > max(600, head // 2):
                    break
                keep_lines.append(line.strip()[:240])
                used += len(line) + 1
        middle = "\n".join(keep_lines[:20]) if keep_lines else ""
        return (
            text[:head]
            + ("\n...[middle omitted, key observations]...\n" + middle if middle else "")
            + ("\n...\n" + text[-tail:] if tail else "")
            + " (structured digest; full text remains in session history)"
        )
    except Exception:
        return text[: head + tail]


def _row_to_message(row: dict[str, Any]) -> dict[str, Any]:
    role = row["role"]
    content = row.get("content") or ""
    if role == "assistant":
        message: dict[str, Any] = {"role": "assistant", "content": content or None}
        if row.get("tool_args"):
            try:
                calls = json.loads(row["tool_args"])
                if calls:
                    message["tool_calls"] = calls
            except (ValueError, TypeError):
                pass
        return message
    if role == "tool":
        return {"role": "tool", "tool_call_id": row.get("tool_call_id") or "", "content": content}
    return {"role": role, "content": content}


def sanitize(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index = 0
    while index < len(messages) and messages[index].get("role") != "user":
        index += 1
    messages = messages[index:]
    out: list[dict[str, Any]] = []
    i = 0
    while i < len(messages):
        message = messages[i]
        if message.get("role") == "assistant" and message.get("tool_calls"):
            ids = [call.get("id") for call in message["tool_calls"]]
            j = i + 1
            tools = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tools.append(messages[j])
                j += 1
            got = {tool.get("tool_call_id") for tool in tools}
            if set(ids).issubset(got):
                out.append(message)
                out.extend(tools)
                i = j
            else:
                if message.get("content"):
                    out.append({"role": "assistant", "content": message["content"]})
                i += 1
        elif message.get("role") == "tool":
            i += 1
        else:
            out.append(message)
            i += 1
    return out


def age_tool_results(messages: list[dict[str, Any]], keep: int | None = None, chars: int | None = None) -> int:
    keep = TOOL_AGING_KEEP if keep is None else keep
    chars = TOOL_AGING_CHARS if chars is None else chars
    indices = [i for i, message in enumerate(messages) if message.get("role") == "tool"]
    targets = indices[:-keep] if keep > 0 else indices
    aged = 0
    for index in targets:
        content = messages[index].get("content") or ""
        if len(content) > chars:
            body = (
                structured_digest(content, head=max(chars, DIGEST_HEAD_CHARS), tail=DIGEST_TAIL_CHARS)
                if len(content) > DIGEST_HEAD_CHARS + DIGEST_TAIL_CHARS
                else content[:chars]
            )
            messages[index] = {**messages[index], "content": body + AGED_MARK}
            aged += 1
    return aged


def enforce_hard_budget(messages: list[dict[str, Any]], limit: int | None = None) -> int:
    limit = CONTEXT_HARD_LIMIT if limit is None else limit
    if estimate_tokens(messages) <= limit:
        return 0
    cut = 0
    for index, message in enumerate(messages):
        if estimate_tokens(messages) <= limit:
            break
        if message.get("role") != "tool":
            continue
        content = message.get("content") or ""
        if len(content) > CONTEXT_HARD_TRUNCATE_CHARS:
            body = structured_digest(
                content, head=CONTEXT_HARD_TRUNCATE_CHARS // 2, tail=CONTEXT_HARD_TRUNCATE_CHARS // 4
            )
            messages[index] = {**message, "content": body + TRUNC_MARK}
            cut += 1
    return cut


class ContextManager:
    def __init__(self, storage: Storage, gateway: ModelGateway):
        self.storage = storage
        self.gateway = gateway

    async def _summarize(self, provider: str, model: str, previous: str, transcript: str) -> str:
        reply = await self.gateway.complete_text(
            provider,
            model,
            [
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {
                    "role": "user",
                    "content": f"[Existing summary]\n{previous or '(none)'}\n\n[New conversation]\n{transcript}",
                },
            ],
            thinking="off",
        )
        return reply[:CONTEXT_SUMMARY_MAX_CHARS]

    @staticmethod
    def _render(rows: list[dict[str, Any]], per: int = 1200) -> str:
        lines = []
        for row in rows:
            content = (row.get("content") or "")[:per]
            if row.get("role") == "tool":
                lines.append(f"[tool {row.get('tool_name', '')}] {content}")
            elif row.get("role") == "assistant":
                lines.append(f"[assistant] {content}")
            else:
                lines.append(f"[user] {content}")
        return "\n".join(lines)

    async def _maybe_compact(self, session: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        if int(session.get("context_tokens") or 0) < CONTEXT_COMPACT_TOKENS:
            return
        upto = int(session.get("summary_upto") or 0)
        candidates = [row for row in rows if int(row["seq"]) > upto]
        if len(candidates) <= CONTEXT_KEEP_RECENT + 2:
            return
        old = candidates[:-CONTEXT_KEEP_RECENT]
        if not old:
            return
        session_id = session["id"]
        try:
            summary = await self._summarize(
                session.get("provider") or "mock",
                session.get("model") or "",
                session.get("summary") or "",
                self._render(old),
            )
            if not summary:
                return
            new_upto = int(old[-1]["seq"])
            await self.storage.update_session(session_id, summary=summary, summary_upto=new_upto)
            session["summary"] = summary
            session["summary_upto"] = new_upto
        except Exception:
            return

    async def load(self, session: dict[str, Any]) -> tuple[list[dict[str, Any]], str, int]:
        rows = await self.storage.list_messages(session["id"])
        await self._maybe_compact(session, rows)
        fresh = await self.storage.get_session(session["id"]) or session
        summary = fresh.get("summary") or ""
        upto = int(fresh.get("summary_upto") or 0)
        recent = [_row_to_message(row) for row in rows if int(row["seq"]) > upto]
        recent = sanitize(recent)
        age_tool_results(recent)
        enforce_hard_budget(recent)
        cursor = 0
        for row in rows:
            if int(row["seq"]) > upto and row["role"] == "user":
                cursor = int(row["seq"])
        return recent, summary, cursor

    async def midturn_compact(
        self,
        session: dict[str, Any],
        messages: list[dict[str, Any]],
        step: int,
    ) -> dict[str, Any]:
        result = {"aged": age_tool_results(messages), "compacted": 0, "tokens": 0}
        if not messages or messages[0].get("role") != "system":
            return result
        if step % MID_COMPACT_EVERY != 0:
            result["tokens"] = estimate_tokens(messages)
            return result
        if estimate_tokens(messages) < MID_COMPACT_TOKENS:
            result["tokens"] = estimate_tokens(messages)
            return result
        body = messages[1:]
        if len(body) <= MID_COMPACT_MIN_MSGS:
            result["tokens"] = estimate_tokens(messages)
            return result
        keep_tail = max(CONTEXT_KEEP_RECENT, MID_COMPACT_MIN_MSGS // 2)
        old, tail = body[:-keep_tail], body[-keep_tail:]
        if not old:
            return result
        try:
            rows = [
                {
                    "role": message.get("role"),
                    "content": message.get("content") or "",
                    "tool_name": message.get("tool_name", ""),
                }
                for message in old
            ]
            summary = await self._summarize(
                session.get("provider") or "mock",
                session.get("model") or "",
                "",
                self._render(rows),
            )
            if not summary:
                return result
        except Exception:
            return result
        note = "\n\n--- Progress summary (earlier steps compacted) ---\n" + summary
        messages[0] = {**messages[0], "content": (messages[0].get("content") or "") + note}
        del messages[1 : 1 + len(old)]
        messages[1:] = sanitize(messages[1:])
        result["compacted"] = len(old)
        result["tokens"] = estimate_tokens(messages)
        return result
