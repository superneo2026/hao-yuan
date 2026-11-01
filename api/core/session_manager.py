from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from configs.configs import (
    AUTO_RESUME_ON_BOOT,
    GATE_CONFIRM_TIMEOUT,
    MAX_AUTO_ROLLOVER,
    MAX_CONCURRENT_SESSIONS,
)
from configs.models import auto_default, resolve
from core.contracts import ToolCall
from core.storage import Storage, now


class SessionManager:
    def __init__(self, storage: Storage, runtime):
        self.storage = storage
        self.runtime = runtime
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)
        self.tasks: dict[str, asyncio.Task] = {}
        self.approvals: dict[str, asyncio.Future] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.resume_pending: set[str] = set()

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
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider, model = resolve(provider, model)
        return await self.storage.create_session(
            kind=kind,
            title=title,
            provider=provider,
            model=model,
            workspace=workspace,
            template_id=template_id,
            thinking=thinking,
            gate_mode=gate_mode,
            gate_allow=gate_allow,
            skills=skills,
            meta=meta,
        )

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        return await self.storage.get_session(session_id)

    async def list_sessions(self, include_hidden: bool = True) -> list[dict[str, Any]]:
        return await self.storage.list_sessions(include_hidden=include_hidden)

    def is_active(self, session_id: str) -> bool:
        task = self.tasks.get(session_id)
        return bool(task and not task.done())

    async def set_status(self, session_id: str, status: str, error: str = "") -> None:
        await self.storage.update_session(session_id, status=status, error=error)
        await self.runtime.emit(session_id, "session.status", {"status": status, "error": error})

    def enqueue(self, session_id: str) -> bool:
        if self.is_active(session_id):
            return False
        task = asyncio.create_task(self._run_wrapped(session_id))
        self.tasks[session_id] = task
        return True

    async def _run_wrapped(self, session_id: str) -> None:
        try:
            await self.set_status(session_id, "queued")
            async with self.semaphore:
                await self.runtime.run_session(session_id)
        except asyncio.CancelledError:
            await self.set_status(session_id, "error", "用户取消")
        except Exception as exc:
            await self.set_status(session_id, "error", str(exc)[:500])
        finally:
            self.tasks.pop(session_id, None)

    async def cancel(self, session_id: str) -> bool:
        task = self.tasks.get(session_id)
        if not task or task.done():
            return False
        task.cancel()
        for approval_id, future in list(self.approvals.items()):
            approval = await self.storage.get_approval(approval_id)
            if approval and approval["session_id"] == session_id:
                await self.storage.resolve_approval(approval_id, False, "task cancelled", "system")
                if not future.done():
                    future.set_result(False)
        return True

    async def archive(self, session_id: str) -> None:
        await self.storage.update_session(session_id, hidden=1)
        await self.runtime.emit(session_id, "session.hidden", {"hidden": True})

    async def unhide(self, session_id: str) -> None:
        await self.storage.update_session(session_id, hidden=0)
        await self.runtime.emit(session_id, "session.hidden", {"hidden": False})

    async def purge(self, session_id: str) -> None:
        await self.cancel(session_id)
        self.pending.pop(session_id, None)
        import shutil

        from configs.configs import ARTIFACTS_DIR

        shutil.rmtree(ARTIFACTS_DIR / session_id, ignore_errors=True)
        await self.storage.delete_session(session_id)

    def mark_resume(self, session_id: str) -> None:
        self.resume_pending.add(session_id)

    def consume_resume(self, session_id: str) -> bool:
        if session_id in self.resume_pending:
            self.resume_pending.discard(session_id)
            return True
        return False

    def get_pending(self, session_id: str) -> dict[str, Any] | None:
        return self.pending.get(session_id)

    def clear_pending(self, session_id: str) -> None:
        self.pending.pop(session_id, None)

    async def resume_interrupted(self) -> None:
        rows = await self.storage._fetch(
            "SELECT * FROM sessions WHERE status IN ('queued','running','waiting_input')"
        )
        for row in rows:
            session_id = row["id"]
            if row["status"] == "queued":
                self.enqueue(session_id)
                continue
            checkpoint = await self.storage.latest_checkpoint(session_id)
            used = int(row.get("resume_count") or 0)
            if AUTO_RESUME_ON_BOOT and checkpoint and used < MAX_AUTO_ROLLOVER:
                self.mark_resume(session_id)
                await self.storage.update_session(
                    session_id,
                    status="idle",
                    error="",
                    resume_count=used + 1,
                )
                await self.runtime.emit(
                    session_id,
                    "session.resume",
                    {"auto": True, "from_step": checkpoint["step"]},
                )
                self.enqueue(session_id)
            else:
                await self.set_status(
                    session_id,
                    "error",
                    "服务重启导致任务中断，点击「继续」可基于历史断点续跑",
                )

    async def _slot_release(self) -> None:
        self.semaphore.release()

    async def _slot_acquire(self) -> None:
        future = asyncio.ensure_future(self.semaphore.acquire())
        try:
            await asyncio.shield(future)
        except asyncio.CancelledError:
            raise

    async def ask_approval(
        self,
        session: dict[str, Any],
        call: ToolCall,
        run_id: str,
        preview: str,
    ) -> tuple[bool, str]:
        session_id = session["id"]
        approval = await self.storage.create_approval(
            session_id=session_id,
            run_id=run_id,
            call_id=call.call_id,
            tool=call.name,
            args=call.arguments,
            preview=preview,
        )
        approval_id = approval["id"]
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.approvals[approval_id] = future
        self.pending[session_id] = {
            "approval_id": approval_id,
            "call_id": call.call_id,
            "tool": call.name,
            "args": call.arguments,
            "preview": preview,
            "created_at": now(),
        }
        await self.storage.update_session(session_id, status="waiting_input")
        await self.runtime.emit(session_id, "session.status", {"status": "waiting_input"}, run_id)
        await self.runtime.emit(
            session_id,
            "approval.required",
            {
                "approval_id": approval_id,
                "call_id": call.call_id,
                "tool": call.name,
                "args": call.arguments,
                "preview": preview,
                "timeout_s": GATE_CONFIRM_TIMEOUT,
            },
            run_id,
        )
        await self._slot_release()
        try:
            try:
                approved = await asyncio.wait_for(future, timeout=GATE_CONFIRM_TIMEOUT)
                reason = "user approved" if approved else "user rejected"
            except asyncio.TimeoutError:
                approved = False
                reason = "approval timed out"
                await self.storage.resolve_approval(approval_id, False, reason, "timeout")
            except asyncio.CancelledError:
                await self.storage.resolve_approval(approval_id, False, "task cancelled", "system")
                raise
        finally:
            self.pending.pop(session_id, None)
            self.approvals.pop(approval_id, None)
            await self._slot_acquire()
        await self.storage.update_session(session_id, status="running")
        await self.runtime.emit(session_id, "session.status", {"status": "running"}, run_id)
        await self.runtime.emit(
            session_id,
            "approval.resolved",
            {"approval_id": approval_id, "approved": approved, "reason": reason},
            run_id,
        )
        return approved, reason

    async def ask_question(self, session: dict[str, Any], call: ToolCall, run_id: str = "") -> str:
        question = str(call.arguments.get("question") or "").strip()
        approved, _reason = await self.ask_approval(session, call, run_id, question)
        if isinstance(approved, str) and approved.strip():
            return approved.strip()
        if approved:
            return "用户已确认，可以继续。"
        return "用户未回答或已取消，请停止当前分支并向用户说明。"

    async def resolve_approval(self, approval_id: str, approved: bool, reason: str = "", resolver: str = "local") -> dict[str, Any] | None:
        approval = await self.storage.get_approval(approval_id)
        if not approval:
            return None
        if approval["status"] != "pending":
            return approval
        resolved = await self.storage.resolve_approval(approval_id, approved, reason, resolver)
        future = self.approvals.get(approval_id)
        if future and not future.done():
            if str(approval.get("tool") or "") == "ask_user":
                answer = (reason or "").strip() or ("是" if approved else "否")
                future.set_result(answer)
            else:
                future.set_result(bool(approved))
        return resolved

    async def resolve_by_call(self, session_id: str, call_id: str, approved: bool, reason: str = "") -> bool:
        approvals = await self.storage.list_approvals(status="pending", session_id=session_id)
        for approval in approvals:
            if approval["call_id"] == call_id:
                await self.resolve_approval(approval["id"], approved, reason)
                return True
        return False
