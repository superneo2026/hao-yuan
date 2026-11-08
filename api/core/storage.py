from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'dev',
    title TEXT DEFAULT '',
    status TEXT DEFAULT 'idle',
    hidden INTEGER DEFAULT 0,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    thinking TEXT DEFAULT '',
    workspace TEXT DEFAULT '',
    template_id TEXT DEFAULT '',
    gate_mode TEXT DEFAULT '',
    gate_allow TEXT DEFAULT '',
    skills TEXT DEFAULT '',
    skills_used TEXT DEFAULT '',
    plan TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    summary_upto INTEGER DEFAULT 0,
    context_tokens INTEGER DEFAULT 0,
    total_prompt INTEGER DEFAULT 0,
    total_completion INTEGER DEFAULT 0,
    cost_est REAL DEFAULT 0,
    error TEXT DEFAULT '',
    lite_mode INTEGER DEFAULT 0,
    resume_count INTEGER DEFAULT 0,
    orch_id TEXT DEFAULT '',
    orch_role TEXT DEFAULT '',
    meta TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    input TEXT DEFAULT '',
    output TEXT DEFAULT '',
    error TEXT DEFAULT '',
    step_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, created_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT DEFAULT '',
    role TEXT NOT NULL,
    content TEXT DEFAULT '',
    reasoning TEXT DEFAULT '',
    tool_call_id TEXT DEFAULT '',
    tool_name TEXT DEFAULT '',
    tool_args TEXT DEFAULT '',
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cost_est REAL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    run_id TEXT DEFAULT '',
    type TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    run_id TEXT DEFAULT '',
    call_id TEXT DEFAULT '',
    tool TEXT NOT NULL,
    args TEXT DEFAULT '{}',
    preview TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    reason TEXT DEFAULT '',
    resolver TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id, status);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT DEFAULT 'file',
    name TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_daily (
    day TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    cost_est REAL DEFAULT 0,
    PRIMARY KEY (day, provider, model)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS plugins (
    name TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    config TEXT DEFAULT '{}',
    installed_at TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS tool_effects (
    effect_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    step INTEGER DEFAULT 0,
    tool TEXT DEFAULT '',
    result TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoints (
    session_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    run_id TEXT DEFAULT '',
    cursor INTEGER DEFAULT 0,
    plan TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (session_id, step)
);

CREATE TABLE IF NOT EXISTS orchestrations (
    id TEXT PRIMARY KEY,
    goal TEXT DEFAULT '',
    workspace TEXT DEFAULT '',
    status TEXT DEFAULT 'planning',
    contract TEXT DEFAULT '',
    metrics TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orchestration_tasks (
    id TEXT PRIMARY KEY,
    orch_id TEXT NOT NULL,
    seq INTEGER DEFAULT 0,
    role TEXT DEFAULT '',
    title TEXT DEFAULT '',
    instruction TEXT DEFAULT '',
    depends_on TEXT DEFAULT '[]',
    session_id TEXT DEFAULT '',
    worktree TEXT DEFAULT '',
    branch TEXT DEFAULT '',
    ports TEXT DEFAULT '[]',
    status TEXT DEFAULT 'pending',
    result TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orch_tasks ON orchestration_tasks(orch_id, seq);

CREATE TABLE IF NOT EXISTS supervisor_chats (
    id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    model TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS supervisor_messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT DEFAULT '',
    actions TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sup_messages ON supervisor_messages(chat_id, created_at);
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            await db.commit()

    @asynccontextmanager
    async def connect(self):
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=8000")
        try:
            yield db
        finally:
            await db.close()

    async def _fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with self.connect() as db:
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = await self._fetch(sql, params)
        return rows[0] if rows else None

    async def _write(self, sql: str, params: tuple = ()) -> int:
        async with self.connect() as db:
            cur = await db.execute(sql, params)
            last = cur.lastrowid or 0
            await cur.close()
            await db.commit()
        return last

    async def create_session(
        self,
        kind: str,
        title: str,
        provider: str,
        model: str,
        workspace: str = "",
        template_id: str = "",
        thinking: str = "",
        gate_mode: str = "",
        gate_allow: list | None = None,
        skills: list | None = None,
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sid = session_id or new_id("s")
        ts = now()
        await self._write(
            "INSERT INTO sessions(id, kind, title, status, provider, model, thinking, workspace, template_id,"
            " gate_mode, gate_allow, skills, meta, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                kind,
                title,
                "idle",
                provider,
                model,
                thinking,
                workspace,
                template_id,
                gate_mode,
                json.dumps(gate_allow or [], ensure_ascii=False) if gate_allow else "",
                json.dumps(skills or [], ensure_ascii=False) if skills else "",
                json.dumps(meta or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        return await self.get_session(sid)  # type: ignore[return-value]

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._one("SELECT * FROM sessions WHERE id=?", (session_id,))

    async def list_sessions(self, include_hidden: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM sessions"
        if not include_hidden:
            sql += " WHERE hidden=0"
        sql += " ORDER BY updated_at DESC"
        return await self._fetch(sql)

    async def update_session(self, session_id: str, **fields: Any) -> None:
        allowed = {
            "kind", "title", "status", "provider", "model", "thinking", "workspace",
            "template_id", "gate_mode", "gate_allow", "skills", "skills_used", "plan",
            "summary", "summary_upto", "context_tokens", "total_prompt", "total_completion",
            "cost_est", "error", "lite_mode", "resume_count", "orch_id", "orch_role",
            "hidden", "meta",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = now()
        assignments = ", ".join(f"{k}=?" for k in updates)
        await self._write(f"UPDATE sessions SET {assignments} WHERE id=?", (*updates.values(), session_id))

    async def delete_session(self, session_id: str) -> None:
        async with self.connect() as db:
            for table, column in (
                ("messages", "session_id"),
                ("events", "session_id"),
                ("approvals", "session_id"),
                ("artifacts", "session_id"),
                ("runs", "session_id"),
                ("tool_effects", "session_id"),
                ("checkpoints", "session_id"),
            ):
                await db.execute(f"DELETE FROM {table} WHERE {column}=?", (session_id,))
            await db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            await db.commit()

    async def create_run(self, session_id: str, provider: str, model: str, user_input: str) -> dict[str, Any]:
        rid = new_id("r")
        ts = now()
        await self._write(
            "INSERT INTO runs(id, session_id, status, provider, model, input, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (rid, session_id, "running", provider, model, user_input, ts, ts),
        )
        return (await self._one("SELECT * FROM runs WHERE id=?", (rid,))) or {}

    async def finish_run(
        self,
        run_id: str,
        status: str,
        output: str = "",
        error: str = "",
        step_count: int = 0,
    ) -> None:
        await self._write(
            "UPDATE runs SET status=?, output=?, error=?, step_count=?, updated_at=? WHERE id=?",
            (status, output, error, step_count, now(), run_id),
        )

    async def add_message(
        self,
        session_id: str,
        run_id: str,
        role: str,
        content: str = "",
        reasoning: str = "",
        tool_call_id: str = "",
        tool_name: str = "",
        tool_args: Any = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        mid = message_id or new_id("m")
        ts = now()
        if tool_args is not None and not isinstance(tool_args, str):
            tool_args = json.dumps(tool_args, ensure_ascii=False)
        await self._write(
            "INSERT INTO messages(id, session_id, run_id, role, content, reasoning, tool_call_id, tool_name,"
            " tool_args, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (mid, session_id, run_id, role, content, reasoning, tool_call_id, tool_name, tool_args or "", ts),
        )
        row = await self._one("SELECT rowid AS seq, * FROM messages WHERE id=?", (mid,))
        return row or {}

    async def update_message_usage(self, message_id: str, usage: dict[str, Any], cost: float) -> None:
        await self._write(
            "UPDATE messages SET prompt_tokens=?, completion_tokens=?, cached_tokens=?, reasoning_tokens=?, cost_est=?"
            " WHERE id=?",
            (
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
                int(usage.get("cached_tokens") or 0),
                int(usage.get("reasoning_tokens") or 0),
                cost,
                message_id,
            ),
        )

    async def list_messages(self, session_id: str, after_rowid: int = 0, limit: int = 5000) -> list[dict[str, Any]]:
        return await self._fetch(
            "SELECT rowid AS seq, * FROM messages WHERE session_id=? AND rowid>? ORDER BY rowid ASC LIMIT ?",
            (session_id, after_rowid, limit),
        )

    async def delete_messages(self, session_id: str) -> None:
        await self._write("DELETE FROM messages WHERE session_id=?", (session_id,))

    async def first_user_message(self, session_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT rowid AS seq, * FROM messages WHERE session_id=? AND role='user' ORDER BY rowid ASC LIMIT 1",
            (session_id,),
        )

    async def append_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> int:
        return await self._write(
            "INSERT INTO events(session_id, run_id, type, payload, created_at) VALUES (?,?,?,?,?)",
            (session_id, run_id, event_type, json.dumps(payload or {}, ensure_ascii=False), now()),
        )

    async def append_events_batch(self, items: list[dict[str, Any]]) -> None:
        if not items:
            return
        async with self.connect() as db:
            await db.executemany(
                "INSERT INTO events(session_id, run_id, type, payload, created_at) VALUES (?,?,?,?,?)",
                [
                    (
                        item["session_id"],
                        item.get("run_id", ""),
                        item["type"],
                        json.dumps(item.get("payload") or {}, ensure_ascii=False),
                        item.get("created_at") or now(),
                    )
                    for item in items
                ],
            )
            await db.commit()

    async def list_events(self, session_id: str, after_id: int = 0, limit: int = 2000) -> list[dict[str, Any]]:
        rows = await self._fetch(
            "SELECT * FROM events WHERE session_id=? AND id>? ORDER BY id ASC LIMIT ?",
            (session_id, after_id, limit),
        )
        for row in rows:
            try:
                row["payload"] = json.loads(row.get("payload") or "{}")
            except (ValueError, TypeError):
                row["payload"] = {}
        return rows

    async def last_event(self, session_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT * FROM events WHERE session_id=? ORDER BY id DESC LIMIT 1", (session_id,)
        )

    async def delete_events(self, session_id: str) -> None:
        await self._write("DELETE FROM events WHERE session_id=?", (session_id,))

    async def create_approval(
        self,
        session_id: str,
        run_id: str,
        call_id: str,
        tool: str,
        args: dict[str, Any],
        preview: str = "",
    ) -> dict[str, Any]:
        aid = new_id("ap")
        await self._write(
            "INSERT INTO approvals(id, session_id, run_id, call_id, tool, args, preview, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (aid, session_id, run_id, call_id, tool, json.dumps(args, ensure_ascii=False), preview, "pending", now()),
        )
        return (await self.get_approval(aid)) or {}

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        row = await self._one("SELECT * FROM approvals WHERE id=?", (approval_id,))
        if row:
            try:
                row["args"] = json.loads(row.get("args") or "{}")
            except (ValueError, TypeError):
                row["args"] = {}
        return row

    async def list_approvals(
        self, status: str | None = "pending", session_id: str | None = None
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if status:
            clauses.append("status=?")
            values.append(status)
        if session_id:
            clauses.append("session_id=?")
            values.append(session_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self._fetch(f"SELECT * FROM approvals {where} ORDER BY created_at DESC LIMIT 200", tuple(values))
        for row in rows:
            try:
                row["args"] = json.loads(row.get("args") or "{}")
            except (ValueError, TypeError):
                row["args"] = {}
        return rows

    async def resolve_approval(
        self, approval_id: str, approved: bool, reason: str = "", resolver: str = "local"
    ) -> dict[str, Any] | None:
        status = "approved" if approved else "rejected"
        await self._write(
            "UPDATE approvals SET status=?, reason=?, resolver=?, resolved_at=? WHERE id=? AND status='pending'",
            (status, reason, resolver, now(), approval_id),
        )
        return await self.get_approval(approval_id)

    async def create_artifact(
        self,
        session_id: str,
        path: str,
        kind: str = "file",
        name: str = "",
        size: int = 0,
    ) -> dict[str, Any]:
        aid = new_id("a")
        await self._write(
            "INSERT INTO artifacts(id, session_id, path, kind, name, size, created_at) VALUES (?,?,?,?,?,?,?)",
            (aid, session_id, path, kind, name or Path(path).name, size, now()),
        )
        return (await self._one("SELECT * FROM artifacts WHERE id=?", (aid,))) or {}

    async def list_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        return await self._fetch(
            "SELECT * FROM artifacts WHERE session_id=? ORDER BY created_at DESC", (session_id,)
        )

    async def record_usage(
        self,
        session_id: str,
        message_id: str,
        provider: str,
        model: str,
        usage: dict[str, Any],
        cost: float,
    ) -> dict[str, Any]:
        p = int(usage.get("prompt_tokens") or 0)
        c = int(usage.get("completion_tokens") or 0)
        cached = int(usage.get("cached_tokens") or 0)
        reasoning = int(usage.get("reasoning_tokens") or 0)
        await self.update_message_usage(message_id, usage, cost)
        day = now()[:10]
        await self._write(
            "INSERT INTO usage_daily(day, provider, model, prompt_tokens, completion_tokens, cached_tokens,"
            " reasoning_tokens, cost_est) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(day, provider, model) DO UPDATE SET"
            " prompt_tokens=prompt_tokens+excluded.prompt_tokens,"
            " completion_tokens=completion_tokens+excluded.completion_tokens,"
            " cached_tokens=cached_tokens+excluded.cached_tokens,"
            " reasoning_tokens=reasoning_tokens+excluded.reasoning_tokens,"
            " cost_est=cost_est+excluded.cost_est",
            (day, provider, model, p, c, cached, reasoning, cost),
        )
        await self._write(
            "UPDATE sessions SET context_tokens=?, total_prompt=total_prompt+?,"
            " total_completion=total_completion+?, cost_est=cost_est+?, updated_at=? WHERE id=?",
            (p + c, p, c, cost, now(), session_id),
        )
        row = await self._one(
            "SELECT context_tokens, total_prompt, total_completion, cost_est FROM sessions WHERE id=?",
            (session_id,),
        )
        return {
            "prompt": p,
            "completion": c,
            "cost_est": cost,
            "session_total": {
                "context_tokens": (row or {}).get("context_tokens", 0),
                "prompt": (row or {}).get("total_prompt", 0),
                "completion": (row or {}).get("total_completion", 0),
                "cost_est": (row or {}).get("cost_est", 0),
            },
        }

    async def usage_daily(self, days: int = 14) -> list[dict[str, Any]]:
        return await self._fetch(
            "SELECT * FROM usage_daily ORDER BY day DESC LIMIT ?", (days * 8,)
        )

    async def usage_today(self) -> dict[str, Any]:
        day = now()[:10]
        rows = await self._fetch("SELECT * FROM usage_daily WHERE day=?", (day,))
        return {
            "day": day,
            "prompt_tokens": sum(int(r.get("prompt_tokens") or 0) for r in rows),
            "completion_tokens": sum(int(r.get("completion_tokens") or 0) for r in rows),
            "cost_est": round(sum(float(r.get("cost_est") or 0) for r in rows), 6),
            "models": rows,
        }

    async def get_setting(self, key: str, default: str = "") -> str:
        row = await self._one("SELECT value FROM settings WHERE key=?", (key,))
        return (row or {}).get("value", default) if row else default

    async def set_setting(self, key: str, value: str) -> None:
        await self._write(
            "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    async def all_settings(self) -> dict[str, str]:
        rows = await self._fetch("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    async def plugin_states(self) -> dict[str, dict[str, Any]]:
        rows = await self._fetch("SELECT * FROM plugins")
        return {r["name"]: r for r in rows}

    async def set_plugin_state(self, name: str, enabled: bool, config: dict[str, Any] | None = None) -> None:
        await self._write(
            "INSERT INTO plugins(name, enabled, config, installed_at) VALUES (?,?,?,?)"
            " ON CONFLICT(name) DO UPDATE SET enabled=excluded.enabled, config=excluded.config",
            (name, 1 if enabled else 0, json.dumps(config or {}, ensure_ascii=False), now()),
        )

    async def delete_plugin_state(self, name: str) -> None:
        await self._write("DELETE FROM plugins WHERE name = ?", (name,))

    async def save_effect(self, key: str, session_id: str, step: int, tool: str, result: str) -> None:
        await self._write(
            "INSERT OR REPLACE INTO tool_effects(effect_key, session_id, step, tool, result, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (key, session_id, step, tool, result, now()),
        )

    async def get_effects(self, session_id: str) -> dict[str, str]:
        rows = await self._fetch("SELECT effect_key, result FROM tool_effects WHERE session_id=?", (session_id,))
        return {r["effect_key"]: r["result"] for r in rows}

    async def save_checkpoint(
        self, session_id: str, step: int, run_id: str, cursor: int, plan: str, note: str = ""
    ) -> None:
        await self._write(
            "INSERT OR REPLACE INTO checkpoints(session_id, step, run_id, cursor, plan, note, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (session_id, step, run_id, cursor, plan, note, now()),
        )
        # Keep only the newest checkpoint per session so long tasks do not accumulate rows.
        await self._write(
            "DELETE FROM checkpoints WHERE session_id=? AND step<>?", (session_id, step)
        )

    async def latest_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        return await self._one(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY step DESC LIMIT 1", (session_id,)
        )

    async def clear_checkpoints(self, session_id: str) -> None:
        await self._write("DELETE FROM checkpoints WHERE session_id=?", (session_id,))

    async def create_orchestration(self, goal: str, workspace: str, contract: str) -> dict[str, Any]:
        oid = new_id("o")
        ts = now()
        await self._write(
            "INSERT INTO orchestrations(id, goal, workspace, status, contract, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (oid, goal, workspace, "planning", contract, ts, ts),
        )
        return (await self._one("SELECT * FROM orchestrations WHERE id=?", (oid,))) or {}

    async def get_orchestration(self, oid: str) -> dict[str, Any] | None:
        return await self._one("SELECT * FROM orchestrations WHERE id=?", (oid,))

    async def list_orchestrations(self) -> list[dict[str, Any]]:
        return await self._fetch("SELECT * FROM orchestrations ORDER BY created_at DESC")

    async def update_orchestration(self, oid: str, **fields: Any) -> None:
        allowed = {"status", "contract", "metrics", "error"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = now()
        assignments = ", ".join(f"{k}=?" for k in updates)
        await self._write(f"UPDATE orchestrations SET {assignments} WHERE id=?", (*updates.values(), oid))

    async def add_orch_task(self, task: dict[str, Any]) -> None:
        await self._write(
            "INSERT INTO orchestration_tasks(id, orch_id, seq, role, title, instruction, depends_on, session_id,"
            " worktree, branch, ports, status, result, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task["id"], task["orch_id"], task.get("seq", 0), task.get("role", ""), task.get("title", ""),
                task.get("instruction", ""), json.dumps(task.get("depends_on") or [], ensure_ascii=False),
                task.get("session_id", ""), task.get("worktree", ""), task.get("branch", ""),
                json.dumps(task.get("ports") or [], ensure_ascii=False), task.get("status", "pending"),
                task.get("result", ""), now(), now(),
            ),
        )

    async def list_orch_tasks(self, oid: str) -> list[dict[str, Any]]:
        rows = await self._fetch(
            "SELECT * FROM orchestration_tasks WHERE orch_id=? ORDER BY seq ASC", (oid,)
        )
        for row in rows:
            for key in ("depends_on", "ports"):
                try:
                    row[key] = json.loads(row.get(key) or "[]")
                except (ValueError, TypeError):
                    row[key] = []
        return rows

    async def update_orch_task(self, task_id: str, **fields: Any) -> None:
        allowed = {"status", "result", "session_id", "worktree", "branch", "ports"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = now()
        assignments = ", ".join(f"{k}=?" for k in updates)
        await self._write(f"UPDATE orchestration_tasks SET {assignments} WHERE id=?", (*updates.values(), task_id))

    async def vacuum(self) -> None:
        async with self.connect() as db:
            for statement in ("PRAGMA wal_checkpoint(TRUNCATE)", "VACUUM", "PRAGMA wal_checkpoint(TRUNCATE)"):
                cur = await db.execute(statement)
                await cur.close()
            await db.commit()
