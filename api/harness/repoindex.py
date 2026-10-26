from __future__ import annotations

import ast
import os
import re
import time

from configs.configs import (
    REPO_INDEX_CODE_EXTS,
    REPO_INDEX_MAX_FILES,
    REPO_INDEX_TIME_BUDGET,
    REPO_MAP_MAX_TOKENS,
    SEARCH_SKIP_DIRS,
)

_CODE_EXTS = set(REPO_INDEX_CODE_EXTS)


def _iter_code_files(base: str):
    deadline = time.monotonic() + REPO_INDEX_TIME_BUDGET
    count = 0
    for root, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in SEARCH_SKIP_DIRS)
        for name in sorted(files):
            ext = os.path.splitext(name)[1].lower()
            if ext not in _CODE_EXTS:
                continue
            count += 1
            if count > REPO_INDEX_MAX_FILES or time.monotonic() > deadline:
                return
            yield os.path.join(root, name)


def index_python(rel: str, src: str) -> list[dict]:
    out: list[dict] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    lines = src.splitlines()

    def signature(node) -> str:
        try:
            segment = lines[node.lineno - 1 : node.end_lineno or node.lineno]
            return (segment[0].strip() if segment else "")[:160]
        except (IndexError, TypeError):
            return ""

    def walk(body, prefix: str, class_name: str | None = None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if class_name else ("async_def" if isinstance(node, ast.AsyncFunctionDef) else "def")
                name = f"{class_name}.{node.name}" if class_name else f"{prefix}{node.name}"
                out.append(
                    {
                        "kind": kind,
                        "name": name,
                        "path": rel,
                        "line": node.lineno,
                        "end": node.end_lineno or node.lineno,
                        "sig": signature(node),
                    }
                )
            elif isinstance(node, ast.ClassDef):
                out.append(
                    {
                        "kind": "class",
                        "name": f"{prefix}{node.name}",
                        "path": rel,
                        "line": node.lineno,
                        "end": node.end_lineno or node.lineno,
                        "sig": f"class {node.name}",
                    }
                )
                walk(node.body, "", class_name=node.name)

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif node.module:
                names = [f"{node.module}.{alias.name}" for alias in node.names]
            out.append(
                {
                    "kind": "import",
                    "name": ", ".join(names)[:160],
                    "path": rel,
                    "line": node.lineno,
                    "end": node.lineno,
                    "sig": "",
                }
            )
    walk(tree.body, "")
    return out


_JS_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)",
    re.M,
)
_JS_CLASS_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", re.M
)
_JS_IMPORT_RE = re.compile(r"^[ \t]*(?:import|export)\s+[^;{]*?from\s+['\"]([^'\"]+)['\"]", re.M)
_JS_CONST_FUNC_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>",
    re.M,
)


def index_js(rel: str, src: str) -> list[dict]:
    out: list[dict] = []

    def line_of(pos: int) -> int:
        return src.count("\n", 0, pos) + 1

    for match in _JS_CLASS_RE.finditer(src):
        out.append(
            {
                "kind": "class",
                "name": match.group(1),
                "path": rel,
                "line": line_of(match.start()),
                "end": line_of(match.start()),
                "sig": match.group(0).strip()[:160],
            }
        )
    for match in _JS_FUNC_RE.finditer(src):
        out.append(
            {
                "kind": "def",
                "name": match.group(1),
                "path": rel,
                "line": line_of(match.start()),
                "end": line_of(match.start()),
                "sig": f"function {match.group(1)}({match.group(2).strip()[:80]})",
            }
        )
    for match in _JS_CONST_FUNC_RE.finditer(src):
        out.append(
            {
                "kind": "def",
                "name": match.group(1),
                "path": rel,
                "line": line_of(match.start()),
                "end": line_of(match.start()),
                "sig": f"const {match.group(1)} = ({match.group(2).strip()[:80]}) =>",
            }
        )
    for match in _JS_IMPORT_RE.finditer(src):
        out.append(
            {
                "kind": "import",
                "name": match.group(1),
                "path": rel,
                "line": line_of(match.start()),
                "end": line_of(match.start()),
                "sig": "",
            }
        )
    return out


