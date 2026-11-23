from __future__ import annotations

from core.contracts import ToolCall
from core.runtime import AgentRuntime


def _runtime() -> AgentRuntime:
    return AgentRuntime.__new__(AgentRuntime)


def test_loop_digest_returns_ledger_for_own_deliverable(tmp_path):
    out = tmp_path / "plan"
    out.mkdir()
    page = out / "index.html"
    page.write_text(
        "<html><body><nav><a href=\"#s1\">1</a><a href=\"#s2\">2</a></nav>"
        "<div id=\"s1\">hello</div></body></html>",
        encoding="utf-8",
    )
    session = {"workspace": str(tmp_path)}
    state = {
        "output_targets": [str(out)],
        "written_paths": [str(page)],
        "reference_paths": [],
        "total_steps": 12,
    }
    call = ToolCall(call_id="c1", name="read_range", arguments={"path": "plan/index.html", "start": 1, "end": 50})
    text = _runtime()._loop_digest(session, call, 9, state)
    assert "[loop guard]" in text
    assert "Authoritative state" in text
    assert "WRITTEN" in text
    assert "#s2" in text  # the unresolved anchor is reported


def test_loop_digest_gives_design_digest_for_reference(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(
        "<html><head><style>:root{--x:#123456} .kpi{color:#123456}</style></head>"
        "<body><div class=\"kpi\">k</div></body></html>",
        encoding="utf-8",
    )
    session = {"workspace": str(tmp_path)}
    state = {"output_targets": [], "written_paths": [], "reference_paths": [str(ref)], "total_steps": 3}
    call = ToolCall(call_id="c2", name="read_range", arguments={"path": "ref.html", "start": 1, "end": 9})
    text = _runtime()._loop_digest(session, call, 9, state)
    assert "[loop guard]" in text
    assert "design tokens" in text


def test_loop_digest_handles_missing_file(tmp_path):
    session = {"workspace": str(tmp_path)}
    state = {"output_targets": [], "written_paths": [], "reference_paths": [], "total_steps": 1}
    call = ToolCall(call_id="c3", name="read_range", arguments={"path": "nope.html", "start": 1, "end": 2})
    text = _runtime()._loop_digest(session, call, 9, state)
    assert "does not exist" in text
