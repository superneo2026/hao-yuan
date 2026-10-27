from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BENCH = Path(__file__).resolve().parent
PROJECT = BENCH.parent.parent
API_DIR = PROJECT / "api"
ENV_PY = API_DIR / "env1" / "Scripts" / "python.exe"
PY = str(ENV_PY if ENV_PY.is_file() else sys.executable)
TASKS_DIR = BENCH / "tasks"
RUNS_DIR = BENCH / "runs"
RESULTS_DIR = BENCH / "results"
CACHE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "tests_hidden", ".git"}

CLAUDE_EXE = Path(os.environ["USERPROFILE"]) / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"
OPENCODE_EXE = Path(os.environ["USERPROFILE"]) / "AppData/Roaming/npm/node_modules/opencode-ai/bin/opencode.exe"
OPENCODE_CONFIG = BENCH / "configs" / "opencode-mimo.json"
HAOYUAN_PORT = int(os.environ.get("BENCH_HAOYUAN_PORT", "8031"))

MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
MIMO_ANTHROPIC_URL = "https://token-plan-cn.xiaomimimo.com/anthropic"
MIMO_MODEL = "mimo-v2.6-flash"


def load_key() -> str:
    text = (API_DIR / "configs" / "secrets_local.py").read_text(encoding="utf-8")
    for name in ("MIMO_API_KEY", "DEEPSEEK_API_KEY"):
        match = re.search(rf'{name}\s*=\s*["\']([^"\']+)', text)
        if match:
            return match.group(1)
    raise SystemExit("MIMO_API_KEY not found in api/configs/secrets_local.py")


MIMO_KEY = load_key()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(repo: Path) -> dict[str, str]:
    out = {}
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo)
        if any(part in CACHE_DIRS for part in rel.parts):
            continue
        out[str(rel).replace("\\", "/")] = sha256(path)
    return out


def protected_snapshot(repo: Path, prefixes: list[str]) -> dict[str, str]:
    out = {}
    for prefix in prefixes:
        target = repo / prefix
        if target.is_file():
            out[prefix] = sha256(target)
        elif target.is_dir():
            for path in target.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    rel = str(path.relative_to(repo)).replace("\\", "/")
                    out[rel] = sha256(path)
    return out


def task_meta(task_id: str) -> dict:
    return json.loads((TASKS_DIR / task_id / "meta.json").read_text(encoding="utf-8-sig"))


def task_ids(selector: str) -> list[str]:
    all_ids = sorted(p.name for p in TASKS_DIR.iterdir() if p.is_dir() and (p / "meta.json").is_file())
    if selector in ("all", ""):
        return all_ids
    wanted = [item.strip() for item in selector.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in all_ids]
    if unknown:
        raise SystemExit(f"unknown tasks: {unknown}")
    return wanted


class HaoYuanServer:
    def __init__(self, batch: str) -> None:
        self.batch = batch
        self.runtime = BENCH / "runtime" / f"haoyuan-{batch}"
        self.proc: subprocess.Popen | None = None
        self.log = None
        self.port = self._free_port()

    @staticmethod
    def _free_port() -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def __enter__(self) -> "HaoYuanServer":
        shutil.rmtree(self.runtime, ignore_errors=True)
        self.runtime.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "HAOYUAN_PORT": str(self.port),
                "HAOYUAN_DATA_DIR": str(self.runtime / "data"),
                "HAOYUAN_DB_PATH": str(self.runtime / "data" / "haoyuan.db"),
                "HAOYUAN_AUTO_APPROVE": "1",
                "HAOYUAN_MAX_STEPS": os.environ.get("BENCH_HAOYUAN_MAX_STEPS", "60"),
                "HAOYUAN_SUBAGENT_MAX_STEPS": os.environ.get("BENCH_HAOYUAN_SUBAGENT_MAX_STEPS", "20"),
                "HAOYUAN_STRICT_PROVIDER": "1",
                "HAOYUAN_LLM_FIRST_CHUNK_TIMEOUT": os.environ.get("BENCH_LLM_FIRST_CHUNK_TIMEOUT", "60"),
                "HAOYUAN_LLM_STREAM_IDLE_TIMEOUT": os.environ.get("BENCH_LLM_STREAM_IDLE_TIMEOUT", "45"),
                "HAOYUAN_LLM_TOTAL_TIMEOUT": os.environ.get("BENCH_LLM_TOTAL_TIMEOUT", "240"),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
            }
        )
        self.log = (self.runtime / "server.log").open("w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [PY, "main.py"],
            cwd=API_DIR,
            env=env,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"HaoYuan server exited early; see {self.runtime / 'server.log'}")
            try:
                self.call("GET", "/api/health", timeout=2)
                return self
            except Exception:
                time.sleep(0.5)
        raise RuntimeError("HaoYuan server did not become ready in 90s")

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
        if self.log:
            self.log.close()

    def call(self, method: str, path: str, payload: dict | None = None, timeout: float = 30):
        if self.proc and self.proc.poll() is not None:
            raise RuntimeError("HaoYuan server exited unexpectedly")
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        if body.get("code") != 200:
            raise RuntimeError(f"{path} failed: {body}")
        return body.get("data")


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def run_process(cmd: list[str], cwd: Path, env: dict, timeout: int) -> dict:
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        stdout, stderr = proc.communicate()
    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "duration_sec": round(time.monotonic() - started, 2),
    }


