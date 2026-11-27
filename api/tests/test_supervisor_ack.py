from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.storage import Storage, now
from harness import supervisor


class FakeEvents:
    def __init__(self, storage):
        self.storage = storage

    async def emit(self, session_id, event_type, payload=None, run_id=""):
        # Mimic the real bus writing an event, which changes last_event.
        await self.storage._write(
            "INSERT INTO events(session_id, run_id, type, payload, created_at) VALUES (?,?,?,?,?)",
            (session_id, run_id, event_type, json.dumps(payload or {}), now()),
        )


class FakeHarness:
    def __init__(self, storage):
        self.storage = storage
        self.events = FakeEvents(storage)


def _run(coro):
    return asyncio.run(coro)


def test_ack_hides_alert_and_reappears_after_change(tmp_path):
    async def scenario():
        storage = Storage(Path(tmp_path) / "ack.db")
        await storage.init()
        session = await storage.create_session(kind="dev", title="T", provider="mock", model="m")
        await storage.update_session(session["id"], status="error", error="boom")
        harness = FakeHarness(storage)

        snap = await supervisor.snapshot(storage)
        assert any(item["id"] == session["id"] for item in snap["alerts"])
        assert snap["summary"]["alerts"] >= 1

        result = await supervisor.act(harness, session["id"], "ack")
        assert result["ok"] is True

        snap2 = await supervisor.snapshot(storage)
        assert all(item["id"] != session["id"] for item in snap2["alerts"])
        item = next(item for item in snap2["items"] if item["id"] == session["id"])
        assert item["acknowledged"] is True

        # A new failure changes the alert signature, so it should surface again.
        await storage.update_session(session["id"], status="error", error="a new failure")
        snap3 = await supervisor.snapshot(storage)
        assert any(item["id"] == session["id"] for item in snap3["alerts"])

    _run(scenario())
