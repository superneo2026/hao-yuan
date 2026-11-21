from __future__ import annotations

import asyncio

from core.instructions import addition_message, classify_instruction, interrupt_message
from core.session_manager import SessionManager


def test_explicit_interrupts_are_detected():
    for text in (
        "停止当前任务",
        "先停一下",
        "取消",
        "别做了",
        "不要继续了",
        "stop",
        "please stop",
        "cancel the current task",
        "stop working",
        "换一个任务",
        "推倒重来",
    ):
        verdict = classify_instruction(text)
        assert verdict.kind == "interrupt", text


def test_additions_do_not_interrupt():
    for text in (
        "顺便把测试也跑一下",
        "先把首页按钮改成蓝色",
        "不要修改 README",
        "取消测试里的超时",
        "stop the server after build",
        "另外补充一个边界条件",
        "不要中断当前任务，先修登录",
        "do not interrupt the current task, fix login first",
    ):
        verdict = classify_instruction(text)
        assert verdict.kind == "addition", text


def test_priority_and_chatter():
    assert classify_instruction("紧急：先修复登录崩溃").priority == "urgent"
    assert classify_instruction("另外把页脚文案也改一下").priority == "high"
    assert classify_instruction("谢谢").kind == "chatter"


def test_midrun_wrappers_keep_original_task_alive():
    addition = addition_message("把按钮改成蓝色", "urgent")
    assert "mid-task addition" in addition
    assert "priority: urgent" in addition
    assert "do not discard" in addition
    assert "把按钮改成蓝色" in addition

    interrupted = interrupt_message("停止")
    assert "explicitly interrupted" in interrupted
    assert "停止" in interrupted


class _FakeStorage:
    async def update_session(self, session_id, **fields):
        return None

    async def get_approval(self, approval_id):
        return None


class _FakeRuntime:
    def __init__(self):
        self.runs = 0
        self.started = asyncio.Event()

    async def emit(self, *args, **kwargs):
        return None

    async def run_session(self, session_id):
        self.runs += 1
        self.started.set()
        await asyncio.sleep(10)


class _InjectStorage:
    def __init__(self, rows):
        self.rows = rows

    async def list_messages(self, session_id, after_rowid=0):
        return [row for row in self.rows if row["seq"] > after_rowid]


def test_inject_pending_wraps_additions_and_skips_chatter():
    from core.runtime import AgentRuntime

    runtime = object.__new__(AgentRuntime)
    runtime.storage = _InjectStorage(
        [
            {"seq": 1, "role": "user", "content": "顺便把测试也跑一下"},
            {"seq": 2, "role": "user", "content": "谢谢"},
        ]
    )
    messages = []
    cursor, merged = asyncio.run(runtime._inject_pending("s_test", messages, 0))
    assert cursor == 2
    assert len(merged) == 1
    assert merged[0]["kind"] == "addition"
    assert "mid-task addition" in messages[0]["content"]
    assert "顺便把测试也跑一下" in messages[0]["content"]


class _MessageStorage:
    def __init__(self):
        self.plan_updates = []

    async def add_message(self, session_id, run_id, role, content):
        return {"id": "m_test", "role": role, "content": content}

    async def update_session(self, session_id, **fields):
        if "plan" in fields:
            self.plan_updates.append(fields["plan"])

    async def first_user_message(self, session_id):
        return {"id": "m_test"}


class _MessageManager:
    def __init__(self):
        self.interrupted = []
        self.enqueued = []

    async def get_session(self, session_id):
        return {"id": session_id, "status": "running", "title": "existing task", "plan": "{}"}

    def is_active(self, session_id):
        return True

    async def interrupt(self, session_id):
        self.interrupted.append(session_id)
        return True

    def enqueue(self, session_id):
        self.enqueued.append(session_id)
        return True


class _MessageEvents:
    def __init__(self):
        self.emitted = []

    async def emit(self, session_id, event_type, payload):
        self.emitted.append((event_type, payload))


class _MessageHarness:
    def __init__(self):
        self.storage = _MessageStorage()
        self.manager = _MessageManager()
        self.events = _MessageEvents()


def test_send_message_routes_midrun_interrupt(monkeypatch):
    from extensions import sessions as sessions_ext

    harness = _MessageHarness()

    async def fake_harness():
        return harness

    monkeypatch.setattr(sessions_ext, "get_harness", fake_harness)
    result = asyncio.run(
        sessions_ext.send_message(
            "s_test",
            sessions_ext.MessageSend(content="停止当前任务，改为先修复登录"),
        )
    )
    assert result["data"]["kind"] == "interrupt"
    assert result["data"]["interrupted"] is True
    assert harness.manager.interrupted == ["s_test"]
    assert harness.manager.enqueued == []
    types = [event[0] for event in harness.events.emitted]
    assert "instruction.queued" in types
    assert "plan.updated" in types


def test_send_message_keeps_midrun_addition_parallel(monkeypatch):
    from extensions import sessions as sessions_ext

    harness = _MessageHarness()

    async def fake_harness():
        return harness

    monkeypatch.setattr(sessions_ext, "get_harness", fake_harness)
    result = asyncio.run(
        sessions_ext.send_message(
            "s_test",
            sessions_ext.MessageSend(content="顺便把测试也跑一下"),
        )
    )
    assert result["data"]["kind"] == "addition"
    assert result["data"]["priority"] == "high"
    assert "interrupted" not in result["data"]
    assert harness.manager.interrupted == []
    queued = [payload for event_type, payload in harness.events.emitted if event_type == "instruction.queued"]
    assert queued and queued[0]["interrupted"] is False


def test_interrupt_cancels_and_requeues_new_requirement():
    async def scenario():
        runtime = _FakeRuntime()
        manager = SessionManager(_FakeStorage(), runtime)
        assert manager.enqueue("s_test") is True
        await asyncio.wait_for(runtime.started.wait(), timeout=2)
        assert await manager.interrupt("s_test") is True
        for _ in range(40):
            if runtime.runs >= 2:
                break
            await asyncio.sleep(0.02)
        assert runtime.runs >= 2
        assert manager.consume_interrupt("s_test") is True
        assert manager.consume_interrupt("s_test") is False
        await manager.cancel("s_test")
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
