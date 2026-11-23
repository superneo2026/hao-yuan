"""Deliverable completeness checks.

A run may only be marked ``done`` once the requested artifact is *complete*.
"Exists" is not enough: one observed run wrote an HTML page with 1 of 12
planned sections, 11 dead navigation anchors and no closing tag, and was still
reported as "deliverable created" because a file with a fresh mtime existed.
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from typing import Any

HTML_EXTS = (".html", ".htm")
MD_EXTS = (".md", ".markdown")
# Files that are scratch for the agent's own arithmetic, never the deliverable.
_TEMP_NAME_RE = re.compile(
    r"(^|[\\/])(\.?tmp[_-]?|_tmp[_-]?|~\$|\.~|\.swp$)|\.tmp$|\.swp$|\.pyc$|\.log$|\.bak$|\.orig$|\.rej$|\.part$",
    re.I,
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})


def is_temp_file(name: str) -> bool:
    return bool(_TEMP_NAME_RE.search(name or ""))


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.stack: list[tuple[str, int]] = []
        self.errors: list[str] = []
        self.ids: dict[str, int] = {}
        self.anchors: list[str] = []
        self.visible: list[str] = []
        self._skip = 0

    def _note(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: (value or "") for key, value in attrs}
        if data.get("id"):
            self.ids[data["id"]] = self.ids.get(data["id"], 0) + 1
        if tag == "a" and data.get("href", "").startswith("#") and len(data["href"]) > 1:
            self.anchors.append(data["href"][1:])
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag not in _VOID_TAGS and tag not in _SKIP_TAGS:
            self.stack.append((tag, self.getpos()[0]))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._note(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID_TAGS or tag in _SKIP_TAGS:
            data = {key: (value or "") for key, value in attrs}
            if data.get("id"):
                self.ids[data["id"]] = self.ids.get(data["id"], 0) + 1
            return
        self._note(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_TAGS:
            return
        if tag in _SKIP_TAGS:
            # <style>/<script> are tracked by a counter, never pushed on the stack.
            if self._skip:
                self._skip -= 1
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
            return
        names = [name for name, _line in self.stack]
        if tag in names:
            while self.stack and self.stack[-1][0] != tag:
                name, line = self.stack.pop()
                self.errors.append(f"<{name}> opened at line {line} never closed")
            if self.stack:
                self.stack.pop()
            return
        self.errors.append(f"stray </{tag}> at line {self.getpos()[0]}")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.visible.append(data.strip())


def html_report(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError as exc:
        return {"error": f"cannot read {path}: {exc}"}
    parser = _PageParser()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as exc:  # HTMLParser is lenient, but never let a check crash the run
        return {"error": f"parse failed: {type(exc).__name__}: {exc}"}
    unclosed = [f"<{name}> opened at line {line} never closed" for name, line in parser.stack if name != "html"]
    anchors = list(dict.fromkeys(parser.anchors))
    dead = [anchor for anchor in anchors if anchor not in parser.ids]
    return {
        "bytes": len(raw.encode("utf-8", errors="replace")),
        "line_count": raw.count("\n") + 1,
        "visible_chars": len(" ".join(parser.visible)),
        "nav_anchors": len(anchors),
        "resolved_anchors": len(anchors) - len(dead),
        "dead_anchors": dead,
        "duplicate_ids": sorted(key for key, count in parser.ids.items() if count > 1),
        "mismatches": (parser.errors + unclosed)[:12],
        "mismatch_count": len(parser.errors) + len(unclosed),
        # A document cut off by the output limit has no closing tag at the end.
        "closed": "</html>" in raw[-4000:].lower(),
    }


def _markdown_visible(raw: str) -> int:
    text = re.sub(r"```.*?```", " ", raw, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[#>*_`|\-\[\]()]", " ", text)
    return len(" ".join(text.split()))


def markdown_report(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            raw = handle.read()
    except OSError as exc:
        return {"error": f"cannot read {path}: {exc}"}
    return {
        "bytes": len(raw.encode("utf-8", errors="replace")),
        "line_count": raw.count("\n") + 1,
        "visible_chars": _markdown_visible(raw),
        "closed": raw.count("```") % 2 == 0,
        "mismatches": [] if raw.count("```") % 2 == 0 else ["unclosed code fence"],
    }


# Directories that never contain the deliverable and can be enormous.
_SKIP_DIRS = {
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "env1",
    "site-packages", "dist", "build", "out", "target", ".idea", ".vscode", ".next",
    ".nuxt", ".gradle", ".cache", ".pytest_cache", ".mypy_cache", ".tox", "vendor",
    "coverage", ".sass-cache", "bower_components", ".haoyuan",
}
_MAX_WALK_FILES = 4000
_MAX_WALK_DEPTH = 4


def deliverable_files(target: str) -> list[str]:
    """Concrete files that make up the deliverable behind an output target.

    A directory target resolves to its index page first, then any document,
    then the most recent non-temporary file. Scratch files never count. The walk
    is bounded so a target that happens to be a large repository stays cheap.
    """
    if os.path.isfile(target):
        return [target]
    if not os.path.isdir(target):
        return []
    base_depth = target.rstrip("\\/").count(os.sep)
    candidates: list[tuple[int, int, str]] = []
    seen = 0
    for root, dirs, files in os.walk(target):
        dirs[:] = [
            name for name in dirs
            if name.lower() not in _SKIP_DIRS and not name.startswith(".")
        ]
        if root.rstrip("\\/").count(os.sep) - base_depth >= _MAX_WALK_DEPTH:
            dirs[:] = []
        for name in files:
            if is_temp_file(name) or name.startswith("."):
                continue
            seen += 1
            if seen > _MAX_WALK_FILES:
                break
            full = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            if name.lower() in ("index.html", "index.htm"):
                rank = 0
            elif ext in HTML_EXTS:
                rank = 1
            elif ext in MD_EXTS:
                rank = 2
            else:
                rank = 3
            try:
                mtime = int(os.path.getmtime(full))
            except OSError:
                mtime = 0
            candidates.append((rank, -mtime, full))
        if seen > _MAX_WALK_FILES:
            break
    candidates.sort()
    return [item[2] for item in candidates]


def main_document(files: list[str]) -> list[str]:
    """Pick the newest document among ``files`` (falls back to the first file).

    A directory target may contain stale earlier drafts; only the newest html/md
    document is the deliverable to validate.
    """
    if not files:
        return []
    documents = [item for item in files if os.path.splitext(item)[1].lower() in HTML_EXTS + MD_EXTS]
    pool = documents or files
    newest = max(pool, key=lambda item: os.path.getmtime(item) if os.path.exists(item) else 0)
    return [newest]


def completeness_issues(
    path: str,
    reference_paths: list[str] | tuple[str, ...] = (),
    min_visible_chars: int = 2000,
    min_reference_ratio: float = 0.5,
) -> list[str]:
    """Human-readable reasons the deliverable is not finished (empty = complete)."""
    ext = os.path.splitext(path)[1].lower()
    issues: list[str] = []
    if ext in HTML_EXTS:
        report = html_report(path)
        if report.get("error"):
            return [report["error"]]
        if not report["closed"]:
            issues.append("the document has no closing </html>: it was cut off, continue appending from the end")
        if report["dead_anchors"]:
            listed = ", ".join(f"#{anchor}" for anchor in report["dead_anchors"][:10])
            more = f" (+{len(report['dead_anchors']) - 10} more)" if len(report["dead_anchors"]) > 10 else ""
            issues.append(f"{len(report['dead_anchors'])} navigation anchor(s) point at sections that do not exist: {listed}{more}")
        if report["mismatches"]:
            issues.append(f"{report['mismatch_count']} tag mismatch(es): " + "; ".join(report["mismatches"][:3]))
        if report["duplicate_ids"]:
            issues.append("duplicate ids: " + ", ".join(report["duplicate_ids"][:5]))
        reference_visible = 0
        for ref in reference_paths:
            if os.path.splitext(ref)[1].lower() in HTML_EXTS and os.path.isfile(ref):
                reference_visible = max(reference_visible, int(html_report(ref).get("visible_chars") or 0))
        floor = max(min_visible_chars, int(reference_visible * min_reference_ratio)) if reference_visible else min_visible_chars
        if report["visible_chars"] < floor:
            detail = f" (reference has {reference_visible})" if reference_visible else ""
            issues.append(
                f"only {report['visible_chars']} visible characters, at least {floor} required{detail}: the body sections are missing"
            )
    elif ext in MD_EXTS:
        report = markdown_report(path)
        if report.get("error"):
            return [report["error"]]
        if report["mismatches"]:
            issues.append("unclosed code fence at the end of the file")
        if report["visible_chars"] < min(1000, min_visible_chars):
            issues.append(f"only {report['visible_chars']} visible characters: the body is missing")
    return issues
