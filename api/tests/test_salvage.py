from __future__ import annotations

import json

from core.runtime import announcement_prefix, salvage_truncated_write


def _truncated_write(path: str, content: str) -> str:
    raw = json.dumps({"path": path, "content": content}, ensure_ascii=False)
    return raw[:-1]  # drop the closing brace so it no longer parses


def test_salvage_recovers_complete_lines_and_path():
    content = "</style>\n" + ("<div>section</div>\n" * 120)
    raw = _truncated_write("git/neo-tts/v2/plan/index.html", content)
    recovered = salvage_truncated_write("write_file", raw)
    assert recovered is not None
    assert recovered["path"] == "git/neo-tts/v2/plan/index.html"
    assert recovered["content"].endswith("</div>\n")
    assert recovered["lines"] >= 120


def test_salvage_drops_partial_last_line():
    complete = "this line is complete and long enough\n" * 30
    raw = _truncated_write("a.html", complete + "second line is cut off mid")
    recovered = salvage_truncated_write("write_file", raw)
    assert recovered is not None
    assert recovered["content"].startswith("this line is complete")
    assert "cut off" not in recovered["content"]


def test_salvage_ignores_small_or_non_write_calls():
    assert salvage_truncated_write("write_file", _truncated_write("a.html", "tiny")) is None
    assert salvage_truncated_write("edit_file", _truncated_write("a.html", "x" * 800)) is None


def test_salvage_decodes_json_escapes():
    content = "<p>" + ("引用\n换行\t制表" * 80) + "</p>"
    raw = _truncated_write("a.html", content)
    recovered = salvage_truncated_write("write_file", raw)
    assert recovered is not None
    assert "引用\n换行\t制表" in recovered["content"]


def test_announcement_prefix_normalizes_and_truncates():
    a = announcement_prefix("I'll start by checking the current state of the deliverable directory!")
    b = announcement_prefix("  I'll start by checking   the current state of the deliverable directory")
    assert a == b
    assert len(a) <= 48
