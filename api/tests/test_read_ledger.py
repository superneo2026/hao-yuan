from __future__ import annotations

from tools import dev

from tests.test_tools import ctx_for


def _lines(count: int) -> str:
    return "\n".join(f"line {index}" for index in range(1, count + 1))


def test_read_range_second_time_is_skipped(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(_lines(100), encoding="utf-8")
    context = ctx_for(tmp_path)
    first = dev.read_range(context, {"path": "a.txt", "start": 10, "end": 20})
    assert "line 10" in first
    second = dev.read_range(context, {"path": "a.txt", "start": 10, "end": 20})
    assert "already read" in second
    assert "line 10" not in second


def test_read_file_default_range_is_ledgered(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(_lines(500), encoding="utf-8")
    context = ctx_for(tmp_path)
    first = dev.read_file(context, {"path": "a.txt"})
    assert "line 400" in first
    second = dev.read_file(context, {"path": "a.txt"})
    assert "already read" in second


def test_read_ledger_merges_overlapping_ranges(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text(_lines(100), encoding="utf-8")
    context = ctx_for(tmp_path)
    dev.read_range(context, {"path": "a.txt", "start": 1, "end": 40})
    dev.read_range(context, {"path": "a.txt", "start": 30, "end": 60})
    covered = dev.read_range(context, {"path": "a.txt", "start": 1, "end": 60})
    assert "already read" in covered


def test_read_ledger_resets_after_edit(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    context = ctx_for(tmp_path)
    dev.read_range(context, {"path": "a.txt", "start": 1, "end": 3})
    path.write_text("a\nb\nc\nd\n", encoding="utf-8")
    fresh = dev.read_range(context, {"path": "a.txt", "start": 1, "end": 3})
    assert "already read" not in fresh
    assert "a" in fresh
