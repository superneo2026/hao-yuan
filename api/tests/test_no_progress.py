from __future__ import annotations

import json
import time

from core import context as ctx
from core.context import ContextManager, MID_SUMMARY_MARK
from core.runtime import AgentRuntime, missing_deliverables


class _FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_text(self, provider, model, messages, thinking="off"):
        self.calls += 1
        return f"summary-{self.calls}"


def _big_tool_messages(count: int) -> list[dict]:
    return [{"role": "tool", "content": "x" * 2000} for _ in range(count)]


def test_midturn_compact_replaces_instead_of_appending(monkeypatch):
    monkeypatch.setattr(ctx, "MID_COMPACT_TOKENS", 10)
    monkeypatch.setattr(ctx, "MID_COMPACT_MIN_MSGS", 4)
    monkeypatch.setattr(ctx, "CONTEXT_KEEP_RECENT", 2)
    monkeypatch.setattr(ctx, "MID_COMPACT_EVERY", 1)
    # Pin a small budget so the ten 2k-char tool messages trigger compaction
    # regardless of the model window this test machine resolves to.
    monkeypatch.setattr(ctx, "context_budget", lambda window=None: {"window": 1000, "compact_at": 300, "hard_at": 800})

    manager = ContextManager(None, _FakeGateway())
    session = {"provider": "mock", "model": "mock"}
    messages = [{"role": "system", "content": "BASE RULES"}] + _big_tool_messages(10)

    result = asyncio_run(manager.midturn_compact(session, messages, 1))
    assert result["compacted"] > 0
    system = messages[0]["content"]
    assert system.startswith("BASE RULES")
    assert system.count(MID_SUMMARY_MARK) == 1

    # Second compaction must replace the rolling summary, not grow the prompt.
    messages.extend(_big_tool_messages(10))
    before = len(messages[0]["content"])
    result = asyncio_run(manager.midturn_compact(session, messages, 2))
    assert result["compacted"] > 0
    system = messages[0]["content"]
    assert system.count(MID_SUMMARY_MARK) == 1
    assert system.startswith("BASE RULES")
    # The appended block is bounded by the summary, so growth is small.
    assert len(system) <= before + 200


def test_midturn_compact_injects_delivery_ledger(monkeypatch):
    monkeypatch.setattr(ctx, "MID_COMPACT_TOKENS", 10)
    monkeypatch.setattr(ctx, "MID_COMPACT_MIN_MSGS", 4)
    monkeypatch.setattr(ctx, "CONTEXT_KEEP_RECENT", 2)
    monkeypatch.setattr(ctx, "MID_COMPACT_EVERY", 1)
    monkeypatch.setattr(ctx, "context_budget", lambda window=None: {"window": 1000, "compact_at": 300, "hard_at": 800})

    manager = ContextManager(None, _FakeGateway())
    session = {"provider": "mock", "model": "mock", "id": "s1"}
    messages = [{"role": "system", "content": "BASE RULES"}] + _big_tool_messages(10)
    ledger = "- WRITTEN plan.html: 100 bytes, 3 lines, 5 visible chars, 1/12 nav anchors resolved"
    result = asyncio_run(manager.midturn_compact(session, messages, 1, ledger_text=ledger))
    assert result["compacted"] > 0
    assert ctx.LEDGER_MARK in messages[0]["content"]
    assert "1/12 nav anchors resolved" in messages[0]["content"]


