from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


class WorkspaceError(Exception):
    pass


class SafeWorkspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative_path: str | None) -> Path:
        raw = (relative_path or ".").strip()
        candidate = Path(raw)
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            target = (self.root / candidate).resolve()
        if target != self.root and self.root not in target.parents:
            raise WorkspaceError(f"path escapes workspace: {relative_path}")
        return target

    def relative(self, target: Path) -> str:
        try:
            rel = target.resolve().relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(f"path outside workspace: {target}") from exc
        return str(rel).replace("\\", "/") or "."

    def read_text(self, relative_path: str, max_chars: int = 200_000) -> str:
        target = self.resolve(relative_path)
        if not target.exists():
            raise WorkspaceError(f"file not found: {relative_path}")
        if not target.is_file():
            raise WorkspaceError(f"not a file: {relative_path}")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > max_chars:
            return text[:max_chars] + f"\n... [truncated, original {len(text)} chars]"
        return text

    def write_text(self, relative_path: str, content: str) -> Path:
        target = self.resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_", suffix=".swp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return target

    def delete(self, relative_path: str, recursive: bool = False) -> str:
        import shutil

        target = self.resolve(relative_path)
        if target == self.root:
            raise WorkspaceError("refusing to delete workspace root")
        if target.is_dir():
            if recursive:
                shutil.rmtree(target)
                return f"deleted directory {relative_path}"
            target.rmdir()
            return f"deleted empty directory {relative_path}"
        if target.is_file():
            target.unlink()
            return f"deleted file {relative_path}"
        raise WorkspaceError(f"path not found: {relative_path}")

    def move(self, src: str, dst: str) -> str:
        import shutil

        source = self.resolve(src)
        target = self.resolve(dst)
        if not source.exists():
            raise WorkspaceError(f"source not found: {src}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return f"moved {src} -> {dst}"

    def list_dir(self, relative_path: str | None = None) -> list[dict[str, Any]]:
        target = self.resolve(relative_path)
        if not target.exists():
            raise WorkspaceError(f"directory not found: {relative_path or '.'}")
        if not target.is_dir():
            raise WorkspaceError(f"not a directory: {relative_path or '.'}")
        items = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            try:
                stat = child.stat()
            except OSError:
                continue
            items.append(
                {
                    "name": child.name,
                    "path": self.relative(child),
                    "type": "dir" if child.is_dir() else "file",
                    "size": stat.st_size if child.is_file() else 0,
                    "mtime": int(stat.st_mtime),
                }
            )
        return items

    def tree(self, max_entries: int = 2000, max_depth: int = 8) -> list[dict[str, Any]]:
        skip = {
            ".git", "node_modules", "__pycache__", ".venv", "venv", "env1", "dist", "build",
            ".pytest_cache", ".idea", ".vscode", ".next", ".cache",
        }
        out: list[dict[str, Any]] = []
        root_depth = len(self.root.parts)

        def walk(directory: Path) -> None:
            if len(out) >= max_entries:
                return
            try:
                children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for child in children:
                if len(out) >= max_entries:
                    return
                if child.name in skip:
                    continue
                depth = len(child.parts) - root_depth
                if depth > max_depth:
                    continue
                try:
                    stat = child.stat()
                except OSError:
                    continue
                item = {
                    "name": child.name,
                    "path": self.relative(child),
                    "type": "dir" if child.is_dir() else "file",
                    "size": stat.st_size if child.is_file() else 0,
                    "mtime": int(stat.st_mtime),
                }
                out.append(item)
                if child.is_dir():
                    walk(child)

        walk(self.root)
        return out