def run_haoyuan(server: HaoYuanServer, repo: Path, prompt: str, budget: int) -> dict:
    session = server.call(
        "POST",
        "/api/sessions",
        {
            "kind": "dev",
            "title": f"bench-{repo.parent.name}",
            "provider": "mimo",
            "model": MIMO_MODEL,
            "workspace": str(repo),
            "gate_mode": "allow_all",
        },
    )
    session_id = session["id"]
    started = time.monotonic()
    server.call("POST", f"/api/sessions/{session_id}/messages", {"content": prompt})
    cursor = 0
    tool_calls = 0
    tool_names: dict[str, int] = {}
    verify_cmds: list[str] = []
    errors: list[str] = []
    timed_out = False
    status = "unknown"
    last_payload: dict = {}
    events_seen = 0
    route: dict = {}
    fallbacks: list[str] = []
    verify_nudges = 0
    while True:
        elapsed = time.monotonic() - started
        if elapsed > budget:
            timed_out = True
            try:
                server.call("POST", f"/api/sessions/{session_id}/cancel", {})
            except Exception:
                pass
            status = "timeout"
            break
        try:
            data = server.call("GET", f"/api/sessions/{session_id}", timeout=15)
            session_row = data["session"]
            events = server.call("GET", f"/api/sessions/{session_id}/events?after_id={cursor}", timeout=15)
        except Exception as exc:
            errors.append(f"poll error: {exc}")
            time.sleep(1)
            continue
        for event in events:
            cursor = max(cursor, int(event.get("id") or 0))
            events_seen += 1
            etype = event.get("type")
            payload = event.get("payload") or {}
            if etype == "tool.start":
                tool_calls += 1
                name = str(payload.get("tool") or "")
                tool_names[name] = tool_names.get(name, 0) + 1
                command = str((payload.get("args") or {}).get("command") or "")
                if command and ("pytest" in command or "unittest" in command or "npm test" in command):
                    verify_cmds.append(command[:300])
            elif etype == "error":
                errors.append(str(payload.get("message") or "error")[:300])
            elif etype == "route":
                route = payload
            elif etype == "model.fallback":
                fallbacks.extend(payload.get("fallbacks") or [])
            elif etype == "verify.nudge":
                verify_nudges += 1
            elif etype == "done":
                last_payload = payload
        status = str(session_row.get("status") or status)
        if status in ("done", "error") and not server.call("GET", f"/api/sessions/{session_id}/pending", timeout=10):
            break
        time.sleep(1)
    elapsed = round(time.monotonic() - started, 2)
    try:
        final = server.call("GET", f"/api/sessions/{session_id}", timeout=15)
        session_row = final["session"]
        runs = final.get("runs") or []
    except Exception:
        session_row = {}
        runs = []
    return {
        "exit_code": 0 if status == "done" else (124 if timed_out else 1),
        "timed_out": timed_out,
        "status": status,
        "duration_sec": elapsed,
        "prompt_tokens": int(float(session_row.get("total_prompt") or 0)),
        "completion_tokens": int(float(session_row.get("total_completion") or 0)),
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "steps": int((runs[0].get("step_count") if runs else 0) or 0),
        "verify_cmds": verify_cmds,
        "errors": errors,
        "final_text": str(last_payload.get("text") or (runs[0].get("output") if runs else "") or "")[:4000],
        "events": events_seen,
        "session_id": session_id,
        "route": route,
        "fallbacks": fallbacks,
        "verify_nudges": verify_nudges,
    }