def test_midturn_compact_hysteresis_skips_small_regrowth(monkeypatch):
    calls = {"n": 0}

    class _CountingGateway(_FakeGateway):
        async def complete_text(self, provider, model, messages, thinking="off"):
            calls["n"] += 1
            return f"summary-{calls['n']}"

    monkeypatch.setattr(ctx, "MID_COMPACT_TOKENS", 10)
    monkeypatch.setattr(ctx, "MID_COMPACT_MIN_MSGS", 4)
    monkeypatch.setattr(ctx, "CONTEXT_KEEP_RECENT", 2)
    monkeypatch.setattr(ctx, "MID_COMPACT_EVERY", 1)
    monkeypatch.setattr(ctx, "COMPACT_HYSTERESIS_STEPS", 6)
    monkeypatch.setattr(ctx, "COMPACT_HYSTERESIS_RATIO", 1.3)
    # Budget such that the body sits just above the trigger but below the
    # hysteresis ceiling after the first compaction.
    monkeypatch.setattr(ctx, "context_budget", lambda window=None: {"window": 1000, "compact_at": 400, "hard_at": 800})

    manager = ContextManager(None, _CountingGateway())
    session = {"provider": "mock", "model": "mock", "id": "s2"}
    messages = [{"role": "system", "content": "BASE RULES"}] + _big_tool_messages(10)
    first = asyncio_run(manager.midturn_compact(session, messages, 1))
    assert first["compacted"] > 0
    # Rebuild the body so it sits above the trigger but below trigger * ratio
    # (a small regrowth right after a compaction): hysteresis must skip it.
    messages[1:] = [{"role": "tool", "content": "y" * 120} for _ in range(5)]
    second = asyncio_run(manager.midturn_compact(session, messages, 2))
    assert second["compacted"] == 0


def test_context_budget_scales_with_window(monkeypatch):
    monkeypatch.setattr(ctx, "CONTEXT_COMPACT_TOKENS", 20000)
    monkeypatch.setattr(ctx, "CONTEXT_HARD_LIMIT", 48000)
    small = ctx.context_budget(32000)
    large = ctx.context_budget(200000)
    assert small["compact_at"] <= 32000
    assert large["compact_at"] > small["compact_at"]
    assert large["hard_at"] > large["compact_at"]
    # Floors still apply for tiny windows.
    tiny = ctx.context_budget(1000)
    assert tiny["compact_at"] == 20000
    assert tiny["hard_at"] == 48000


def test_body_tokens_prefers_provider_count():
    manager = ContextManager(None, _FakeGateway())
    messages = [{"role": "system", "content": "x" * 4000}, {"role": "user", "content": "hi"}]
    # A provider-reported prompt of 90000 tokens means the body is ~89k, far above
    # the heuristic estimate; the larger value wins.
    assert manager.body_tokens(messages, last_prompt_tokens=90000) >= 80000


def test_guarded_tools_hides_reads_in_write_only_mode():
    names = ["write_file", "read_range", "list_dir", "reference_digest", "run_shell"]
    assert AgentRuntime._guarded_tools(names, {"write_only": True}) == ["write_file", "run_shell"]
    assert AgentRuntime._guarded_tools(names, {"write_only": False}) == names


def test_missing_deliverables_tracks_new_files(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    state = {"output_targets": [str(out)], "delivery_since": time.time() + 60}
    assert missing_deliverables(state) == [str(out)]
    (out / "plan.html").write_text("<html></html>", encoding="utf-8")
    state["delivery_since"] = 0.0
    assert missing_deliverables(state) == []


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


def _wait_status(client, session_id, statuses=("done", "error"), timeout=25.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        session = client.get(f"/api/sessions/{session_id}").json()["data"]["session"]
        last = session
        if session["status"] in statuses:
            return session
        time.sleep(0.1)
    raise AssertionError(f"session did not reach {statuses}: {last}")


def test_looping_model_is_stopped_by_no_progress_guard(client, tmp_path, monkeypatch):
    from core.harness import harness_instance

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "ref.html").write_text("<html>\n<body>ref</body>\n</html>\n", encoding="utf-8")

    async def fake_stream(provider, model, messages, tools=None, thinking="", strict=None):
        # A degraded model that always re-reads the same range and never writes.
        yield {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_loop",
                        "type": "function",
                        "function": {
                            "name": "read_range",
                            "arguments": json.dumps({"path": "ref.html", "start": 1, "end": 2}),
                        },
                    }
                ],
            },
            "usage": {},
            "provider": "mock",
            "model": "mock",
            "fallbacks": [],
            "finish_reason": "tool_calls",
        }

    monkeypatch.setattr(harness_instance().gateway, "stream", fake_stream)

    session = client.post(
        "/api/sessions",
        json={"kind": "dev", "title": "loop guard", "workspace": str(workspace)},
    ).json()["data"]
    client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": f"write the plan to {tmp_path / 'out'}"},
    )
    final = _wait_status(client, session["id"])
    assert final["status"] == "error"
    assert "no progress" in (final["error"] or "")


