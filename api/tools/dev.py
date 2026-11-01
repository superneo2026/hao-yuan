from __future__ import annotations

import difflib
import glob as globlib
import json
import locale
import os
import re
import subprocess
import time
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
)
from core.contracts import ToolContext, ToolSpec
from harness import reference as reference_analysis
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


def read_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    offset = max(int(args.get("offset") or 1), 1)
    limit = int(args.get("limit") or 400)
    segment = lines[offset - 1 : offset - 1 + limit]
    body = "".join(f"{index + offset}: {line}" for index, line in enumerate(segment))
    head = f"{args.get('path')} ({len(lines)} lines)"
    return _truncate(f"{head}\n{body}" if body else f"{head} is empty")


def read_range(ctx: ToolContext, args: dict[str, Any]) -> str:
    workspace = _workspace(ctx)
    path = workspace.resolve(args.get("path", ""))
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {args.get('path')}")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    start = max(int(args.get("start") or 1), 1)
    end = int(args.get("end") or (start + 119))
    if end < start:
        start, end = end, start
    segment = lines[start - 1 : end]
    body = "".join(f"{index + start}: {line}" for index, line in enumerate(segment))
    head = f"{args.get('path')} (range {start}-{min(end, len(lines))} / {len(lines)} lines)"
    return _truncate(f"{head}\n{body}" if body else f"{head} (empty range)")


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
    "ask_user": ask_user,
}


def register_dev_tools(registry, source: str = "coding") -> None:
    for spec in tool_specs(source):
        handler = EXECUTORS.get(spec.name)
        if handler is None:
            continue
        registry.register(spec, handler)
