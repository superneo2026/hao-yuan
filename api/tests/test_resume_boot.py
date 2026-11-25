from __future__ import annotations

import asyncio

import main
from core import session_manager as sm


def test_storage_maintenance_checkpoints_wal(client):
    result = asyncio.run(main.harness.storage.maintenance())
    assert result == {"vacuum": False}


def test_resume_interrupted_requires_checkpoint_and_closes_stale_run(client, monkeypatch):
    session = client.post("/api/sessions", json={"kind": "general", "title": "boot resume"}).json()["data"]
    session_id = session["id"]

    async def seed():
        await main.harness.storage._write(
            "UPDATE sessions SET status='running' WHERE id=?", (session_id,)
        )
        run = await main.harness.storage.create_run(session_id, "mock", "mock", "resume me")
        await main.harness.storage.save_checkpoint(
            session_id, 3, run["id"], 12, "", "step 3 completed"
        )
        return run["id"]

    run_id = asyncio.run(seed())
    monkeypatch.setattr(sm, "AUTO_RESUME_ON_BOOT", True)
    enqueued: list[str] = []
    monkeypatch.setattr(
        main.harness.manager, "enqueue", lambda sid: enqueued.append(sid) or True
    )

    asyncio.run(main.harness.manager.resume_interrupted())

    detail = client.get(f"/api/sessions/{session_id}").json()["data"]["session"]
    assert detail["status"] == "idle"
    assert detail["error"] == ""
    assert detail["resume_count"] == 1
    assert session_id in enqueued

    row = asyncio.run(main.harness.storage._one("SELECT * FROM runs WHERE id=?", (run_id,)))
    assert row["status"] == "error"
    assert "restart" in (row["error"] or "")
