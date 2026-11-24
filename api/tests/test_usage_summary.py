from __future__ import annotations

import asyncio
from datetime import datetime

import main


def test_old_session_reports_zero_cache_and_reasoning(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": "usage zero"}).json()["data"]
    detail = client.get(f"/api/sessions/{session['id']}").json()["data"]["session"]
    assert detail["cached_tokens"] == 0
    assert detail["reasoning_tokens"] == 0


def test_usage_rollup_exposes_cached_and_reasoning(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": "usage seeded"}).json()["data"]
    session_id = session["id"]

    async def seed():
        row = await main.harness.storage.add_message(session_id, "", "assistant", "seeded reply")
        return await main.harness.storage.record_usage(
            session_id,
            row["id"],
            "mock",
            "mock",
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cached_tokens": 60,
                "reasoning_tokens": 7,
            },
        )

    bill = asyncio.run(seed())
    assert bill["cached_tokens"] == 60
    assert bill["reasoning_tokens"] == 7
    assert bill["session_total"]["cached_tokens"] == 60
    assert bill["session_total"]["reasoning_tokens"] == 7

    detail = client.get(f"/api/sessions/{session_id}").json()["data"]["session"]
    assert detail["cached_tokens"] == 60
    assert detail["reasoning_tokens"] == 7

    listing = client.get("/api/sessions").json()["data"]
    item = next(row for row in listing if row["id"] == session_id)
    assert item["cached_tokens"] == 60
    assert item["reasoning_tokens"] == 7

    today = client.get("/api/usage/today").json()["data"]
    assert today["cached_tokens"] >= 60
    assert today["reasoning_tokens"] >= 7

    daily = client.get("/api/usage/daily").json()["data"]
    today_key = datetime.now().strftime("%Y-%m-%d")
    row = next((entry for entry in daily if entry["day"] == today_key), None)
    assert row is not None
    assert row["cached_tokens"] >= 60
    assert row["reasoning_tokens"] >= 7
