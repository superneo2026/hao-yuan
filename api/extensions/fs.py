from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from configs.configs import prefix
from core.harness import get_harness
from extensions.common import fail, ok
from harness.sandbox import SafeWorkspace, WorkspaceError

router = APIRouter(prefix=prefix, tags=["files"])

MAX_DIRS = 800
LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".vue": "vue",
    ".html": "html", ".css": "css", ".scss": "scss", ".json": "json", ".md": "markdown",
    ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".sh": "bash", ".bat": "bat",
    ".ps1": "powershell", ".sql": "sql", ".go": "go", ".rs": "rust", ".java": "java",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".xml": "xml",
}


def _workspace(path: str) -> SafeWorkspace:
    if not path or not os.path.isdir(path):
        raise WorkspaceError(f"workspace does not exist: {path}")
    return SafeWorkspace(path)


def _drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    return [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{letter}:\\")]


def _git(workspace: str, args: list[str], timeout: int = 20) -> tuple[int, str, str]:
    try:
        process = subprocess.run(
            ["git"] + args,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return process.returncode, process.stdout, process.stderr
    except Exception as exc:
        return 1, "", str(exc)


@router.get("/fs/list")
async def fs_list(path: str = ""):
    try:
        if not path:
            return ok({"path": "", "parent": "", "dirs": _drives()})
        if len(path) == 2 and path[1] == ":":
            path += "\\"
        real = os.path.realpath(path)
        if not os.path.isdir(real):
            return fail(f"directory does not exist: {path}")
        dirs = []
        for name in sorted(os.listdir(real), key=str.lower):
            full = os.path.join(real, name)
            if not os.path.isdir(full) or name.startswith((".", "$")):
                continue
            dirs.append(full)
            if len(dirs) >= MAX_DIRS:
                break
        parent = os.path.dirname(real) if len(real) > 3 else ""
        return ok({"path": real, "parent": parent, "dirs": dirs})
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")


@router.get("/workspace/tree")
async def workspace_tree(workspace: str, max_entries: int = 2500):
    try:
        safe = _workspace(workspace)
        return ok({"workspace": str(safe.root), "items": safe.tree(max_entries=max_entries)})
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")


@router.get("/workspace/file")
async def workspace_file(workspace: str, path: str):
    try:
        safe = _workspace(workspace)
        target = safe.resolve(path)
        if not target.is_file():
            return fail(f"file not found: {path}", 404)
        raw = target.read_bytes()
        if b"\x00" in raw[:4000]:
            return fail("binary file preview is not supported", 415)
        text = raw.decode("utf-8", errors="replace")
        if len(text) > 600_000:
            text = text[:600_000] + "\n... [preview truncated]"
        return ok(
            {
                "path": safe.relative(target),
                "content": text,
                "language": LANG_BY_EXT.get(target.suffix.lower(), "text"),
                "size": target.stat().st_size,
                "lines": text.count("\n") + 1,
                "mtime": int(target.stat().st_mtime),
            }
        )
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")


@router.get("/workspace/changes")
async def workspace_changes(workspace: str):
    try:
        safe = _workspace(workspace)
        code, out, _ = _git(str(safe.root), ["status", "--porcelain"])
        changes = []
        if code == 0:
            for line in out.splitlines():
                if not line.strip():
                    continue
                status = line[:2].strip() or "?"
                path = line[3:].strip()
                if " -> " in path:
                    path = path.split(" -> ", 1)[1]
                changes.append({"status": status, "path": path.replace("\\", "/")})
        else:
            now = __import__("time").time()
            for item in safe.tree(max_entries=4000):
                if item["type"] != "file":
                    continue
                if now - item.get("mtime", 0) < 86400:
                    changes.append({"status": "M", "path": item["path"]})
            changes = changes[:200]
        return ok(changes)
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")


@router.get("/workspace/diff")
async def workspace_diff(workspace: str, path: str = ""):
    try:
        safe = _workspace(workspace)
        args = ["diff", "--no-color"]
        if path:
            safe.resolve(path)
            args += ["--", path]
        code, out, err = _git(str(safe.root), args)
        if code == 0 and out.strip():
            return ok({"path": path, "diff": out, "source": "git"})
        if path:
            target = safe.resolve(path)
            if target.is_file():
                text = target.read_text(encoding="utf-8", errors="replace")
                diff = "\n".join(f"+{line}" for line in text.splitlines())
                return ok({"path": path, "diff": f"--- /dev/null\n+++ b/{path}\n" + diff, "source": "file"})
        return ok({"path": path, "diff": out or "", "source": "git", "error": err[:400]})
    except Exception as exc:
        return fail(f"{type(exc).__name__}: {exc}")


@router.get("/artifacts/{artifact_id}/file")
async def artifact_file(artifact_id: str, download: bool = False):
    harness = await get_harness()
    artifact = await harness.storage._one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
    if not artifact:
        return fail("artifact not found", 404)
    path = artifact.get("path") or ""
    if not os.path.isfile(path):
        return fail("artifact file is missing on disk", 404)
    filename = os.path.basename(path)
    headers = {
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{filename}"',
        "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:;",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(path, filename=filename, headers=headers)