def run_claude(repo: Path, prompt: str, budget: int) -> dict:
    env = os.environ.copy()
    env.update(
        {
            "CLAUDE_CONFIG_DIR": str(BENCH / "configs" / "claude-home"),
            "ANTHROPIC_BASE_URL": MIMO_ANTHROPIC_URL,
            "ANTHROPIC_AUTH_TOKEN": MIMO_KEY,
            "ANTHROPIC_MODEL": MIMO_MODEL,
            "ANTHROPIC_SMALL_FAST_MODEL": MIMO_MODEL,
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1",
        }
    )
    cmd = [str(CLAUDE_EXE), "-p", prompt, "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"]
    raw = run_process(cmd, repo, env, budget)
    prompt_tokens = 0
    completion_tokens = 0
    tool_calls = 0
    tool_names: dict[str, int] = {}
    verify_cmds: list[str] = []
    errors: list[str] = []
    final_text = ""
    reported_cost = 0.0
    steps = 0
    for line in raw["stdout"].splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        etype = event.get("type")
        if etype == "assistant":
            message = event.get("message") or {}
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    tool_calls += 1
                    name = str(block.get("name") or "")
                    tool_names[name] = tool_names.get(name, 0) + 1
                    command = str((block.get("input") or {}).get("command") or "")
                    if command and ("pytest" in command or "unittest" in command or "npm test" in command):
                        verify_cmds.append(command[:300])
                elif block.get("type") == "text":
                    final_text = block.get("text") or final_text
            steps += 1
        elif etype == "result":
            usage = event.get("usage") or {}
            prompt_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
            completion_tokens = int(usage.get("output_tokens") or 0)
            reported_cost = float(event.get("total_cost_usd") or 0)
            final_text = str(event.get("result") or final_text)
            if event.get("is_error"):
                errors.append(str(event.get("result") or "claude error")[:300])
        elif etype == "system" and event.get("subtype") == "init":
            tool_names.setdefault("__tools_available", len(event.get("tools") or []))
    return {
        "exit_code": raw["exit_code"],
        "timed_out": raw["timed_out"],
        "status": "timeout" if raw["timed_out"] else ("done" if raw["exit_code"] == 0 else "error"),
        "duration_sec": raw["duration_sec"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tool_calls": tool_calls,
        "tool_names": {k: v for k, v in tool_names.items() if k != "__tools_available"},
        "steps": steps,
        "verify_cmds": verify_cmds,
        "errors": errors,
        "final_text": final_text[:4000],
        "reported_cost_usd": reported_cost,
        "stdout_bytes": len(raw["stdout"].encode("utf-8")),
        "stderr_tail": raw["stderr"][-2000:],
    }


def run_opencode(repo: Path, prompt: str, budget: int) -> dict:
    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(OPENCODE_CONFIG)
    env["CI"] = "1"
    cmd = [str(OPENCODE_EXE), "run", "-m", "mimo/mimo-v2.6-flash", "--auto", "--format", "json", prompt]
    raw = run_process(cmd, repo, env, budget)
    prompt_tokens = 0
    completion_tokens = 0
    reported_cost = 0.0
    tool_calls = 0
    tool_names: dict[str, int] = {}
    verify_cmds: list[str] = []
    errors: list[str] = []
    final_text = ""
    steps = 0
    for line in raw["stdout"].splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        etype = event.get("type")
        part = event.get("part") or {}
        if etype == "tool_use":
            tool_calls += 1
            name = str(part.get("tool") or "")
            tool_names[name] = tool_names.get(name, 0) + 1
            command = str(((part.get("state") or {}).get("input") or {}).get("command") or "")
            if command and ("pytest" in command or "unittest" in command or "npm test" in command):
                verify_cmds.append(command[:300])
        elif etype == "step_finish":
            steps += 1
            tokens = part.get("tokens") or {}
            prompt_tokens += int(tokens.get("input") or 0) + int((tokens.get("cache") or {}).get("read") or 0)
            completion_tokens += int(tokens.get("output") or 0)
            reported_cost += float(part.get("cost") or 0)
        elif etype == "text":
            final_text = str(part.get("text") or final_text)
        elif etype == "error":
            errors.append(str(part.get("message") or event.get("error") or "error")[:300])
    return {
        "exit_code": raw["exit_code"],
        "timed_out": raw["timed_out"],
        "status": "timeout" if raw["timed_out"] else ("done" if raw["exit_code"] == 0 else "error"),
        "duration_sec": raw["duration_sec"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "steps": steps,
        "verify_cmds": verify_cmds,
        "errors": errors,
        "final_text": final_text[:4000],
        "reported_cost_usd": round(reported_cost, 8),
        "stdout_bytes": len(raw["stdout"].encode("utf-8")),
        "stderr_tail": raw["stderr"][-2000:],
    }


def parse_pytest(stdout: str) -> dict:
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for key in counts:
        match = re.search(rf"(\d+) {key}", stdout)
        if match:
            counts[key] = int(match.group(1))
    total = counts["passed"] + counts["failed"] + counts["error"]
    return {**counts, "total": total}


def grade(repo: Path, task: dict, pre_protected: dict[str, str]) -> dict:
    post_protected = protected_snapshot(repo, task["protected_prefixes"])
    changed_protected = sorted(
        key for key, value in pre_protected.items() if post_protected.get(key) != value
    )
    added_protected = sorted(key for key in post_protected if key not in pre_protected)
    hidden_src = TASKS_DIR / task["id"] / "hidden"
    hidden_dst = repo / "tests_hidden"
    shutil.rmtree(hidden_dst, ignore_errors=True)
    hidden_dst.mkdir()
    for path in hidden_src.glob("*.py"):
        shutil.copy2(path, hidden_dst / path.name)
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "-q", "-p", "no:cacheprovider", "tests", "tests_hidden"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    elapsed = round(time.monotonic() - started, 2)
    counts = parse_pytest(proc.stdout or "")
    integrity_ok = not changed_protected and not added_protected
    raw_score = 100.0 * counts["passed"] / counts["total"] if counts["total"] else 0.0
    if not integrity_ok:
        raw_score = 0.0
    return {
        **counts,
        "score": round(raw_score, 1),
        "pytest_exit": proc.returncode,
        "pytest_sec": elapsed,
        "integrity_ok": integrity_ok,
        "changed_protected": changed_protected,
        "added_protected": added_protected,
        "pytest_tail": (proc.stdout or "")[-4000:],
    }


def time_score(duration: float, budget: int) -> float:
    floor = 120.0
    if duration <= floor:
        return 100.0
    if duration >= budget:
        return 0.0
    return round(100.0 * (1.0 - (duration - floor) / (budget - floor)), 1)


def discipline_score(run: dict, grade_result: dict) -> float:
    if not grade_result["integrity_ok"]:
        return 0.0
    if run.get("verify_cmds"):
        return 100.0
    if run.get("tool_calls"):
        return 50.0
    return 0.0


def init_git(repo: Path) -> None:
    try:
        subprocess.run(["git", "init", "-q"], cwd=repo, capture_output=True, timeout=30)
        (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.pyc\ntests_hidden/\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, timeout=30)
        subprocess.run(
            ["git", "-c", "user.name=bench", "-c", "user.email=bench@local", "commit", "-qm", "seed"],
            cwd=repo,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass

def run_one(tool: str, task_id: str, batch: str, server: HaoYuanServer | None) -> dict:
    meta = task_meta(task_id)
    prompt = (TASKS_DIR / task_id / "prompt.txt").read_text(encoding="utf-8")
    out_dir = RUNS_DIR / batch / tool / task_id
    repo = out_dir / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TASKS_DIR / task_id / "seed", repo, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    init_git(repo)
    before = snapshot(repo)
    pre_protected = protected_snapshot(repo, meta["protected_prefixes"])
    started = time.monotonic()
    if tool == "haoyuan":
        assert server is not None
        run = run_haoyuan(server, repo, prompt, meta["budget_sec"])
    elif tool == "claude":
        run = run_claude(repo, prompt, meta["budget_sec"])
    elif tool == "opencode":
        run = run_opencode(repo, prompt, meta["budget_sec"])
    else:
        raise SystemExit(f"unknown tool: {tool}")
    after = snapshot(repo)
    changed = sorted(key for key in after if before.get(key) != after[key])
    removed = sorted(key for key in before if key not in after)
    result = grade(repo, meta, pre_protected)
    record = {
        "batch": batch,
        "tool": tool,
        "task": task_id,
        "task_title": meta["title"],
        "budget_sec": meta["budget_sec"],
        "weight": meta["weight"],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wall_sec": round(time.monotonic() - started, 2),
        "run": run,
        "grade": result,
        "changed_files": changed,
        "removed_files": removed,
        "changed_count": len([k for k in changed if k not in removed]),
        "time_score": time_score(run["duration_sec"], meta["budget_sec"]),
        "discipline_score": discipline_score(run, result),
        "cost_est_usd": round(
            (run.get("prompt_tokens", 0) * 1.0 + run.get("completion_tokens", 0) * 4.0) / 1_000_000, 6
        ),
    }
    (out_dir / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "agent.stdout.log").write_text(run.get("stdout", ""), encoding="utf-8", errors="replace")
    (out_dir / "pytest.log").write_text(result["pytest_tail"], encoding="utf-8", errors="replace")
    return record


def summarize(records: list[dict]) -> dict:
    tools = sorted({record["tool"] for record in records})
    tasks = sorted({record["task"] for record in records})
    table = []
    for tool in tools:
        rows = [record for record in records if record["tool"] == tool]
        if not rows:
            continue
        weight = sum(row["weight"] for row in rows)
        correctness = sum(row["grade"]["score"] * row["weight"] for row in rows) / weight if weight else 0
        efficiency = sum(row["time_score"] for row in rows) / len(rows)
        discipline = sum(row["discipline_score"] for row in rows) / len(rows)
        final = 0.8 * correctness + 0.1 * efficiency + 0.1 * discipline
        table.append(
            {
                "tool": tool,
                "tasks": len(rows),
                "correctness": round(correctness, 1),
                "efficiency": round(efficiency, 1),
                "discipline": round(discipline, 1),
                "final": round(final, 1),
                "avg_sec": round(sum(row["run"]["duration_sec"] for row in rows) / len(rows), 1),
                "tokens_in": sum(row["run"].get("prompt_tokens", 0) for row in rows),
                "tokens_out": sum(row["run"].get("completion_tokens", 0) for row in rows),
                "tool_calls": sum(row["run"].get("tool_calls", 0) for row in rows),
                "cost_usd": round(sum(row["cost_est_usd"] for row in rows), 4),
                "integrity": all(row["grade"]["integrity_ok"] for row in rows),
            }
        )
    table.sort(key=lambda item: (-item["final"], item["avg_sec"]))
    return {"tools": table, "tasks": tasks, "records": len(records)}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--batch", required=True)
    run_parser.add_argument("--tools", default="haoyuan,claude,opencode")
    run_parser.add_argument("--tasks", default="all")
    run_parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if args.command != "run":
        return 2

    tools = [item.strip() for item in args.tools.split(",") if item.strip()]
    ids = task_ids(args.tasks)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_records: list[dict] = []
    server_cm = HaoYuanServer(args.batch) if "haoyuan" in tools else None
    server = server_cm.__enter__() if server_cm else None
    try:
        for task_id in ids:
            for tool in tools:
                record_path = RUNS_DIR / args.batch / tool / task_id / "run.json"
                if args.resume and record_path.is_file():
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    print(f"[resume] {tool} {task_id} score={record['grade']['score']}")
                else:
                    print(f"[run] {tool} {task_id} ...", flush=True)
                    record = run_one(tool, task_id, args.batch, server)
                    print(
                        f"[done] {tool} {task_id} score={record['grade']['score']} "
                        f"passed={record['grade']['passed']}/{record['grade']['total']} "
                        f"{record['run']['duration_sec']}s",
                        flush=True,
                    )
                all_records.append(record)
                summary = summarize(all_records)
                (RESULTS_DIR / f"{args.batch}.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
                )
    finally:
        if server_cm:
            server_cm.__exit__(None, None, None)

    summary = summarize(all_records)
    print(json.dumps(summary["tools"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