COMPLETE_PAGE = (
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><title>Plan</title></head><body>"
    + "".join(f"<p>Section {index}: " + ("详细内容 " * 30) + "</p>" for index in range(1, 16))
    + "</body></html>"
)


def test_delivered_file_then_spin_finishes_done(client, tmp_path, monkeypatch):
    from core.harness import harness_instance

    workspace = tmp_path / "ws2"
    workspace.mkdir()
    out = workspace / "plan.html"

    state = {"calls": 0}

    async def fake_stream(provider, model, messages, tools=None, thinking="", strict=None):
        state["calls"] += 1
        if state["calls"] == 1:
            call = {
                "id": "call_write",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": str(out), "content": COMPLETE_PAGE}),
                },
            }
        else:
            # After shipping the file the model keeps re-running one command.
            call = {
                "id": "call_shell",
                "type": "function",
                "function": {
                    "name": "run_shell",
                    "arguments": json.dumps({"command": "echo budget"}),
                },
            }
        yield {
            "type": "message",
            "message": {"role": "assistant", "content": "", "tool_calls": [call]},
            "usage": {},
            "provider": "mock",
            "model": "mock",
            "fallbacks": [],
            "finish_reason": "tool_calls",
        }

    monkeypatch.setattr(harness_instance().gateway, "stream", fake_stream)

    session = client.post(
        "/api/sessions",
        json={
            "kind": "dev",
            "title": "delivered then spin",
            "workspace": str(workspace),
            "gate_mode": "allow_all",
        },
    ).json()["data"]
    client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": f"write the plan to {out}"},
    )
    final = _wait_status(client, session["id"])
    assert out.is_file()
    assert final["status"] == "done"


def test_stub_deliverable_is_reported_incomplete(client, tmp_path, monkeypatch):
    """A file that exists but has no body must not be reported as done."""
    from core.harness import harness_instance

    workspace = tmp_path / "ws3"
    workspace.mkdir()
    out = workspace / "stub.html"

    state = {"calls": 0}

    async def fake_stream(provider, model, messages, tools=None, thinking="", strict=None):
        state["calls"] += 1
        if state["calls"] == 1:
            call = {
                "id": "call_write",
                "type": "function",
                "function": {
                    "name": "write_file",
                    "arguments": json.dumps({"path": str(out), "content": "<html>ok</html>"}),
                },
            }
        else:
            call = {
                "id": "call_shell",
                "type": "function",
                "function": {
                    "name": "run_shell",
                    "arguments": json.dumps({"command": "echo still here"}),
                },
            }
        yield {
            "type": "message",
            "message": {"role": "assistant", "content": "", "tool_calls": [call]},
            "usage": {},
            "provider": "mock",
            "model": "mock",
            "fallbacks": [],
            "finish_reason": "tool_calls",
        }

    monkeypatch.setattr(harness_instance().gateway, "stream", fake_stream)

    session = client.post(
        "/api/sessions",
        json={
            "kind": "dev",
            "title": "stub deliverable",
            "workspace": str(workspace),
            "gate_mode": "allow_all",
        },
    ).json()["data"]
    client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": f"write the plan to {out}"},
    )
    final = _wait_status(client, session["id"], timeout=40.0)
    assert final["status"] == "error"
    assert "incomplete" in (final["error"] or "")


