from __future__ import annotations

import asyncio
import os

import main
from core.pricing import estimate_cost


def test_estimate_cost_uses_cached_and_output_rates():
    cost = estimate_cost(
        "deepseek",
        "deepseek-flash",
        prompt_tokens=1_000_000,
        completion_tokens=100_000,
        cached_tokens=400_000,
    )
    # 600k uncached input @0.15 + 400k cached @0.003 + 100k output @0.60
    assert abs(cost - 0.1512) < 1e-9


def test_estimate_cost_unknown_model_is_zero():
    assert estimate_cost("mock", "mock", 1000, 1000) == 0.0


def test_estimate_cost_env_override():
    os.environ["HAOYUAN_PRICING"] = '{"custom/model": [1.0, 0.1, 2.0]}'
    try:
        cost = estimate_cost("custom", "model", 1_000_000, 1_000_000, 500_000)
        assert abs(cost - 2.55) < 1e-9
    finally:
        os.environ.pop("HAOYUAN_PRICING", None)


def test_record_usage_persists_cost(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": "priced usage"}).json()["data"]
    session_id = session["id"]

    async def seed():
        row = await main.harness.storage.add_message(session_id, "", "assistant", "priced")
        return await main.harness.storage.record_usage(
            session_id,
            row["id"],
            "deepseek",
            "deepseek-flash",
            {
                "prompt_tokens": 1_000_000,
                "completion_tokens": 100_000,
                "cached_tokens": 400_000,
                "reasoning_tokens": 10_000,
            },
        )

    bill = asyncio.run(seed())
    assert abs(bill["cost"] - 0.1512) < 1e-9
    assert abs(bill["session_total"]["cost"] - 0.1512) < 1e-9

    detail = client.get(f"/api/sessions/{session_id}").json()["data"]["session"]
    assert abs(detail["cost_est"] - 0.1512) < 1e-6
