from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from core.storage import Storage


def _file_fingerprint(workspace: str, path: str) -> str:
    try:
        full = path if os.path.isabs(path) else os.path.join(workspace, path)
        stat = os.stat(full)
        return f"{int(stat.st_mtime)}:{stat.st_size}"
    except OSError:
        return "missing"


def effect_key(session_id: str, tool: str, args: dict[str, Any], workspace: str = "") -> str:
    path = str(args.get("path") or args.get("src") or "")
    fingerprint = _file_fingerprint(workspace, path) if path else ""
    raw = json.dumps(
        {"session": session_id, "tool": tool, "args": args, "file": fingerprint},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


async def load_effects(storage: Storage, session_id: str) -> dict[str, str]:
    return await storage.get_effects(session_id)


async def record_effect(
    storage: Storage,
    session_id: str,
    step: int,
    tool: str,
    args: dict[str, Any],
    result: str,
    workspace: str = "",
) -> None:
    key = effect_key(session_id, tool, args, workspace)
    await storage.save_effect(key, session_id, step, tool, result)


async def save_checkpoint(
    storage: Storage,
    session_id: str,
    step: int,
    run_id: str,
    cursor: int,
    plan: str,
    note: str = "",
) -> None:
    await storage.save_checkpoint(session_id, step, run_id, cursor, plan, note)


async def latest_checkpoint(storage: Storage, session_id: str) -> dict[str, Any] | None:
    return await storage.latest_checkpoint(session_id)


async def clear_checkpoints(storage: Storage, session_id: str) -> None:
    await storage.clear_checkpoints(session_id)
