from __future__ import annotations

import asyncio
import difflib
import glob as globlib
import hashlib
import json
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from configs.configs import (
    API_DIR,
    APPLY_PATCH_ENABLED,
    GATE_CONFIRM_TIMEOUT,
    GREP_MAX_CHARS,
    GREP_MAX_HITS,
    SEARCH_MAX_FILES,
    SEARCH_MAX_FILE_BYTES,
    SEARCH_SKIP_DIRS,
    SEARCH_TIME_BUDGET,
    SHELL_TIMEOUT,
    TOOL_RESULT_MAX_BYTES,
    VERIFY_CMD_HINTS,
    WEB_FETCH_ENABLED,
    WEB_FETCH_TIMEOUT,
)
from core.contracts import ToolContext, ToolSpec
from harness import evidence as evidence_analysis
from harness import reference as reference_analysis
from harness import vision as vision_analysis
from harness import webfetch
from harness.sandbox import SafeWorkspace

_CHILD_IO_ENV = {
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONLEGACYWINDOWSSTDIO": "0",
}


def _workspace(ctx: ToolContext) -> SafeWorkspace:
    if not ctx.workspace:
        raise ValueError("session has no workspace bound")
    return SafeWorkspace(ctx.workspace)


def _truncate(text: str, limit: int | None = None) -> str:
    limit = limit or TOOL_RESULT_MAX_BYTES
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + f"\n... [truncated at {limit} bytes; read a narrower range]"


def _read_ledger(ctx: ToolContext) -> dict[str, Any]:
    ledger = ctx.session.get("_read_ledger")
    if not isinstance(ledger, dict):
        ledger = {}
        ctx.session["_read_ledger"] = ledger
    return ledger


def _file_entry(ctx: ToolContext, key: str, content: str) -> dict[str, Any]:
    digest = hashlib.sha1(content.encode("utf-8", errors="replace")).hexdigest()
    ledger = _read_ledger(ctx)
    entry = ledger.get(key)
    if not isinstance(entry, dict) or entry.get("hash") != digest:
        entry = {"hash": digest, "ranges": []}
        ledger[key] = entry
    return entry


def _covered(entry: dict[str, Any], start: int, end: int) -> bool:
    return any(a <= start and end <= b for a, b in entry.get("ranges") or [])


def _overlaps(entry: dict[str, Any], start: int, end: int) -> bool:
    return any(not (end < a or start > b) for a, b in entry.get("ranges") or [])


def _record(entry: dict[str, Any], start: int, end: int) -> None:
    merged: list[list[int]] = []
    ranges = list(entry.get("ranges") or []) + [[start, end]]
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    entry["ranges"] = merged


def _suggest_similar(src: str, old: str, limit: int = 3) -> str:
    lines = src.splitlines()
    if not lines:
        return "(target file is empty; use write_file)"
    stripped = [line.strip() for line in lines]
    seeds = [line.strip() for line in (old or "").splitlines() if line.strip()]
    if not seeds:
        return "(old snippet is empty)"
    hits, seen = [], set()
    for seed in seeds[:3]:
        for candidate in difflib.get_close_matches(seed, stripped, n=limit, cutoff=0.5):
            for index, text in enumerate(stripped, 1):
                if text == candidate and index not in seen:
                    seen.add(index)
                    hits.append(f"  line {index}: {lines[index - 1].strip()[:140]}")
                    break
        if len(hits) >= limit:
            break
    if not hits:
        return "(no similar line found; read the file again before editing)"
    return "Closest candidates:\n" + "\n".join(hits[:limit])


def _read_budget_chars() -> int:
    """Raw text a read may return so the JSON-wrapped result still fits the context cap.

    The runtime keeps at most TOOL_RESULT_CONTEXT_CHARS of each tool result. Reads
    used to ignore that and get clipped by the runtime at an arbitrary byte, so the
    model never knew which lines it had actually seen. Reading within this budget
    lets the tool itself report the exact range returned.
    """
    from configs.configs import TOOL_RESULT_CONTEXT_CHARS

    return max(2000, int(TOOL_RESULT_CONTEXT_CHARS * 0.78))


def _json_cost(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False)) - 2


def _clip_line(text: str, budget: int) -> str:
    return text[: max(0, budget - 60)] + " ...[line clipped: this single line exceeds the result budget; use run_shell/python to slice it]"


def _render_lines(lines: list[str], start: int, end: int, budget: int) -> tuple[str, int]:
    """Render numbered lines ``start..end`` (1-based, inclusive) within ``budget``.

    Returns the rendered text and the last line that was actually rendered.
    """
    parts: list[str] = []
    used = 0
    last = start - 1
    for index in range(start, end + 1):
        piece = f"{index}: {lines[index - 1]}"
        cost = _json_cost(piece)
        if cost > budget:
            piece = _clip_line(piece, budget)
            cost = _json_cost(piece)
        if parts and used + cost > budget:
            break
        parts.append(piece)
        used += cost
        last = index
        if used >= budget:
            break
    return "".join(parts), last


def _range_note(start: int, end: int, last: int) -> str:
    if last >= end:
        return ""
    return (
        f"\n[range clipped to fit the tool-result budget: lines {start}-{last} of the requested "
        f"{start}-{end} were returned. Call read_range(start={last + 1}, end={end}) for the rest; "
        "do not repeat the lines you already have.]"
    )


def read_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    offset = max(int(args.get("offset") or 1), 1)
    limit = int(args.get("limit") or 400)
    start = offset
    end = min(offset + limit - 1, len(lines))
    label = str(args.get("path") or "")
    entry = _file_entry(ctx, str(path), content)
    if start <= end and _covered(entry, start, end):
        return _truncate(
            f"[read_file] {label}: lines {start}-{end} were already read earlier in this run. "
            "Reuse that content instead of re-reading; request a different range only if you need new lines."
        )
    body, last = _render_lines(lines, start, end, _read_budget_chars())
    head = f"{label} ({len(lines)} lines)"
    overlap_note = ""
    if start <= end and _overlaps(entry, start, end):
        overlap_note = "\n[read ledger] This range overlaps lines already read; avoid re-reading unchanged ranges."
    if last >= start:
        # Record only what the model actually received, so a later request for the
        # clipped remainder is served instead of being refused as "already read".
        _record(entry, start, last)
    rendered = f"{head}\n{body}{_range_note(start, end, last)}{overlap_note}" if body else f"{head} is empty"
    return _truncate(rendered)


