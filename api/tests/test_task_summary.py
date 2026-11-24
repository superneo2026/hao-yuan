from __future__ import annotations

import asyncio
import os
import time

from core.harness import harness_instance
from core.runtime import task_summary_text


def test_task_summary_text_reports_produced_and_missing(tmp_path):
    out = tmp_path / "plan"
    out.mkdir()
    page = out / "index.html"
    page.write_text(
        "<!DOCTYPE html><html><body><section id='s1'>" + "内容 " * 1500 + "</section></body></html>",
        encoding="utf-8",
    )
    missing = tmp_path / "missing.html"
    state = {
        "output_targets": [str(out), str(missing)],
        "delivery_since": 0.0,
        "total_steps": 65,
        "started_at": time.time() - 718,
        "written_paths": [str(page)],
    }
    text = task_summary_text(
        {"first_question": "做一份 v3 方案", "elapsed_s": 718},
        state,
        "error",
        "no progress: deliverable not created",
    )
    assert "任务收尾总结" in text
    assert "index.html" in text
    assert "missing.html" in text
    assert "no progress" in text
    assert "下一步" in text


def test_task_summary_text_marks_stale_file_as_missing(tmp_path):
    target = tmp_path / "old.html"
    target.write_text("<html></html>", encoding="utf-8")
    os.utime(target, (0, 0))
    state = {
        "output_targets": [str(target)],
        "delivery_since": time.time(),
        "total_steps": 3,
        "started_at": time.time(),
    }
    text = task_summary_text({"first_question": "x"}, state, "error", "boom")
    assert "未完成" in text
    assert "不是本轮生成" in text


def test_ensure_task_summary_persists_on_error(client):
    harness = harness_instance()
    session = asyncio.run(
        harness.manager.create_session(
            kind="plan",
            title="closure summary",
            provider="mock",
            model="mock-deterministic",
            workspace="",
        )
    )

    async def go():
        await harness.runtime._ensure_task_summary(
            session["id"],
            "r_test_closure",
            session,
            {"output_targets": [], "total_steps": 2},
            status="error",
            error="boom",
        )
        return await harness.storage.list_messages_tail(session["id"], limit=5)

    rows = asyncio.run(go())
    assert rows
    assert rows[-1]["role"] == "assistant"
    assert "任务收尾总结" in rows[-1]["content"]
    assert "boom" in rows[-1]["content"]


def test_ensure_task_summary_skips_done_with_final_text(client):
    harness = harness_instance()
    session = asyncio.run(
        harness.manager.create_session(
            kind="plan",
            title="closure skip",
            provider="mock",
            model="mock-deterministic",
            workspace="",
        )
    )

    async def go():
        await harness.runtime._ensure_task_summary(
            session["id"],
            "r_test_skip",
            session,
            {"output_targets": [], "total_steps": 2, "final_text": "已经完成并验证。"},
            status="done",
            error="",
        )
        return await harness.storage.list_messages_tail(session["id"], limit=5)

    rows = asyncio.run(go())
    assert not any("任务收尾总结" in (row.get("content") or "") for row in rows)
