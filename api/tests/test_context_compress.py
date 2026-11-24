from __future__ import annotations

from core import context
from core.context import AGED_MARK, TOOL_COMPRESS_MARK, age_tool_results, compress_tool_output


def _long_success() -> str:
    body = "\n".join(f"collected item {index}" for index in range(200))
    return "$ python collect.py\n[exit 0]\n" + body


def _long_failure() -> str:
    middle = "\n".join(f"step {index} ok" for index in range(100))
    return (
        "$ pytest -q\n[exit 1]\n"
        + middle
        + "\nFAILED tests/test_inventory.py::test_atomic - AssertionError: stock went negative\n"
        + "Traceback (most recent call last):\n"
        + "\n".join(f"frame {index}" for index in range(100))
        + "\nAssertionError: expected 0, got -1\n"
    )


def test_clean_shell_output_becomes_one_line_summary(monkeypatch):
    monkeypatch.setattr(context, "TOOL_COMPRESS_ENABLED", True)
    monkeypatch.setattr(context, "TOOL_COMPRESS_MIN_CHARS", 100)
    monkeypatch.setattr(context, "TOOL_COMPRESS_HEAD_LINES", 10)
    monkeypatch.setattr(context, "TOOL_COMPRESS_TAIL_LINES", 10)
    text = _long_success()
    compressed, state = compress_tool_output(text, ok=True)
    assert len(compressed) < len(text)
    assert "no failures" in compressed
    assert TOOL_COMPRESS_MARK in compressed
    assert state["sha"]


def test_nonzero_exit_without_error_words_is_not_summarized_as_clean(monkeypatch):
    monkeypatch.setattr(context, "TOOL_COMPRESS_ENABLED", True)
    monkeypatch.setattr(context, "TOOL_COMPRESS_MIN_CHARS", 100)
    monkeypatch.setattr(context, "TOOL_COMPRESS_HEAD_LINES", 5)
    monkeypatch.setattr(context, "TOOL_COMPRESS_TAIL_LINES", 5)
    text = "$ ./run.sh\n[exit 2]\n" + "\n".join(f"row {index}" for index in range(200))
    compressed, _state = compress_tool_output(text, ok=True)
    assert "no failures" not in compressed
    assert "[exit 2]" in compressed
    assert "lines omitted" in compressed


def test_failure_keeps_head_tail_and_error_lines(monkeypatch):
    monkeypatch.setattr(context, "TOOL_COMPRESS_ENABLED", True)
    monkeypatch.setattr(context, "TOOL_COMPRESS_MIN_CHARS", 100)
    monkeypatch.setattr(context, "TOOL_COMPRESS_HEAD_LINES", 5)
    monkeypatch.setattr(context, "TOOL_COMPRESS_TAIL_LINES", 5)
    text = _long_failure()
    compressed, _state = compress_tool_output(text, ok=False)
    assert len(compressed) < len(text)
    assert "step 50 ok" not in compressed
    assert "FAILED tests/test_inventory.py" in compressed
    assert "Traceback (most recent call last)" in compressed
    assert "AssertionError: expected 0, got -1" in compressed
    assert "lines omitted" in compressed


def test_identical_failure_is_collapsed(monkeypatch):
    monkeypatch.setattr(context, "TOOL_COMPRESS_ENABLED", True)
    monkeypatch.setattr(context, "TOOL_COMPRESS_MIN_CHARS", 100)
    text = _long_failure()
    _first, state = compress_tool_output(text, ok=False)
    second, _ = compress_tool_output(text, ok=False, previous=state)
    assert "same failure as previous call" in second
    assert len(second) < len(text)


def test_repeated_failure_reports_only_new_lines(monkeypatch):
    monkeypatch.setattr(context, "TOOL_COMPRESS_ENABLED", True)
    monkeypatch.setattr(context, "TOOL_COMPRESS_MIN_CHARS", 100)
    text = _long_failure()
    _first, state = compress_tool_output(text, ok=False)
    changed = text + "\nAssertionError: a different assertion failed\n"
    second, _ = compress_tool_output(changed, ok=False, previous=state)
    assert "new lines since previous failure" in second
    assert "a different assertion failed" in second
    assert len(second) < len(changed)


def test_aging_skips_already_compressed_output():
    compressed = "summary" + TOOL_COMPRESS_MARK
    messages = [
        {"role": "tool", "content": compressed + "x" * 1000},
        {"role": "tool", "content": "y" * 1000},
    ]
    aged = age_tool_results(messages, keep=0, chars=100)
    assert aged == 1
    assert messages[0]["content"].startswith("summary")
    assert TOOL_COMPRESS_MARK in messages[0]["content"]
    assert AGED_MARK in messages[1]["content"]
