from __future__ import annotations

import asyncio

import pytest

from harness import supervisor


class FakeStorage:
    def __init__(self, session: dict, usage: dict | None = None):
        self.session = session
        self.usage = usage or {"cost_est": 0.0}
        self.updates: list[dict] = []

    async def get_session(self, session_id: str):
        return self.session if self.session.get("id") == session_id else None

    async def update_session(self, session_id: str, **fields):
        self.session.update(fields)
        self.updates.append(fields)

    async def usage_today(self):
        return self.usage


class FakeManager:
    def __init__(self):
        self.resumed: list[str] = []
        self.enqueued: list[str] = []
        self.active = False

    def mark_resume(self, session_id: str):
        self.resumed.append(session_id)

    def enqueue(self, session_id: str) -> bool:
        self.enqueued.append(session_id)
        self.active = True
        return True

    def is_active(self, session_id: str) -> bool:
        return self.active


class FakeEvents:
    def __init__(self):
        self.emitted: list[tuple] = []

    async def emit(self, session_id: str, event_type: str, payload):
        self.emitted.append((session_id, event_type, payload))


class FakeHarness:
    def __init__(self, session: dict, usage: dict | None = None):
        self.storage = FakeStorage(session, usage)
        self.manager = FakeManager()
        self.events = FakeEvents()


def _session(**overrides):
    data = {
        "id": "s_test",
        "status": "error",
        "error": "max steps reached",
    }
    data.update(overrides)
    return data


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    supervisor.reset_resume_state()
    monkeypatch.setattr(supervisor, "SUPERVISOR_AUTO_RESUME", True)
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_MAX", 1000)
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_BACKOFF_SEC", 60.0)
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_MAX_BACKOFF_SEC", 1800.0)
    monkeypatch.setattr(supervisor, "SUPERVISOR_DAILY_COST_CAP", 0.0)
    yield
    supervisor.reset_resume_state()


def test_resumable_error_whitelist():
    assert supervisor._resumable_error("max steps reached")
    assert supervisor._resumable_error("stale: no progress")
    assert not supervisor._resumable_error("服务重启导致任务中断")
    assert not supervisor._resumable_error("用户取消")
    assert not supervisor._resumable_error("")


def test_resume_delay_doubles_and_caps(monkeypatch):
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_BACKOFF_SEC", 60.0)
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_MAX_BACKOFF_SEC", 300.0)
    assert supervisor._resume_delay(1) == 60.0
    assert supervisor._resume_delay(2) == 120.0
    assert supervisor._resume_delay(3) == 240.0
    assert supervisor._resume_delay(10) == 300.0


def test_auto_resume_max_steps():
    harness = FakeHarness(_session())
    item = {"id": "s_test", "health": "error", "error": "max steps reached"}
    assert _run(supervisor._auto_resume(harness, item)) is True
    assert harness.manager.enqueued == ["s_test"]
    assert harness.storage.session["status"] == "idle"
    assert harness.storage.session["error"] == ""
    assert harness.events.emitted[-1][2]["health"] == "auto-resumed"


def test_auto_resume_respects_backoff():
    harness = FakeHarness(_session())
    item = {"id": "s_test", "health": "error", "error": "max steps reached"}
    assert _run(supervisor._auto_resume(harness, item)) is True
    assert _run(supervisor._auto_resume(harness, item)) is False
    assert harness.manager.enqueued == ["s_test"]


def test_auto_resume_skips_user_cancel():
    harness = FakeHarness(_session(error="用户取消"))
    item = {"id": "s_test", "health": "error", "error": "用户取消"}
    assert _run(supervisor._auto_resume(harness, item)) is False
    assert harness.manager.enqueued == []


def test_auto_resume_cost_cap(monkeypatch):
    harness = FakeHarness(_session(), usage={"cost_est": 5.0})
    monkeypatch.setattr(supervisor, "SUPERVISOR_DAILY_COST_CAP", 1.0)
    item = {"id": "s_test", "health": "error", "error": "max steps reached"}
    assert _run(supervisor._auto_resume(harness, item)) is False
    assert harness.manager.enqueued == []
    assert harness.events.emitted[-1][2]["health"] == "cost-capped"


def test_auto_resume_exhausted(monkeypatch):
    harness = FakeHarness(_session())
    monkeypatch.setattr(supervisor, "SUPERVISOR_RESUME_MAX", 1)
    item = {"id": "s_test", "health": "error", "error": "max steps reached"}
    assert _run(supervisor._auto_resume(harness, item)) is True
    supervisor._RESUME_STATE["s_test"]["next_at"] = 0.0
    assert _run(supervisor._auto_resume(harness, item)) is False
    assert harness.events.emitted[-1][2]["health"] == "resume-exhausted"
