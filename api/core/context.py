from __future__ import annotations

import json
import re
from typing import Any

from configs import models as models_mod
from configs.configs import (
    COMPACT_HYSTERESIS_RATIO,
    COMPACT_HYSTERESIS_STEPS,
    CONTEXT_COMPACT_RATIO,
    CONTEXT_COMPACT_TOKENS,
    CONTEXT_HARD_LIMIT,
    CONTEXT_HARD_RATIO,
    CONTEXT_HARD_TRUNCATE_CHARS,
    CONTEXT_KEEP_RECENT,
    CONTEXT_SUMMARY_MAX_CHARS,
    DEFAULT_CONTEXT_WINDOW,
    DIGEST_HEAD_CHARS,
    DIGEST_TAIL_CHARS,
    MID_COMPACT_EVERY,
    MID_COMPACT_MIN_MSGS,
    MID_COMPACT_TOKENS,
    STRUCTURED_DIGEST_ENABLED,
    TOKEN_ESTIMATE_FACTOR,
    TOOL_AGING_CHARS,
    TOOL_AGING_KEEP,
)
from core.gateway import ModelGateway
from core.storage import Storage

AGED_MARK = "\n...[aged: full result remains in session history; re-read the target if needed]"
TRUNC_MARK = "\n...[truncated by hard context budget; use a precise tool call to fetch details]"
MID_SUMMARY_MARK = "--- Progress summary (earlier steps compacted) ---"
LEDGER_MARK = "--- Delivery ledger (harness-managed, authoritative; do not re-verify by re-reading) ---"
# Mid-turn compaction fires somewhat before the turn-level threshold so a single
# long tool loop never reaches the turn-level compaction point unannounced.
MID_COMPACT_RATIO = 0.85

