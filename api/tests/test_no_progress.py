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
                    "arguments": json.dumps({"path": str(out), "content": "<html>ok</html>"}),
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