TRUNCATED_PREFIX = (
    "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<style>\n.card{color:#fff}\n</style>\n</head>\n"
    "<body>\n<nav><a href=\"#s1\">1</a><a href=\"#s2\">2</a></nav>\n<div id=\"s1\" class=\"sec\">\n"
    + ("正文内容段落\n" * 200)
)


def test_truncated_write_is_salvaged_and_incomplete_is_flagged(client, tmp_path, monkeypatch):
    """A write cut by the output limit keeps its complete prefix; a partial page is not 'done'."""
    from core.harness import harness_instance

    workspace = tmp_path / "ws4"
    workspace.mkdir()
    out = workspace / "plan.html"
    # The adapter wraps unparseable arguments as {"_raw": ...} when the provider
    # truncated the tool call at the length limit.
    raw_arguments = json.dumps({"path": str(out), "content": TRUNCATED_PREFIX}, ensure_ascii=False)[:-1]

    state = {"calls": 0}

    async def fake_stream(provider, model, messages, tools=None, thinking="", strict=None):
        state["calls"] += 1
        if state["calls"] == 1:
            call = {
                "id": "call_trunc",
                "type": "function",
                "function": {"name": "write_file", "arguments": json.dumps({"_raw": raw_arguments}, ensure_ascii=False)},
            }
            finish = "length"
        else:
            call = None
            finish = "stop"
        message = {"role": "assistant", "content": "written" if call is None else "", "tool_calls": [call] if call else []}
        yield {
            "type": "message",
            "message": message,
            "usage": {},
            "provider": "mock",
            "model": "mock",
            "fallbacks": [],
            "finish_reason": finish,
        }

    monkeypatch.setattr(harness_instance().gateway, "stream", fake_stream)

    session = client.post(
        "/api/sessions",
        json={"kind": "dev", "title": "salvage", "workspace": str(workspace), "gate_mode": "allow_all"},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": f"write the plan to {out}"})
    final = _wait_status(client, session["id"], timeout=40.0)
    assert out.is_file()
    assert "正文内容段落" in out.read_text(encoding="utf-8")
    events = client.get(f"/api/sessions/{session['id']}/events?limit=5000").json()["data"]
    assert any(item["type"] == "write.salvaged" for item in events)
    assert final["status"] == "error"
    assert "incomplete" in (final["error"] or "")


def test_exploration_budget_arms_write_only(client, tmp_path, monkeypatch):
    """Reading many different files forever must hit the exploration budget."""
    from core import runtime as runtime_mod
    from core.harness import harness_instance

    monkeypatch.setattr(runtime_mod, "EXPLORATION_MAX_SEC", 0.0)
    monkeypatch.setattr(runtime_mod, "EXPLORATION_MAX_PROMPT_TOKENS", 0)

    workspace = tmp_path / "ws5"
    workspace.mkdir()
    for index in range(50):
        (workspace / f"doc{index}.txt").write_text(f"content {index}\n", encoding="utf-8")

    state = {"calls": 0}

    async def fake_stream(provider, model, messages, tools=None, thinking="", strict=None):
        state["calls"] += 1
        index = min(state["calls"], 49)
        call = {
            "id": f"call_{state['calls']}",
            "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": f"doc{index}.txt"})},
        }
        yield {
            "type": "message",
            "message": {"role": "assistant", "content": "", "tool_calls": [call]},
            "usage": {},
            "provider": "mock",
            "model": "mock",
            "fallbacks": [],
            "finish_reason": "tool_calls",
        }

    monkeypatch.setattr(harness_instance().gateway, "stream", fake_stream)

    session = client.post(
        "/api/sessions",
        json={"kind": "dev", "title": "explore budget", "workspace": str(workspace), "gate_mode": "allow_all"},
    ).json()["data"]
    client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": f"write the plan to {tmp_path / 'out'}"},
    )
    final = _wait_status(client, session["id"], timeout=40.0)
    events = client.get(f"/api/sessions/{session['id']}/events?limit=5000").json()["data"]
    assert any(item["type"] == "explore.budget" for item in events)
    assert final["status"] == "error"