def build_index(workspace: str) -> dict:
    idx: dict = {"symbols": [], "files": {}, "truncated": False}
    if not workspace or not os.path.isdir(workspace):
        return idx
    try:
        base = os.path.realpath(workspace)
        for path in _iter_code_files(base):
            rel = os.path.relpath(path, base).replace("\\", "/")
            try:
                if os.path.getsize(path) > 512 * 1024:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    src = handle.read()
            except OSError:
                continue
            ext = os.path.splitext(path)[1].lower()
            symbols = index_python(rel, src) if ext == ".py" else index_js(rel, src)
            if symbols:
                idx["symbols"].extend(symbols)
                idx["files"][rel] = len([s for s in symbols if s["kind"] != "import"])
        return idx
    except Exception:
        return {"symbols": [], "files": {}, "truncated": True}


_CACHE: dict[str, dict] = {}


def _fingerprint(workspace: str) -> tuple:
    try:
        base = os.path.realpath(workspace)
        stats = []
        for name in sorted(os.listdir(base))[:200]:
            path = os.path.join(base, name)
            try:
                stat = os.stat(path)
                stats.append((name, int(stat.st_mtime), os.path.isdir(path)))
            except OSError:
                continue
        return base, tuple(stats)
    except Exception:
        return workspace, ()


def get_index(workspace: str, fresh: bool = False) -> dict:
    fingerprint = _fingerprint(workspace)
    hit = _CACHE.get(workspace)
    if hit and not fresh and hit.get("fp") == fingerprint:
        return hit["idx"]
    idx = build_index(workspace)
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[workspace] = {"fp": fingerprint, "idx": idx}
    return idx


def search_symbols(workspace: str, query: str, kind: str = "", limit: int = 30) -> list[dict]:
    idx = get_index(workspace)
    q = (query or "").strip().lstrip(".")
    if not q:
        return []
    ql = q.lower()
    exact, prefix, sub = [], [], []
    for symbol in idx["symbols"]:
        if symbol["kind"] == "import":
            continue
        if kind and symbol["kind"] != kind:
            continue
        name = symbol["name"].lower()
        tail = name.rsplit(".", 1)[-1]
        if name == ql or tail == ql:
            exact.append(symbol)
        elif tail.startswith(ql) or name.startswith(ql):
            prefix.append(symbol)
        elif ql in name:
            sub.append(symbol)
    return (exact + prefix + sub)[: max(1, min(limit, 60))]


def rank_files(workspace: str, query: str, limit: int = 8) -> list[tuple[str, float]]:
    idx = get_index(workspace)
    q = (query or "").strip().lower()
    if not q:
        return []
    words = [w for w in re.split(r"[^a-z0-9_\u4e00-\u9fff]+", q) if len(w) >= 3]
    scores: dict[str, float] = {}
    for symbol in idx["symbols"]:
        if symbol["kind"] == "import":
            continue
        name = symbol["name"].lower()
        score = 3.0 if q in name else 0.0
        score += sum(1.0 for word in words if word in name)
        if score:
            scores[symbol["path"]] = scores.get(symbol["path"], 0.0) + score
    for rel in idx["files"]:
        lowered = rel.lower()
        score = scores.get(rel, 0.0)
        score += sum(0.8 for word in words if word in lowered)
        if score:
            scores[rel] = score
    return sorted(scores.items(), key=lambda item: -item[1])[: max(1, min(limit, 20))]


def repo_map(workspace: str, max_tokens: int | None = None) -> str:
    max_tokens = max_tokens or REPO_MAP_MAX_TOKENS
    idx = get_index(workspace)
    if not idx["symbols"] and not idx["files"]:
        return ""
    files = sorted(idx["files"])
    dirs: dict[str, list[str]] = {}
    for rel in files:
        parts = rel.split("/")
        directory = "/".join(parts[:-1]) or "."
        dirs.setdefault(directory, []).append(parts[-1])
    lines: list[str] = []
    budget = max_tokens * 4 - 200
    for directory in sorted(dirs):
        names = dirs[directory]
        head = f"{directory}/: " + " ".join(names[:24]) + (" ..." if len(names) > 24 else "")
        if budget - len(head) < 0:
            break
        lines.append(head)
        budget -= len(head) + 1
    priority = {"class": 0, "def": 1, "async_def": 1, "method": 2}
    symbols = sorted(
        (s for s in idx["symbols"] if s["kind"] in priority),
        key=lambda s: (priority[s["kind"]], s["path"], s["line"]),
    )
    if lines:
        lines.append("")
        budget -= 2
    for symbol in symbols:
        row = f"{symbol['path']}:{symbol['line']}  {symbol['sig']}"
        if budget - len(row) < 0:
            lines.append("... [repo map truncated; use search_symbol for precision]")
            break
        lines.append(row)
        budget -= len(row) + 1
    return "\n".join(lines)[: max_tokens * 4]