def read_range(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    content = path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    start = max(int(args.get("start") or 1), 1)
    end = int(args.get("end") or (start + 119))
    if end < start:
        start, end = end, start
    end = min(end, len(lines))
    label = str(args.get("path") or "")
    entry = _file_entry(ctx, str(path), content)
    if start <= end and _covered(entry, start, end):
        return _truncate(
            f"[read_range] {label}: lines {start}-{end} were already read earlier in this run. "
            "Reuse that content instead of re-reading; request a different range only if you need new lines."
        )
    body, last = _render_lines(lines, start, end, _read_budget_chars())
    head = f"{label} (range {start}-{end} / {len(lines)} lines)"
    overlap_note = ""
    if start <= end and _overlaps(entry, start, end):
        overlap_note = "\n[read ledger] This range overlaps lines already read; avoid re-reading unchanged ranges."
    if last >= start:
        _record(entry, start, last)
    rendered = f"{head}\n{body}{_range_note(start, end, last)}{overlap_note}" if body else f"{head} (empty range)"
    return _truncate(rendered)


def search_symbol(ctx: ToolContext, args: dict[str, Any]) -> str:
    from harness import repoindex

    query = args.get("name") or args.get("query") or ""
    kind = str(args.get("kind") or "").strip()
    hits = repoindex.search_symbols(ctx.workspace, query, kind=kind, limit=int(args.get("limit") or 30))
    if not hits:
        index = repoindex.get_index(ctx.workspace)
        return (
            f"symbol '{query}' not found. Indexed {len(index['files'])} files / "
            f"{len([s for s in index['symbols'] if s['kind'] != 'import'])} symbols. "
            "Try a shorter query or grep."
        )
    rows = [f"{s['path']}:{s['line']}  {s['name']}  {s.get('sig') or s['kind']}" for s in hits]
    return _truncate(f"symbol '{query}' matched {len(hits)}:\n" + "\n".join(rows))


def write_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = args.get("path", "")
    content = args.get("content", "")
    existed = workspace.resolve(path).exists()
    workspace.write_text(path, content)
    return f"{'overwrote' if existed else 'created'} {path} ({len(content)} chars)"


def _apply_search_replace_blocks(src: str, text: str) -> tuple[str | None, str | None]:
    pattern = re.compile(r"<{5,9}\s*SEARCH\s*\n(.*?)\n={5,9}\s*\n(.*?)\n>{5,9}\s*REPLACE", re.S)
    blocks = pattern.findall(text or "")
    if not blocks:
        return None, None
    out = src
    for old, new in blocks:
        if old == "":
            return None, "SEARCH block is empty"
        if out.count(old) == 0:
            return None, f"SEARCH snippet not found:\n{old[:300]}"
        if out.count(old) > 1:
            return None, f"SEARCH snippet matched {out.count(old)} positions"
        out = out.replace(old, new, 1)
    return out, None


def _apply_unified_diff(src: str, diff_text: str) -> tuple[str | None, str | None]:
    sr_src, sr_err = _apply_search_replace_blocks(src, diff_text)
    if sr_src is not None or sr_err is not None:
        return sr_src, sr_err
    lines = diff_text.splitlines()
    hunks = []
    current = None
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if match:
            current = {
                "old_start": int(match.group(1)),
                "old_len": int(match.group(2) or 1),
                "lines": [],
            }
            hunks.append(current)
            continue
        if current is not None and (line.startswith((" ", "+", "-")) or line == ""):
            current["lines"].append(line if line else " ")
    if not hunks:
        return None, (
            "unrecognized patch format. Use unified diff with @@ hunks or "
            "<<<<<<< SEARCH / ======= / >>>>>>> REPLACE blocks."
        )
    source_lines = src.splitlines(keepends=True)
    result = source_lines[:]
    offset = 0
    for hunk in hunks:
        old_body = [line[1:] for line in hunk["lines"] if line.startswith((" ", "-"))]
        new_body = [line[1:] if line else "" for line in hunk["lines"] if line.startswith((" ", "+"))]

        def norm(value: str) -> str:
            return value.rstrip("\r\n")

        old_norm = [norm(line) for line in old_body]
        position = hunk["old_start"] - 1 + offset
        candidates = [position] + [position + d for d in range(1, 201)] + [position - d for d in range(1, 201)]
        applied_at = None
        for candidate in candidates:
            if candidate < 0 or candidate + len(old_norm) > len(result):
                continue
            window = [norm(line) for line in result[candidate : candidate + len(old_norm)]]
            if window == old_norm:
                applied_at = candidate
                break
        if applied_at is None:
            return None, (
                f"hunk cannot be applied: no context match near line {hunk['old_start']}. "
                "Regenerate the patch from the current file content."
            )
        result[applied_at : applied_at + len(old_norm)] = [line + "\n" for line in new_body]
        offset = applied_at - (hunk["old_start"] - 1) + (len(new_body) - len(old_norm))
    return "".join(result), None


def apply_patch(ctx: ToolContext, args: dict[str, Any]) -> str:
    if not APPLY_PATCH_ENABLED:
        raise ValueError("apply_patch is disabled")
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')} (use write_file to create)")
    patch = args.get("patch") or args.get("diff") or ""
    if not patch.strip():
        raise ValueError("patch is empty")
    src = path.read_text(encoding="utf-8", errors="replace")
    new_src, error = _apply_unified_diff(src, patch)
    if error:
        raise ValueError(f"patch failed: {error}")
    if new_src == src:
        return f"patch applied but content unchanged: {args.get('path')}"
    workspace.write_text(args.get("path", ""), new_src or "")
    diff = list(difflib.unified_diff(src.splitlines(), (new_src or "").splitlines(), lineterm=""))
    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    return f"patched {args.get('path')} (+{added} / -{removed} lines)"


def edit_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    src = path.read_text(encoding="utf-8", errors="replace")
    old, new = args.get("old", ""), args.get("new", "")
    count = src.count(old)
    if count == 0:
        raise ValueError(f"old snippet not found\n{_suggest_similar(src, old)}")
    if count > 1 and not args.get("replace_all"):
        raise ValueError(f"old snippet matched {count} places; make it unique or pass replace_all=true")
    dst = src.replace(old, new) if args.get("replace_all") else src.replace(old, new, 1)
    workspace.write_text(args.get("path", ""), dst)
    replaced = count if args.get("replace_all") else 1
    return f"edited {args.get('path')}: replaced {replaced} (+{len(new)} / -{len(old)} chars)"


def _glob_to_re(pattern: str):
    pat = (pattern or "**/*").replace("\\", "/")
    out, index = [], 0
    while index < len(pat):
        if pat.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pat.startswith("**", index):
            out.append(".*")
            index += 2
        elif pat[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pat[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(pat[index]))
            index += 1
    return re.compile("^" + "".join(out) + "$")


def _search_files(base: str, pattern: str):
    regex = _glob_to_re(pattern)
    deadline = time.monotonic() + SEARCH_TIME_BUDGET
    hits, truncated = [], False
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SEARCH_SKIP_DIRS)
        rel_dir = os.path.relpath(root, base).replace("\\", "/")
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for name in sorted(files):
            rel = prefix + name
            if not regex.match(rel):
                continue
            hits.append((os.path.join(root, name), rel))
            if len(hits) >= SEARCH_MAX_FILES or time.monotonic() > deadline:
                truncated = True
                return hits, truncated
    return hits, truncated


def glob_files(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    matches, truncated = _search_files(str(workspace.root), args.get("pattern") or "**/*")
    rels = sorted(rel for _, rel in matches)[:200]
    tip = ""
    if truncated:
        tip = (
            f"\n[scan truncated at {SEARCH_MAX_FILES} files / {SEARCH_TIME_BUDGET}s; "
            "use a narrower pattern]"
        )
    return _truncate(f"matched {len(rels)} files:\n" + "\n".join(rels) + tip)


def grep_search(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    try:
        regex = re.compile(args.get("pattern", ""))
    except re.error as exc:
        raise ValueError(f"invalid regex: {exc}")
    files, truncated = _search_files(str(workspace.root), args.get("include") or "**/*")
    want_content = bool(args.get("content"))
    by_file: dict[str, list[tuple[int, str]]] = {}
    total = 0
    for path, rel in files:
        try:
            if os.path.getsize(path) > SEARCH_MAX_FILE_BYTES:
                continue
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                for index, line in enumerate(handle, 1):
                    if not regex.search(line):
                        continue
                    total += 1
                    if total <= GREP_MAX_HITS:
                        by_file.setdefault(rel, []).append((index, line.strip()[:160]))
        except (OSError, UnicodeError):
            continue
    blocks = []
    chars = 0
    for rel, items in by_file.items():
        if want_content:
            body = "\n".join(f"{rel}:{index}: {text}" for index, text in items)
        else:
            nums = ", ".join(str(index) for index, _ in items[:20])
            more = f" ...(+{len(items) - 20} lines)" if len(items) > 20 else ""
            body = f"{rel}: {nums}{more}"
        if chars + len(body) > GREP_MAX_CHARS:
            blocks.append("... [too many matches; narrow the include pattern or regex]")
            break
        blocks.append(body)
        chars += len(body) + 1
    head = f"{total} matches / {len(by_file)} files"
    if total > GREP_MAX_HITS:
        head += f" (showing first {GREP_MAX_HITS})"
    if not want_content and by_file:
        head += "\n(only line numbers are shown; pass content=true for the matched text)"
    tip = ""
    if truncated:
        tip = f"\n[scan truncated at {SEARCH_MAX_FILES} files / {SEARCH_TIME_BUDGET}s]"
    return _truncate(head + "\n" + ("\n".join(blocks) if blocks else "(no matches)") + tip)


def _failure_digest(stderr: str, stdout: str) -> str:
    text = (stderr or "") + "\n" + (stdout or "")
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    picked = []
    for line in lines:
        text_line = line.strip()
        if (
            text_line.startswith(("E ", "ERROR"))
            or "AssertionError" in text_line
            or re.match(r"^\w*(Error|Exception)\b", text_line)
            or "FAILED" in text_line
            or "error:" in text_line.lower()
        ):
            picked.append(text_line[:240])
    if not picked:
        picked = [line.strip()[:240] for line in lines[-3:]]
    return "\n".join(f"  - {item}" for item in list(dict.fromkeys(picked))[:5])


def _decode_child_output(raw: bytes) -> str:
    if not raw:
        return ""
    encodings = ["utf-8"]
    local = locale.getpreferredencoding(False)
    if local and local.replace("-", "").lower() not in ("utf8",):
        encodings.append(local)
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _test_digest_block(stdout: str, stderr: str) -> str:
    try:
        from harness import repair

        parsed = repair.parse_pytest((stdout or "") + "\n" + (stderr or ""))
        failures = parsed.get("failures") or []
        failed = (parsed.get("summary") or {}).get("failed", 0)
        if not failures and not failed:
            return ""
        lines = ["[structured test failure digest]"]
        if parsed.get("summary"):
            lines.append(
                f"- summary: {parsed['summary']['failed']} failed / {parsed['summary']['passed']} passed"
            )
        for failure in failures[:8]:
            loc = f" @ {failure['locations'][0]}" if failure.get("locations") else ""
            lines.append(f"- FAILED {failure['node']}{loc}  {failure.get('exc') or ''}: {(failure.get('error') or '')[:150]}")
            for assertion in (failure.get("asserts") or [])[:2]:
                lines.append(f"  assert: {assertion[:180]}")
        return "\n".join(lines)
    except Exception:
        return ""


def is_test_command(command: str) -> bool:
    lowered = (command or "").lower()
    return any(
        hint in lowered
        for hint in (
            "pytest", "unittest", "jest", "vitest", "mocha", "go test", "cargo test",
            "mvn test", "gradle test", "dotnet test", "tox ", "nosetests",
        )
    )


_BLOCKED_COMMANDS = (
    "rm -rf /",
    "rm -fr /",
    "del /f /s /q c:\\",
    "rd /s /q c:\\",
    "remove-item -recurse -force c:\\",
    "format ",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    ":(){",
    "fork()",
    "> /dev/sda",
    "chmod -r 777 /",
)

_TAIL_PIPE_RE = re.compile(r"(?is)^(.*?)\|\s*tail\s+(?:-n\s*|-)?(\d+)\s*$")
_HEAD_PIPE_RE = re.compile(r"(?is)^(.*?)\|\s*head\s+(?:-n\s*|-)?(\d+)\s*$")
_CAT_RE = re.compile(r"(?is)^\s*cat\s+([^\s|&<>]+)\s*$")


def normalize_shell_command(command: str) -> str:
    """Adapt common Unix-only pipes to the native Windows cmd.exe shell.

    This keeps Windows runs from wasting a step on ``'tail' is not recognized``
    while leaving every other command untouched.
    """
    if os.name != "nt":
        return command
    for pattern, selector in ((_TAIL_PIPE_RE, "Last"), (_HEAD_PIPE_RE, "First")):
        match = pattern.match(command)
        if match:
            base = match.group(1).strip()
            count = max(0, int(match.group(2)))
            if base:
                return f'{base} | powershell -NoProfile -Command "$input | Select-Object -{selector} {count}"'
    match = _CAT_RE.match(command)
    if match:
        return f"type {match.group(1)}"
    return command


def run_shell(ctx: ToolContext, args: dict[str, Any]) -> str:
    command = args.get("command", "")
    if not command.strip():
        raise ValueError("command is empty")
    lowered = command.lower()
    if any(pattern in lowered for pattern in _BLOCKED_COMMANDS):
        raise ValueError("command blocked by safety policy: catastrophic pattern detected")
    workspace = _workspace(ctx)
    env = os.environ.copy()
    env.update(_CHILD_IO_ENV)
    adapted = normalize_shell_command(command)
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        adapted,
        shell=True,
        cwd=str(workspace.root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        creationflags=creationflags,
    )
    try:
        stdout_raw, stderr_raw = process.communicate(timeout=SHELL_TIMEOUT)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except Exception:
                process.kill()
        try:
            stdout_raw, stderr_raw = process.communicate(timeout=10)
        except Exception:
            stdout_raw, stderr_raw = b"", b""
        partial = _decode_child_output(stdout_raw)
        return _truncate(
            f"$ {command}\n[timeout after {int(SHELL_TIMEOUT)}s; process tree terminated]"
            + (("\n" + partial.strip()[-2000:]) if partial.strip() else "")
        )
    stdout = _decode_child_output(stdout_raw)
    stderr = _decode_child_output(stderr_raw)
    out = stdout + (("\n[stderr] " + stderr) if stderr else "")
    head = f"$ {command}\n[exit {process.returncode}]"
    if adapted != command:
        head += f"\n[windows shell adapter] {adapted}"
    if process.returncode != 0:
        digest = _failure_digest(stderr, stdout)
        if digest:
            head += f"\n[key error lines]\n{digest}"
    body = _truncate(head + "\n" + (out.strip() or "(no output)"))
    if process.returncode != 0 and is_test_command(command):
        block = _test_digest_block(stdout, stderr)
        if block:
            body += "\n" + block
    return body


def git_tool(ctx: ToolContext, args: dict[str, Any]) -> str:
    action = args.get("action", "status")
    extra = args.get("args", "")
    allowed = {
        "status", "diff", "add", "commit", "log", "branch", "checkout", "stash",
        "show", "restore", "rev-parse", "ls-files", "blame",
    }
    if action not in allowed:
        raise ValueError(f"unsupported git action {action}; allowed: {sorted(allowed)}")
    return run_shell(ctx, {"command": f"git {action}" + (f" {extra}" if extra else "")})


def list_dir(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    items = workspace.list_dir(args.get("path", "."))
    target = args.get("path") or "."
    lines = []
    for item in items:
        if item["type"] == "dir":
            lines.append(f"{item['name']}/")
        else:
            lines.append(f"{item['name']}  ({item['size']}B)")
    return _truncate(f"{target} ({len(items)} items):\n" + "\n".join(lines))


def delete_path(ctx: ToolContext, args: dict[str, Any]) -> str:
    return _workspace(ctx).delete(args.get("path", ""), recursive=bool(args.get("recursive")))


def move_path(ctx: ToolContext, args: dict[str, Any]) -> str:
    return _workspace(ctx).move(args.get("src", ""), args.get("dst", ""))


def multi_edit(ctx: ToolContext, args: dict[str, Any]) -> str:
    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("edits must be a non-empty array")
    workspace = _workspace(ctx)
    by_file: dict[str, dict[str, Any]] = {}
    order = []
    for edit in edits:
        rel = edit.get("path")
        if not rel:
            raise ValueError("each edit requires path")
        path = workspace.resolve(rel)
        if str(path) not in by_file:
            if not path.is_file():
                raise FileNotFoundError(f"file not found: {rel}")
            by_file[str(path)] = {"rel": rel, "src": path.read_text(encoding="utf-8", errors="replace")}
            order.append(str(path))
        info = by_file[str(path)]
        old, new = edit.get("old", ""), edit.get("new", "")
        count = info["src"].count(old)
        if count == 0:
            raise ValueError(f"{rel}: old snippet not found\n{_suggest_similar(info['src'], old)}")
        if count > 1 and not edit.get("replace_all"):
            raise ValueError(f"{rel}: old snippet matched {count} places")
        info["src"] = (
            info["src"].replace(old, new)
            if edit.get("replace_all")
            else info["src"].replace(old, new, 1)
        )
    for path in order:
        workspace.write_text(by_file[path]["rel"], by_file[path]["src"])
    return f"atomic edit complete: {len(edits)} edits across {len(order)} files"


_PROJECT_MARKERS = (
    ("package.json", "Node/frontend"),
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
    ("go.mod", "Go"),
    ("pom.xml", "Java/Maven"),
    ("Cargo.toml", "Rust"),
    ("CMakeLists.txt", "C/C++"),
    ("vite.config.js", "Vite"),
    ("vite.config.ts", "Vite"),
    ("Dockerfile", "Docker"),
    ("docker-compose.yml", "Docker Compose"),
    ("Makefile", "Make"),
    ("AGENTS.md", "Agent conventions"),
    ("CLAUDE.md", "Agent conventions"),
    ("PROJECT.md", "Project memory"),
    ("pytest.ini", "pytest"),
    ("package-lock.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
)


def project_scan(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    base = str(workspace.root)
    top, markers = [], []
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        top.append(f"{name}/" if os.path.isdir(full) else name)
        for marker, tech in _PROJECT_MARKERS:
            if name == marker:
                markers.append((marker, tech))
    techs = sorted({tech for _, tech in markers})
    hints = []
    package = os.path.join(base, "package.json")
    if os.path.isfile(package):
        try:
            data = json.loads(open(package, "r", encoding="utf-8").read())
            scripts = list((data.get("scripts") or {}).keys())
            priority = ["dev", "test", "lint", "build", "typecheck", "format"]
            hints = [f"npm run {name}" for name in priority if name in scripts]
            hints += [f"npm run {name}" for name in scripts if name not in priority]
        except (OSError, ValueError):
            pass
    if "Python" in techs and "pytest.ini" in [marker for marker, _ in markers]:
        hints.append("python -m pytest")
    lines = [
        f"project root: {base}",
        f"detected stack: {', '.join(techs) if techs else 'no standard marker files'}",
        "top-level entries:\n  " + "\n  ".join(top[:60]),
        "suggested verification: " + (", ".join(hints[:8]) if hints else "use glob/grep to inspect further"),
    ]
    return _truncate("\n".join(lines))


def web_scaffold(ctx: ToolContext, args: dict[str, Any]) -> str:
    import shutil

    workspace = _workspace(ctx)
    rel = (args.get("path") or ".").strip() or "."
    base = workspace.resolve(rel)
    assets = base / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    source_dir = API_DIR / "assets" / "web"
    written, skipped = [], []
    for name in ("style.css", "app.js"):
        source = source_dir / name
        target = assets / name
        if target.exists() and not args.get("overwrite"):
            skipped.append(f"assets/{name}")
            continue
        if not source.is_file():
            return f"[web_scaffold] built-in design system missing: {source}"
        shutil.copyfile(source, target)
        written.append(f"assets/{name}")
    return "\n".join(
        [
            f"[web_scaffold] directory: {base}",
            "written: " + ", ".join(written) if written else "nothing written (files already exist)",
            "skipped: " + ", ".join(skipped) if skipped else "",
            "Include in every HTML page:",
            '  <link rel="stylesheet" href="assets/style.css">',
            '  <script src="assets/app.js"></script>',
            "Use classes: hero, kpi, sec, box, tw, cd, flow, code, callout, matrix, timeline, quote, topnav, nav.",
        ]
    )


def web_audit(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    base = workspace.resolve((args.get("path") or ".").strip() or ".")
    skip = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv"}
    html_files, css_files = [], []
    if base.is_file():
        if base.suffix.lower() in (".html", ".htm"):
            html_files.append(base)
    else:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
            for name in files:
                full = os.path.join(root, name)
                lowered = name.lower()
                if lowered.endswith((".html", ".htm")):
                    html_files.append(full)
                elif lowered.endswith(".css"):
                    css_files.append(full)
            if len(html_files) >= 80:
                break
    html_files = sorted(html_files)[:80]
    css_files = sorted(css_files)[:40]
    if not html_files:
        return f"[web_audit] no HTML files found under {base}"
    stray_files = []
    if base.is_dir():
        deliverable_exts = (".html", ".htm", ".css", ".js", ".json", ".md", ".svg", ".png",
                            ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".woff", ".woff2")
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isfile(full) and not name.lower().endswith(deliverable_exts):
                stray_files.append(name)
    css_blob = ""
    for path in css_files:
        try:
            css_blob += open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            pass
    css_has_media = "@media" in css_blob
    css_has_vars = ":root" in css_blob and "--" in css_blob
    issues = []
    pages = []
    shared_refs: dict[str, int] = {}
    total_inline = total_svg = total_table = 0
    for path in html_files:
        try:
            text = open(path, "r", encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        name = os.path.relpath(path, base)
        page_issues = []
        lowered = text.lower()
        if "<meta" not in lowered or "viewport" not in lowered:
            page_issues.append("missing viewport meta")
        if "<style" in lowered and "<link" not in lowered:
            page_issues.append("inline-only styles; use a shared stylesheet")
        for ref in re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\']', text, re.I):
            shared_refs[ref] = shared_refs.get(ref, 0) + 1
        inline = len(re.findall(r'style=["\']', text, re.I))
        total_inline += inline
        if inline > 20:
            page_issues.append(f"too many inline styles ({inline})")
        if not re.search(r"<(nav|header)\b", text, re.I):
            page_issues.append("missing nav/header")
        if len(re.findall(r"<h1\b", text, re.I)) != 1:
            page_issues.append("should contain exactly one <h1>")
        if not re.search(r"<(section|article|main)\b", text, re.I):
            page_issues.append("missing semantic sections")
        total_svg += len(re.findall(r"<svg\b", text, re.I))
        total_table += len(re.findall(r"<table\b", text, re.I))
        ids = re.findall(r'\bid=["\']([^"\']+)["\']', text)
        duplicates = sorted({item for item in ids if ids.count(item) > 1})
        if duplicates:
            page_issues.append("duplicate ids: " + ", ".join(duplicates[:6]))
        id_set = set(ids)
        anchors = re.findall(r'href=["\']#([^"\']+)["\']', text, re.I)
        broken_anchors = sorted({a for a in anchors if a not in id_set})
        if broken_anchors:
            page_issues.append("broken in-page anchors: " + ", ".join(broken_anchors[:8]))
        missing = []
        for ref in re.findall(r'(?:href|src)=["\']([^"\'#]+)["\']', text, re.I):
            if ref.lower().startswith(("http://", "https://", "//", "data:", "mailto:", "javascript:", "tel:")):
                continue
            target = os.path.normpath(os.path.join(os.path.dirname(path), ref.split("?")[0]))
            if not os.path.exists(target):
                missing.append(ref)
        if missing:
            page_issues.append("missing local assets: " + ", ".join(sorted(set(missing))[:6]))
        no_alt = [img for img in re.findall(r"<img\b[^>]*>", text, re.I) if "alt=" not in img.lower()]
        if no_alt:
            page_issues.append(f"{len(no_alt)} <img> missing alt")
        pages.append({"name": name, "issues": page_issues, "svg": 0, "table": 0, "inline": inline})
        issues.extend(f"{name}: {item}" for item in page_issues)
    if len(html_files) >= 2:
        if not css_files:
            issues.append("multi-page site has no CSS file; share assets/style.css")
        elif not css_has_media:
            issues.append("shared CSS has no @media responsive rules")
        if css_files and not css_has_vars:
            issues.append("shared CSS should define :root design tokens")
        if shared_refs and max(shared_refs.values()) < len(html_files):
            issues.append("not every page references the same shared CSS")
    score = max(0, 100 - 6 * len(issues) - 2 * sum(len(page["issues"]) for page in pages))
    grade = "A (ship)" if score >= 85 else ("B (fix first)" if score >= 65 else "C (rework)")
    lines = [
        f"[web_audit] directory: {base}",
        f"pages {len(html_files)} / css {len(css_files)} / inline styles {total_inline} / svg {total_svg} / tables {total_table}",
        f"design system: shared CSS={'yes' if css_files else 'no'} @media={'yes' if css_has_media else 'no'} variables={'yes' if css_has_vars else 'no'}",
        f"score: {score}/100 - {grade}",
    ]
    if stray_files:
        lines.append(
            "note: non-deliverable files in output directory: "
            + ", ".join(stray_files[:10])
            + " (move helper scripts to a temp dir before delivery)"
        )
    if issues:
        lines.append("must fix:")
        lines += [f"  {index}. {item}" for index, item in enumerate(issues[:24])]
    else:
        lines.append("no structural design issues found.")
    reference_path = str(args.get("reference") or "").strip()
    if reference_path:
        try:
            ref = workspace.resolve(reference_path)
            if ref.is_file():
                for target in html_files[:3]:
                    lines.append("")
                    lines.append(reference_analysis.compare(str(ref), target))
        except Exception as exc:
            lines.append(f"reference compare skipped: {type(exc).__name__}: {exc}")
    return _truncate("\n".join(lines), 8000)


async def ask_user(ctx: ToolContext, args: dict[str, Any]) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("question is required")
    if ctx.call is None:
        raise RuntimeError("ask_user requires an active tool call")
    options = args.get("options") or []
    if not isinstance(options, list):
        options = []
    clean = [str(item).strip()[:200] for item in options if str(item).strip()][:6]
    ctx.call.arguments = {
        **args,
        "question": question[:2000],
        "options": clean,
        "context": str(args.get("context") or "")[:2000],
        "allow_free_text": args.get("allow_free_text", True) is not False,
    }
    manager = getattr(ctx.runtime, "manager", None)
    if manager is None or not hasattr(manager, "ask_question"):
        raise RuntimeError("interactive questions are unavailable in this runtime")
    return await manager.ask_question(ctx.session, ctx.call, ctx.run_id)


def task_placeholder(ctx: ToolContext, args: dict[str, Any]) -> str:
    # The runtime intercepts `task` before it reaches the registry and runs the
    # subagent loop there. This handler exists only so the tool spec is
    # registered and advertised to the model.
    return "task is handled by the runtime subagent dispatcher"


async def web_fetch(ctx: ToolContext, args: dict[str, Any]) -> str:
    if not WEB_FETCH_ENABLED:
        return "[web_fetch] disabled by configuration (HAOYUAN_WEB_FETCH=0)"
    url = str(args.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    return await webfetch.fetch(url, args.get("max_chars") or None)


def reference_digest(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"reference not found: {args.get('path')}")
    return reference_analysis.digest(str(path), int(args.get("max_chars") or 9000))


def reference_compare(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    reference = workspace.resolve(args.get("reference", ""))
    target = workspace.resolve(args.get("target", ""))
    return reference_analysis.compare(str(reference), str(target))


def baseline_audit(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path") or ".")
    return evidence_analysis.baseline_audit(
        str(path), int(args.get("max_chars") or 12000)
    )


def doc_consistency(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    baseline = str(args.get("baseline") or "").strip()
    baseline_path = str(workspace.resolve(baseline)) if baseline else ""
    return evidence_analysis.doc_consistency(str(path), baseline_path)


async def describe_image(ctx: ToolContext, args: dict[str, Any]) -> Any:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path") or "")
    if not path.is_file():
        raise FileNotFoundError(f"image not found: {args.get('path')}")
    prompt = str(args.get("prompt") or "请描述这张图片的内容、布局和明显问题。")[:2000]
    mode = vision_analysis.vision_mode(ctx.session)
    if mode == "native":
        # The runtime attaches this image to the next model call; the main model
        # must have supports_vision=true.
        return vision_analysis.native_image_result(str(path), prompt)
    if mode == "sidecar":
        return await vision_analysis.describe_via_sidecar(
            str(path), prompt, int(args.get("max_tokens") or 800)
        )
    return (
        "[describe_image] 多模态能力未配置：当前主模型不支持视觉，也没有可用的 Qwen-VL sidecar。"
        "已按纯文本模式处理；可继续使用 web_audit / doc_consistency，或配置 "
        "ALIYUN_API_KEY / DASHSCOPE_API_KEY（或 aliyun 渠道的 qwen-vl 模型）。"
    )


def _find_browser() -> str | None:
    env_browser = os.getenv("HAOYUAN_BROWSER", "").strip()
    if env_browser and os.path.isfile(env_browser):
        return env_browser
    candidates: list[str] = []
    if os.name == "nt":
        for base in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)"), os.getenv("LOCALAPPDATA")):
            if not base:
                continue
            candidates += [
                os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
            ]
    elif sys.platform == "darwin":
        candidates += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        candidates += [
            "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/usr/bin/microsoft-edge",
        ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


async def web_screenshot(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    target = workspace.resolve(args.get("path") or "")
    if not target.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    if target.suffix.lower() not in (".html", ".htm"):
        raise ValueError("web_screenshot only supports .html/.htm files")
    browser = _find_browser()
    if not browser:
        return (
            "[web_screenshot] no Chrome/Edge executable found. Install Chrome/Edge or set "
            "HAOYUAN_BROWSER to the browser executable."
        )
    width = max(320, min(int(args.get("width") or 1440), 2560))
    height = max(240, min(int(args.get("height") or (6000 if args.get("full_page") else 900)), 20000))
    # Keep the screenshot inside the workspace so describe_image can read it
    # through SafeWorkspace; the hidden folder is ignored by web_audit.
    out_dir = workspace.root / ".haoyuan" / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    ignore = out_dir / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"{target.stem}-{width}x{height}-{stamp}.png"
    url = target.as_uri()
    with tempfile.TemporaryDirectory(prefix="haoyuan-shot-") as profile:
        command = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-sandbox",
            f"--user-data-dir={profile}",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            url,
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return "[web_screenshot] browser timed out after 60s"
        if not out.is_file() or out.stat().st_size == 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:800]
            return f"[web_screenshot] capture failed (exit {proc.returncode}): {detail}"
    try:
        record = await ctx.runtime.storage.create_artifact(
            ctx.session_id, str(out), "screenshot", out.name, out.stat().st_size
        )
        if ctx.emit:
            await ctx.emit(ctx.session_id, "artifact.created", record, ctx.run_id)
        artifact_id = record.get("id")
    except Exception:
        artifact_id = None
    return json.dumps(
        {
            "ok": True,
            "path": str(out),
            "artifact_id": artifact_id,
            "width": width,
            "height": height,
            "bytes": out.stat().st_size,
            "note": "Screenshot saved as an artifact. Open it in the UI for visual verification; text-only models cannot inspect the image.",
        },
        ensure_ascii=False,
    )


def _unified(old: str, new: str, path: str, max_lines: int = 60) -> str:
    diff = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="", n=2
        )
    )
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... [diff truncated, {len(diff)} lines total]"]
    return "\n".join(diff)


def preview(name: str, workspace: str, args: dict[str, Any]) -> str:
    try:
        safe = SafeWorkspace(workspace)
        if name in ("edit_file", "write_file", "apply_patch"):
            rel = args.get("path", "")
            path = safe.resolve(rel)
            old = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
            new = old
            if name == "write_file":
                new = args.get("content", "")
                label = "overwrite" if old else "create"
            elif name == "apply_patch":
                new_src, error = _apply_unified_diff(old, args.get("patch") or "")
                if error:
                    return f"[patch] {rel}\n(patch cannot be applied: {error})"
                new = new_src or ""
                label = "patch"
            else:
                old_piece = args.get("old", "")
                new_piece = args.get("new", "")
                new = (
                    old.replace(old_piece, new_piece)
                    if args.get("replace_all")
                    else old.replace(old_piece, new_piece, 1)
                )
                label = "edit"
            if old == new:
                return f"[{label}] {rel}\n(no content change)"
            return f"[{label}] {rel}\n" + _unified(old, new, rel)
        if name == "multi_edit":
            parts = [preview("edit_file", workspace, edit) for edit in (args.get("edits") or [])]
            return "\n\n".join(parts) if parts else "(no edits)"
        if name == "delete_path":
            return f"[delete] {args.get('path')}" + (" (recursive)" if args.get("recursive") else "")
        if name == "move_path":
            return f"[move] {args.get('src')} -> {args.get('dst')}"
        if name == "run_shell":
            return f"[shell] {args.get('command', '')}"
        if name == "git":
            return f"[git] {args.get('action', '')} {args.get('args', '')}".strip()
        if name == "web_scaffold":
            return f"[web scaffold] {args.get('path', '.')}"
    except Exception as exc:
        return f"(preview failed: {type(exc).__name__}: {exc})"
    return ""


def _spec(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None, **kwargs) -> ToolSpec:
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return ToolSpec(name=name, description=description, input_schema=schema, **kwargs)


def tool_specs(source: str = "coding") -> list[ToolSpec]:
    return [
        _spec("read_file", "Read a text file in the workspace, optionally by line offset/limit.", {
            "path": {"type": "string"},
            "offset": {"type": "integer"},
            "limit": {"type": "integer"},
        }, ["path"], readonly=True, source=source),
        _spec("read_range", "Read a precise line range [start, end] (1-based, inclusive).", {
            "path": {"type": "string"},
            "start": {"type": "integer"},
            "end": {"type": "integer"},
        }, ["path", "start"], readonly=True, source=source),
        _spec("search_symbol", "Find function/class/method definitions by name (file:line + signature).", {
            "name": {"type": "string"},
            "kind": {"type": "string"},
            "limit": {"type": "integer"},
        }, ["name"], readonly=True, source=source),
        _spec("apply_patch", "Apply a minimal unified diff (or SEARCH/REPLACE blocks) to an existing file.", {
            "path": {"type": "string"},
            "patch": {"type": "string"},
        }, ["path", "patch"], risk="high", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("write_file", "Create or fully overwrite a workspace file. Large files must be split: write a skeleton first, then append the rest with apply_patch/edit_file (<= 150 lines per call), because model output is length-capped.", {
            "path": {"type": "string"},
            "content": {"type": "string"},
        }, ["path", "content"], risk="high", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("edit_file", "Replace a unique snippet in a file with a new snippet.", {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "replace_all": {"type": "boolean"},
        }, ["path", "old", "new"], risk="high", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("multi_edit", "Atomically apply multiple snippet edits across files after validating all of them.", {
            "edits": {"type": "array", "items": {"type": "object"}},
        }, ["edits"], risk="high", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("glob", "List workspace files matching a glob pattern such as src/**/*.vue.", {
            "pattern": {"type": "string"},
        }, ["pattern"], readonly=True, source=source),
        _spec("grep", "Regex search workspace contents. Returns file:line by default; pass content=true for text.", {
            "pattern": {"type": "string"},
            "include": {"type": "string"},
            "content": {"type": "boolean"},
        }, ["pattern"], readonly=True, source=source),
        _spec("list_dir", "List directories and files in a workspace directory.", {
            "path": {"type": "string"},
        }, source=source, readonly=True),
        _spec("project_scan", "Detect project structure, stack markers, and suggested build/test commands.", {}, source=source, readonly=True),
        _spec("run_shell", "Run a shell command in the workspace (120s timeout, dangerous commands blocked).", {
            "command": {"type": "string"},
        }, ["command"], risk="high", side_effect="write", confirm=True, readonly=False, timeout_s=150, source=source),
        _spec("git", "Run a git read/write action (push is disabled).", {
            "action": {"type": "string"},
            "args": {"type": "string"},
        }, ["action"], risk="medium", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("delete_path", "Delete a workspace file or directory.", {
            "path": {"type": "string"},
            "recursive": {"type": "boolean"},
        }, ["path"], risk="high", side_effect="irreversible", confirm=True, readonly=False, source=source),
        _spec("move_path", "Move or rename a workspace file/directory.", {
            "src": {"type": "string"},
            "dst": {"type": "string"},
        }, ["src", "dst"], risk="high", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("web_scaffold", "Copy the built-in design system (style.css + app.js) into a web output directory.", {
            "path": {"type": "string"},
            "overwrite": {"type": "boolean"},
        }, risk="medium", side_effect="write", confirm=True, readonly=False, source=source),
        _spec("web_audit", "Static audit for multi-page HTML deliverables (responsive, links, a11y, consistency). Pass reference to also measure fidelity against a reference page.", {
            "path": {"type": "string"},
            "reference": {"type": "string"},
        }, readonly=True, source=source),
        _spec("reference_digest", "Extract the design system, structure, components and behaviors from a reference HTML/CSS/source file so a new deliverable can faithfully mirror it. Call this before building anything that says 'reference this page/file/style'.", {
            "path": {"type": "string"},
            "max_chars": {"type": "integer"},
        }, ["path"], readonly=True, source=source),
        _spec("reference_compare", "Check whether a generated page faithfully follows a reference page: palette, font stack, light/dark mode, breakpoints, and shared components.", {
            "reference": {"type": "string"},
            "target": {"type": "string"},
        }, ["reference", "target"], readonly=True, source=source),
        _spec("baseline_audit", "Extract measured facts (params, steps, minutes, CER, PESQ, F0, speakers, hours, licenses) from a prior project's README/MODEL_CARD/reports/data cards so a new plan can cite real baselines instead of guessing.", {
            "path": {"type": "string", "description": "Baseline project directory (or one report file)."},
            "max_chars": {"type": "integer", "description": "Output cap; default 12000."},
        }, ["path"], readonly=True, source=source),
        _spec("doc_consistency", "Check a plan/report HTML for cross-section contradictions (same entity with different numbers/attributes) and compare against a baseline directory when provided. Run before finishing any research deliverable.", {
            "path": {"type": "string", "description": "Generated plan/report HTML file."},
            "baseline": {"type": "string", "description": "Optional baseline project directory for data-card cross-checks."},
        }, ["path"], readonly=True, source=source),
        _spec("web_screenshot", "Capture a workspace HTML page with headless Chrome/Edge at a viewport (default 1440x900). Use height>=6000 or full_page for long reports. Saves a PNG artifact for visual verification and delivery.", {
            "path": {"type": "string", "description": "HTML file inside the workspace."},
            "width": {"type": "integer", "description": "Viewport width; default 1440."},
            "height": {"type": "integer", "description": "Viewport height; default 900, or 6000 with full_page."},
            "full_page": {"type": "boolean", "description": "Use a tall viewport for a full-report capture."},
        }, ["path"], readonly=True, source=source),
        _spec("describe_image", "Understand an image (screenshot/photo) with the hybrid vision path: if the main model supports vision, attach the image to the next model call (native); otherwise use the Qwen-VL sidecar and return text; if neither is configured, return a clear text-only notice.", {
            "path": {"type": "string", "description": "Image file inside the workspace (png/jpg/webp/gif)."},
            "prompt": {"type": "string", "description": "What to look for; default describes layout and visible problems."},
            "max_tokens": {"type": "integer", "description": "Sidecar output cap; default 800."},
        }, ["path"], readonly=True, source=source),
        _spec("ask_user", "Pause the running task and ask the user a blocking question. Call this instead of ending your turn whenever a decision, missing detail, or confirmation blocks safe progress. The task resumes in place with the user's answer.", {
            "question": {"type": "string", "description": "One clear, specific question."},
            "options": {"type": "array", "items": {"type": "string"}, "description": "Optional 2-4 short choices."},
            "allow_free_text": {"type": "boolean", "description": "Allow a typed answer in addition to the options."},
            "context": {"type": "string", "description": "Short context explaining why the answer matters."},
        }, ["question"], readonly=True, timeout_s=GATE_CONFIRM_TIMEOUT + 30, source=source),
        _spec("task", "Dispatch a read-only subagent with its own context and return only its conclusion.", {
            "description": {"type": "string"},
            "prompt": {"type": "string"},
            "readonly": {"type": "boolean"},
        }, ["description", "prompt"], readonly=True, subagent=True, source=source),
        _spec("web_fetch", "Fetch a public http(s) URL and return its readable text (HTML is stripped to text; JSON/plain/markdown pass through). Use it to verify external facts before citing them: licenses, model specs, dataset sizes, API docs. Private/loopback addresses are blocked. When a fetch fails, label the fact as unverified instead of guessing.", {
            "url": {"type": "string", "description": "Absolute http:// or https:// URL."},
            "max_chars": {"type": "integer", "description": "Output cap; default 12000."},
        }, ["url"], readonly=True, timeout_s=WEB_FETCH_TIMEOUT + 15, source=source),
    ]


EXECUTORS = {
    "read_file": read_file,
    "read_range": read_range,
    "search_symbol": search_symbol,
    "apply_patch": apply_patch,
    "write_file": write_file,
    "edit_file": edit_file,
    "multi_edit": multi_edit,
    "glob": glob_files,
    "grep": grep_search,
    "list_dir": list_dir,
    "project_scan": project_scan,
    "run_shell": run_shell,
    "git": git_tool,
    "delete_path": delete_path,
    "move_path": move_path,
    "web_scaffold": web_scaffold,
    "web_audit": web_audit,
    "reference_digest": reference_digest,
    "reference_compare": reference_compare,
    "baseline_audit": baseline_audit,
    "doc_consistency": doc_consistency,
    "web_screenshot": web_screenshot,
    "describe_image": describe_image,
    "ask_user": ask_user,
    "task": task_placeholder,
    "web_fetch": web_fetch,
}


def register_dev_tools(registry, source: str = "coding") -> None:
    for spec in tool_specs(source):
        handler = EXECUTORS.get(spec.name)
        if handler is None:
            continue
        registry.register(spec, handler)