_DIGEST_KEEP_RE = re.compile(
    r'File\s+"[^"]+",\s+line\s+\d+|'
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


def context_budget(window: int | None = None) -> dict[str, int]:
    """Compaction thresholds for a model context window (in real provider tokens).

    Thresholds scale with the window; the fixed CONTEXT_* constants act as floors
    so small-window models keep their old behaviour. A 128k window compacts at ~70k
    and hard-truncates at ~102k instead of 20k/48k.
    """
    window = int(window or DEFAULT_CONTEXT_WINDOW)
    compact_at = max(CONTEXT_COMPACT_TOKENS, int(window * CONTEXT_COMPACT_RATIO))
    hard_at = max(CONTEXT_HARD_LIMIT, int(window * CONTEXT_HARD_RATIO))
    return {"window": window, "compact_at": compact_at, "hard_at": hard_at}


def session_window(session: dict[str, Any] | None) -> int:
    try:
        provider = (session or {}).get("provider") or ""
        conf = models_mod.PROVIDERS.get(provider) if provider else None
        return models_mod.effective_context_window(conf, (session or {}).get("model") or "")
    except Exception:
        return DEFAULT_CONTEXT_WINDOW


def mid_compact_trigger(budget: dict[str, int] | None = None) -> int:
    budget = budget or context_budget()
    return max(MID_COMPACT_TOKENS, int(budget["compact_at"] * MID_COMPACT_RATIO))


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


def enforce_hard_budget(messages: list[dict[str, Any]], limit: int | None = None, window: int | None = None) -> int:
    """Shrink tool results until the *estimated* size fits the hard budget.

    ``limit`` is in estimated tokens; when omitted it is the model's hard budget
    divided by TOKEN_ESTIMATE_FACTOR (estimates under-count CJK text).
    """
    if limit is None:
        limit = int(context_budget(window)["hard_at"] / max(1.0, TOKEN_ESTIMATE_FACTOR))
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
        # session_id -> (step, body_tokens) of the last mid-turn compaction.
        self._last_compact: dict[str, tuple[int, int]] = {}

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
        budget = context_budget(session_window(session))
        if int(session.get("context_tokens") or 0) < budget["compact_at"]:
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
        window = session_window(fresh)
        if estimate_tokens(recent) * TOKEN_ESTIMATE_FACTOR > context_budget(window)["compact_at"]:
            age_tool_results(recent)
        enforce_hard_budget(recent, window=window)
        cursor = 0
        for row in rows:
            if int(row["seq"]) > upto and row["role"] == "user":
                cursor = int(row["seq"])
        return recent, summary, cursor

    def body_tokens(self, messages: list[dict[str, Any]], last_prompt_tokens: int = 0) -> int:
        """Real-token estimate of the conversation body (everything but the system prompt).

        The provider's prompt_tokens from the previous call is the most accurate
        signal; the heuristic estimate is only used for what was appended since.
        """
        system_est = estimate_tokens(messages[:1])
        body_est = estimate_tokens(messages[1:])
        from_estimate = int(body_est * TOKEN_ESTIMATE_FACTOR)
        from_provider = int(last_prompt_tokens) - int(system_est * TOKEN_ESTIMATE_FACTOR)
        return max(from_estimate, from_provider, 0)

    async def midturn_compact(
        self,
        session: dict[str, Any],
        messages: list[dict[str, Any]],
        step: int,
        last_prompt_tokens: int = 0,
        ledger_text: str = "",
    ) -> dict[str, Any]:
        budget = context_budget(session_window(session))
        trigger = mid_compact_trigger(budget)
        body_tokens = self.body_tokens(messages, last_prompt_tokens)
        result = {"aged": 0, "compacted": 0, "tokens": body_tokens, "trigger": trigger, "window": budget["window"]}
        if not messages or messages[0].get("role") != "system":
            return result
        # Tool-result aging only kicks in once the body is comfortably large; with
        # a small fixed budget it used to shrink every read older than 6 steps,
        # which threw away the reference material the agent was still using.
        if body_tokens >= int(trigger * 0.6):
            result["aged"] = age_tool_results(messages)
        if step % MID_COMPACT_EVERY != 0:
            return result
        if body_tokens < trigger:
            return result
        body = messages[1:]
        if len(body) <= MID_COMPACT_MIN_MSGS:
            return result
        key = str(session.get("id") or "default")
        last_step, _last_tokens = self._last_compact.get(key, (-(10**9), 0))
        if step - last_step < COMPACT_HYSTERESIS_STEPS and body_tokens < int(trigger * COMPACT_HYSTERESIS_RATIO):
            return result
        keep_tail = max(CONTEXT_KEEP_RECENT, MID_COMPACT_MIN_MSGS // 2)
        old, tail = body[:-keep_tail], body[-keep_tail:]
        if not old:
            return result
        # Merge with the previous rolling summary and REPLACE it in the system
        # prompt. The old code appended a new block on every compaction, so the
        # system prompt grew without bound (~110k tokens after 130 compactions)
        # and the model slowly forgot what it had already done.
        system_content = messages[0].get("content") or ""
        previous = ""
        if MID_SUMMARY_MARK in system_content:
            base_content, _, previous = system_content.partition(MID_SUMMARY_MARK)
            previous = previous.split(LEDGER_MARK)[0].strip()
        else:
            base_content = system_content
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
                previous,
                self._render(rows),
            )
            if not summary:
                return result
        except Exception:
            return result
        note = "\n\n" + MID_SUMMARY_MARK + "\n" + summary
        if ledger_text.strip():
            # The LLM summary is prose and loses precise state; the harness ledger
            # (deliverable paths, sections written, remaining work) is appended
            # verbatim so the agent resumes without re-reading its own output.
            note += "\n\n" + LEDGER_MARK + "\n" + ledger_text.strip()
        messages[0] = {**messages[0], "content": base_content.rstrip() + note}
        del messages[1 : 1 + len(old)]
        messages[1:] = sanitize(messages[1:])
        self._last_compact[key] = (step, body_tokens)
        result["compacted"] = len(old)
        result["tokens"] = self.body_tokens(messages)
        return result
