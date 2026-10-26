from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime
from typing import Any

from configs.configs import (
    ORCH_BLACKBOARD_FILE,
    ORCH_BRANCH_PREFIX,
    ORCH_CONTRACT_FILE,
    ORCH_ISOLATION,
    ORCH_MAX_PARALLEL,
    ORCH_MAX_TASKS,
    ORCH_PORT_BASE,
    ORCH_PORT_STRIDE,
    ORCH_WORKTREE_DIR,
)
from configs.models import resolve


def _run(repo: str, args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    try:
        process = subprocess.run(args, cwd=repo, capture_output=True, text=True, timeout=timeout)
        return process.returncode, process.stdout, process.stderr
    except Exception as exc:
        return 1, "", str(exc)


def ensure_repo(workspace: str) -> tuple[bool, str]:
    code, out, _ = _run(workspace, ["git", "rev-parse", "--is-inside-work-tree"])
    if code != 0 or "true" not in out:
        return False, "workspace is not a git repository"
    code, out, _ = _run(workspace, ["git", "rev-parse", "HEAD"])
    if code != 0:
        return False, "repository has no commits; create an initial commit first"
    return True, "ok"


def current_branch(repo: str) -> str:
    code, out, _ = _run(repo, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if code == 0 else ""


def create_worktree(repo: str, task_id: str, base_branch: str) -> tuple[bool, str, str, str]:
    path = os.path.join(repo, ORCH_WORKTREE_DIR, task_id)
    branch = f"{ORCH_BRANCH_PREFIX}{task_id}"
    if os.path.isdir(path):
        return True, path, branch, "reused"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    code, _, err = _run(repo, ["git", "worktree", "add", "-b", branch, path, base_branch], timeout=120)
    if code != 0:
        return False, "", "", err[:500]
    return True, path, branch, "created"


def merge_branch(repo: str, task_id: str, message: str) -> tuple[bool, str]:
    branch = f"{ORCH_BRANCH_PREFIX}{task_id}"
    code, _, err = _run(repo, ["git", "merge", "--no-ff", branch, "-m", message], timeout=120)
    if code != 0:
        _run(repo, ["git", "merge", "--abort"])
        return False, err[:800]
    return True, "merged"


class PortAllocator:
    def __init__(self, base: int = ORCH_PORT_BASE, stride: int = ORCH_PORT_STRIDE):
        self.base = base
        self.stride = stride
        self.index = 0

    def allocate(self, task_id: str) -> list[int]:
        start = self.base + self.index * self.stride
        self.index += 1
        return list(range(start, start + self.stride))


async def decompose(harness, goal: str, provider: str, model: str) -> tuple[list[dict[str, Any]], str]:
    prompt = (
        "Break the goal below into 2-6 independent engineering tasks for parallel AI workers. "
        "Return ONLY a JSON array. Each item: {\"id\":\"t1\",\"role\":\"backend|frontend|test|docs\","
        "\"title\":\"...\",\"instruction\":\"self-contained instruction with acceptance criteria\","
        "\"depends_on\":[\"t0\"]}. Keep dependencies minimal.\n\nGoal:\n" + goal
    )
    try:
        text = await harness.gateway.complete_text(
            provider,
            model,
            [
                {"role": "system", "content": "You are a technical lead who decomposes work into parallel tasks."},
                {"role": "user", "content": prompt},
            ],
            thinking="off",
        )
        start = text.find("[")
        end = text.rfind("]")
        if start >= 0 and end > start:
            data = json.loads(text[start : end + 1])
            tasks = []
            for index, item in enumerate(data[:ORCH_MAX_TASKS], 1):
                tasks.append(
                    {
                        "id": str(item.get("id") or f"t{index}"),
                        "role": str(item.get("role") or "backend"),
                        "title": str(item.get("title") or f"Task {index}"),
                        "instruction": str(item.get("instruction") or ""),
                        "depends_on": list(item.get("depends_on") or []),
                    }
                )
            if tasks:
                return tasks, "llm"
    except Exception:
        pass
    return (
        [
            {
                "id": "t1",
                "role": "backend",
                "title": "Backend implementation",
                "instruction": f"Implement the backend portion of the goal.\n\nGoal:\n{goal}\n\nAdd tests where practical.",
                "depends_on": [],
            },
            {
                "id": "t2",
                "role": "frontend",
                "title": "Frontend implementation",
                "instruction": f"Implement the frontend portion of the goal.\n\nGoal:\n{goal}\n\nFollow the shared contract and verify the build.",
                "depends_on": [],
            },
            {
                "id": "t3",
                "role": "test",
                "title": "Integration verification",
                "instruction": f"Verify the integrated implementation against the goal, run the test suite, and fix integration issues.\n\nGoal:\n{goal}",
                "depends_on": ["t1", "t2"],
            },
        ],
        "heuristic",
    )


def _write_contract(repo: str, goal: str, tasks: list[dict[str, Any]]) -> str:
    lines = ["# Contract", "", f"Goal: {goal}", "", "## Responsibilities"]
    for task in tasks:
        lines.append(f"- `{task['id']}` ({task['role']}): {task['title']}")
    lines += ["", "## Rules", "- Respect existing interfaces; keep changes backward compatible.", "- Record decisions in the blackboard."]
    text = "\n".join(lines) + "\n"
    path = os.path.join(repo, ORCH_CONTRACT_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return text


def _write_blackboard(repo: str, goal: str, branch: str) -> None:
    path = os.path.join(repo, ORCH_BLACKBOARD_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"# Blackboard\n\nGoal: {goal}\nBase branch: {branch}\n\n")


def append_blackboard(repo: str, line: str) -> None:
    path = os.path.join(repo, ORCH_BLACKBOARD_FILE)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"- [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")
    except OSError:
        pass


async def create_orchestration(
    harness,
    goal: str,
    workspace: str,
    provider: str = "",
    model: str = "",
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("goal is required")
    workspace = (workspace or "").strip()
    if not workspace or not os.path.isdir(workspace):
        raise ValueError(f"workspace does not exist: {workspace}")
    ok, message = ensure_repo(workspace)
    if not ok:
        raise RuntimeError(message)
    base_branch = current_branch(workspace)
    provider, model = resolve(provider, model)
    source = "manual"
    if not tasks:
        tasks, source = await decompose(harness, goal, provider, model)
    tasks = tasks[:ORCH_MAX_TASKS]
    contract = _write_contract(workspace, goal, tasks)
    _write_blackboard(workspace, goal, base_branch)
    orch = await harness.storage.create_orchestration(goal, workspace, contract)
    oid = orch["id"]
    allocator = PortAllocator()
    for index, task in enumerate(tasks):
        task_id = str(task.get("id") or f"t{index + 1}")
        ports = allocator.allocate(task_id)
        worktree_path, branch = "", ""
        if ORCH_ISOLATION == "worktree":
            created, path, branch_name, _ = create_worktree(workspace, task_id, base_branch)
            if created:
                worktree_path, branch = path, branch_name
        worker_workspace = worktree_path or workspace
        session = await harness.manager.create_session(
            kind="dev",
            title=f"[{task.get('role', 'worker')}] {task.get('title', task_id)}",
            provider=provider,
            model=model,
            workspace=worker_workspace,
            meta={"orchestration_id": oid, "orchestration_task": task_id},
        )
        await harness.storage.update_session(session["id"], orch_id=oid, orch_role=str(task.get("role") or ""))
        await harness.storage.add_orch_task(
            {
                "id": task_id,
                "orch_id": oid,
                "seq": index,
                "role": task.get("role", ""),
                "title": task.get("title", task_id),
                "instruction": task.get("instruction", ""),
                "depends_on": task.get("depends_on") or [],
                "session_id": session["id"],
                "worktree": worktree_path,
                "branch": branch,
                "ports": ports,
                "status": "pending",
            }
        )
    await harness.storage.update_orchestration(oid, status="running")
    await harness.events.emit(oid, "orchestration.created", {"goal": goal, "source": source, "tasks": [t["id"] for t in tasks]})
    await advance(harness, oid)
    return await get_orchestration(harness, oid)


async def get_orchestration(harness, oid: str) -> dict[str, Any] | None:
    orch = await harness.storage.get_orchestration(oid)
    if not orch:
        return None
    orch["tasks"] = await harness.storage.list_orch_tasks(oid)
    return orch


async def list_orchestrations(harness) -> list[dict[str, Any]]:
    return await harness.storage.list_orchestrations()


async def ready_task_ids(harness, oid: str) -> list[str]:
    tasks = await harness.storage.list_orch_tasks(oid)
    done = {task["id"] for task in tasks if task["status"] in ("done", "skipped")}
    ready = []
    for task in tasks:
        if task["status"] != "pending":
            continue
        if set(task.get("depends_on") or []) <= done:
            ready.append(task["id"])
    return ready


async def advance(harness, oid: str, dispatch: bool = True) -> dict[str, Any]:
    orch = await harness.storage.get_orchestration(oid)
    if not orch:
        return {"scheduled": [], "status": "not_found"}
    tasks = await harness.storage.list_orch_tasks(oid)
    if tasks and all(task["status"] in ("done", "skipped", "error") for task in tasks):
        merged = await merge_all(harness, oid)
        return {"scheduled": [], "status": "done" if merged else "error"}
    running = sum(1 for task in tasks if task["status"] in ("running", "ready"))
    capacity = max(0, ORCH_MAX_PARALLEL - running)
    ready = await ready_task_ids(harness, oid)
    scheduled = ready[:capacity]
    for task_id in scheduled:
        await harness.storage.update_orch_task(task_id, status="ready")
        if dispatch:
            await _dispatch(harness, oid, task_id)
    return {"scheduled": scheduled, "status": "running"}


async def _dispatch(harness, oid: str, task_id: str) -> None:
    tasks = await harness.storage.list_orch_tasks(oid)
    task = next((item for item in tasks if item["id"] == task_id), None)
    if not task or not task.get("session_id"):
        return
    await harness.storage.update_orch_task(task_id, status="running")
    header = (
        f"[Orchestration {oid} | task {task_id} | role {task['role']}]\n"
        f"Isolated workspace: {task.get('worktree') or '(shared)'}\n"
        f"Suggested ports: {task.get('ports')}\n"
        f"Contract: {ORCH_CONTRACT_FILE}; blackboard: {ORCH_BLACKBOARD_FILE}\n\n"
    )
    await harness.storage.add_message(
        task["session_id"], "", "user", header + (task.get("instruction") or "")
    )
    await harness.events.emit(
        task["session_id"],
        "message.saved",
        {"role": "user", "content": header + (task.get("instruction") or ""), "source": "orchestrator"},
    )
    await harness.events.emit(oid, "orchestration.task.started", {"task_id": task_id, "role": task["role"]})
    harness.manager.enqueue(task["session_id"])


async def mark_task(harness, oid: str, task_id: str, status: str, result: str = "") -> None:
    await harness.storage.update_orch_task(task_id, status=status, result=(result or "")[:4000])
    await harness.events.emit(oid, "orchestration.task." + status, {"task_id": task_id})
    await advance(harness, oid)


async def merge_all(harness, oid: str) -> bool:
    orch = await harness.storage.get_orchestration(oid)
    if not orch:
        return False
    await harness.storage.update_orchestration(oid, status="merging")
    tasks = await harness.storage.list_orch_tasks(oid)
    conflicts = []
    for task in tasks:
        if task["role"] == "chief" or not task.get("branch") or task["status"] != "done":
            continue
        ok, message = merge_branch(orch["workspace"], task["id"], f"merge {task['id']} ({task['title']})")
        append_blackboard(orch["workspace"], f"merge {task['id']}: {'ok' if ok else message}")
        if not ok:
            conflicts.append(task["id"])
    metrics = {
        "tasks": len(tasks),
        "done": sum(1 for task in tasks if task["status"] == "done"),
        "error": sum(1 for task in tasks if task["status"] == "error"),
        "conflicts": len(conflicts),
        "parallelism": ORCH_MAX_PARALLEL,
    }
    await harness.storage.update_orchestration(oid, metrics=json.dumps(metrics, ensure_ascii=False))
    success = not conflicts and all(task["status"] in ("done", "skipped") for task in tasks)
    await harness.storage.update_orchestration(
        oid, status="done" if success else "error", error="" if success else f"merge conflicts: {conflicts}"
    )
    await harness.events.emit(oid, "orchestration.done", {"metrics": metrics, "conflicts": conflicts})
    return success


async def on_session_event(harness, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
    if event_type not in ("done", "error"):
        return
    rows = await harness.storage._fetch(
        "SELECT id, orch_id FROM orchestration_tasks WHERE session_id=? LIMIT 1", (session_id,)
    )
    if not rows:
        return
    task = rows[0]
    if not task.get("orch_id"):
        return
    status = "done" if event_type == "done" else "error"
    text = (payload or {}).get("text") or (payload or {}).get("message") or ""
    await mark_task(harness, task["orch_id"], task["id"], status, str(text)[:2000])
