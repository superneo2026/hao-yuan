# HaoYuan · 豪源

[简体中文](../../README.md) · [繁體中文](README.zh-TW.md) · **English**

> A personal AI studio where you direct multiple AI employees to work asynchronously in parallel.  
> One kernel, a set of installable plugins, and a verifiable closed loop for long-horizon tasks.

HaoYuan is rewritten on top of **agent-harness** as its backend reference foundation. It preserves and strengthens the coding expertise of an AI assistant while reorganizing sessions, tools, agents, routing, skills, supervision, and orchestration around a plugin architecture. The frontend is fully rewritten, with the goal of upgrading "AI collaboration" from a chat window into a workbench you can direct, observe, and intervene in.

![Workbench](../screenshots/workbench-dark.png)

---

## 1. Core Features

### 1.1 A genuinely usable coding loop

| Capability | Implementation |
|---|---|
| Repository awareness | `project_scan`, `repo_map`, symbol index, `search_symbol` |
| Precise reading | `read_file`, `read_range`, line-number targeting |
| Minimal edits | `apply_patch` (unified diff / SEARCH-REPLACE), `edit_file`, `multi_edit` |
| File operations | `write_file`, `glob`, `grep`, `list_dir`, `delete_path`, `move_path` |
| Command verification | `run_shell` (UTF-8, timeouts, structured error summaries), `git` wrapper |
| Verification gate | Tests/lint/build are mandatory after code changes, preventing "edit without verifying" |
| Test-fix loop | Structured pytest failure parsing → line localization → minimal fix → failure-fingerprint escalation |
| Sub-agents | `task` scouts in an isolated context and returns only conclusions, avoiding main-context pollution |
| Context governance | Tool-result aging, structured summaries, in-turn compression, hard-budget trimming |
| Context preloading | Requirement-aware `repo_map` ranking plus a relevant-source `context_pack` for complex tasks (up to ~30KB), reducing repeated full reads |
| Long-horizon tasks | Step budgets, automatic continuation, checkpoints, idempotent side-effect registry (writes are not re-applied) |
| Human-in-the-loop | High-risk writes/commands show a diff preview and execute only after approval |

Session intent layering: greetings, small talk, and general Q&A are answered directly without scanning the workspace, triggering tools, or writing; only explicit tasks such as coding, file changes, and running commands enter the coding loop.

### 1.2 Multi-session asynchronous parallelism

- One session = one background `asyncio.Task`; switching windows, closing tabs, or disconnecting does not stop the task.
- Global concurrency gate + FIFO queue; when waiting for human approval, the concurrency slot is yielded automatically.
- Session state machine: `idle → queued → running ⇄ waiting_input → done / error`.
- Session tab bar at the top of the workbench: creating or opening a session automatically adds a tab; click to switch horizontally; `×` only closes the view without deleting the session, and tabs persist after refresh.
- The first message of a new session is given a short title by the model in the current UI language; if an old session still has the default title, a summary is shown automatically based on the first message.
- Each session has its own URL `/#/s/<session-id>`, which can be copied, refreshed, shared, or switched to directly from the address bar.
- After refreshing the page, messages, events, plans, approvals, and artifacts are restored from SQLite.
- The main real-time event channel uses SSE (reconnect, cursor-based resume, streaming even without WebSocket); the WebSocket endpoint remains for compatibility; REST supports event replay.

### 1.3 AI supervisor and multi-agent orchestration

- **Supervisor**: cross-session health checks, stuck-task alerts, automatic interruption, console conversations, and scheduling actions.
- **Orchestrator**: goal → task DAG → an independent git worktree per employee → parallel execution → merge and acceptance.
- Employee sessions share contract files and a shared blackboard; a failure does not block other tasks at the same layer.

### 1.4 Skills library

- Markdown + front-matter declaring `name / title / description / kinds / triggers`.
- Automatically matched by task type and keywords; BM25 ranking kicks in when there are many skills.
- Built in: core methodology, repository engineering loop, debug loop, web delivery, and proposal writing.
- Skills can be created, edited, and deleted in the UI; changes take effect on save.

### 1.5 Plan documents

- `make_plan`: generates a standalone HTML proposal/plan with KPIs, sections, tables, risks, and milestones.
- Artifacts are registered under `api/data/artifacts/` and can be previewed/downloaded directly from the right side of the workbench.

### 1.6 Plugin architecture

HaoYuan is not "one giant monolith"; it is:

```
Kernel (sessions / events / tool registry / policy / model gateway / approvals)
        │
        ├── coding       coding agent + engineering tools + skills
        ├── plans        planning tools + Planner agent
        ├── supervisor   health checks + console routes
        ├── orchestrator task DAG + worktree + merge
        └── embodied     embodied agent harness (disabled by default, install to enable)
```

Plugins can contribute: tools, agents, HTTP routes, skill directories, event subscriptions, lifecycle hooks, and frontend navigation/command metadata. A single plugin failing to load will not take down the kernel.

![Plugins](../screenshots/plugins.png)

### 1.7 Three languages, light default, and a collapsible sidebar

- Default **light (white) theme**; switch to dark from the settings page or the bottom of the sidebar.
- Default **Simplified Chinese**; switch between **简体中文 / 繁體中文 / English**.
- Language entry points are in three prominent places: the workbench top bar, the sidebar bottom (available on all pages), and Settings → Appearance.
- The choice is persisted to `localStorage` and survives refresh and restart; `document.lang` and the page title are updated as well.
- The sidebar can collapse to a 76px icon rail; after collapsing, an explicit "Expand sidebar" button remains at the top, the session list is hidden, and everything is restored when expanded.
- The right-hand insights panel is collapsed by default to leave more room for the conversation; click the top-right button to open it, and the choice persists.
- Built-in skill titles/descriptions, plugin titles/descriptions, and UI copy for status, buttons, tips, approvals, plans, usage, and orchestration are fully covered in all three languages.

---

## 2. Quick Start

### Anonymous usage statistics (transparency notice)

HaoYuan includes a **fully anonymous** usage heartbeat to count online devices and version distribution:

- **Reported data**: a locally generated random `install_id` (UUID), client version, and OS type (e.g. `Windows 11`). It contains no usernames, emails, file contents, workspace paths, conversation content, or any other personal data.
- **Frequency**: once at startup and every 5 minutes while running (a single lightweight POST request).
- **Fully optional**: set the environment variable `HAOYUAN_TELEMETRY=0` before startup to disable it permanently; all features remain unaffected.
- **Privacy protection**: the server only records a one-way hash of the IP, never the plaintext IP; data is retained for 90 days.
- **Full notice**: see the plugin center privacy endpoint `GET {plugin-center-url}/api/plugin-center/privacy`, or the source `api/core/telemetry.py` (~100 lines, auditable).

### Requirements

- Python 3.10+
- Node.js 18+
- Windows / Linux / macOS

### npm install (recommended)

```bash
# Prerequisite: Node.js 18+ and Python 3.10+
npm install -g haoyuan

# Faster mirrors in mainland China:
npm install -g haoyuan --registry=https://registry.npmmirror.com

# Terminal chat (creates the venv and installs dependencies on first run)
haoyuan

# Start the service and open the web UI automatically
haoyuan web
```

| Command | Purpose |
|---|---|
| `haoyuan` | Terminal chat (streaming output, tool calls, approval prompts) |
| `haoyuan --model x/y` | Start chat with a specific model (e.g. `--model deepseek/deepseek-flash`) |
| `haoyuan web` | Start the service and open the web UI automatically |
| `haoyuan web --no-open` | Start the service without opening a browser |
| `haoyuan --version` / `-V` | Show the version |
| `haoyuan config` | Global config file (model keys, etc.); use `--open` to edit it directly |
| `haoyuan login` / `haoyuan logout` | Log in when account protection is enabled / clear the local token |
| `haoyuan setup` | Install dependencies only |
| `haoyuan help` | Show help |

In-terminal commands: `/models` to view/select a model (choose by number, or `/model x/y` to select directly), `/new` to create a session, `/web` to open the current session in a browser, `/cancel` to cancel the current task, `/exit` to quit (Ctrl+C also works).

The web UI defaults to `http://127.0.0.1:8030` and increments the port automatically when it is in use. Without a model key, the built-in `mock` model still runs sessions, tool calls, approvals, and the frontend end to end.

### Windows one-click start

```bat
start.bat
```

The script automatically: stops the old process on port 8030 → creates `api/env1` → installs Python dependencies → (only when `web/dist` is missing) installs frontend dependencies and builds → starts the API and opens the product page. The npm package already ships a prebuilt frontend, so intranet/offline environments can start directly once dependencies are installed. If a previous `npm install` left an incomplete `web/node_modules` due to a network interruption, the script detects and reinstalls it automatically — no manual deletion needed.

**Automatic port fallback**: the backend defaults to `8030` and the frontend dev server to `8130`; if a port is in use, it increments automatically (8031, 8032, …) until binding succeeds. The actual ports are written to `api/data/runtime.json`, and the start script reads them to open the correct address. You can also set the base ports explicitly with `HAOYUAN_PORT` / `HAOYUAN_WEB_PORT` (frontend) and `HAOYUAN_API_PORT` (frontend proxy target).

Stop:

```bat
stop.bat
```

### Desktop console (desktop.exe)

Double-click `desktop.exe` in the repository root to open the graphical console (~20 KB, depending only on the .NET Framework 4.x bundled with Windows):

- **Start all / stop all**: manage the backend and frontend dev server with one click; the product page opens automatically after startup
- **Start / stop backend** (default 8030) and **start / stop frontend** (default 8130)
- **Port settings**: edit backend/frontend ports directly; click "Apply ports and restart" to save the configuration and restart both services; if a port is occupied, the service still increments automatically
- **Open product page**: opens the backend's actual port from `api/data/runtime.json`; falls back to the frontend port when only the frontend is running
- **Build frontend**, **open project folder**, per-second service status, and live runtime logs

Closing the console window does not stop the services. To stop them, click "Stop all" or the corresponding stop buttons. The source lives in `desktop/`; run `desktop\build.bat` to rebuild after changes.

### Linux / macOS

```bash
bash start.sh
bash stop.sh
```

For intranet or custom-mirror environments, specify download sources explicitly (when omitted, the sources already configured in `~/.npmrc` and `pip.conf` are used):

```bash
export HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
export HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
bash start.sh
```

Windows equivalent:

```bat
set HAOYUAN_NPM_REGISTRY=http://your-intranet/npm/
set HAOYUAN_PIP_INDEX_URL=http://your-intranet/pypi/simple
start.bat
```

When frontend or Python dependencies are incomplete (for example, a previous install was interrupted by `ECONNRESET`), `start.sh` / `start.bat` / `haoyuan setup` automatically detect and clean `web/node_modules`, reinstall, install missing backend packages, and fall back to the existing `web/dist` if the build fails.

`web/package-lock.json` no longer hard-codes an external mirror; `replace-registry-host=always` in `web/.npmrc` ensures installs always use the registry from the current npm configuration, so the lockfile cannot hijack installs to an unreachable external mirror.

### Manual start

```bash
# Backend
cd api
python -m venv env1
env1\Scripts\activate           # Linux: source env1/bin/activate
pip install -r requirements.txt
python main.py                  # http://127.0.0.1:8030, increments automatically if in use

# Frontend dev mode (hot reload, optional)
cd web
npm install
npm run dev                     # http://localhost:8130, increments automatically if in use; /api and /ws proxy to the backend's actual port
```

In production, the backend serves `web/dist` directly, so you only need to visit the backend's actual port. Ports can be overridden with environment variables: `HAOYUAN_PORT` (backend, default 8030), `HAOYUAN_WEB_PORT` (frontend, default 8130), and `HAOYUAN_API_PORT` (frontend proxy target, default from `api/data/runtime.json`).

### Configure models

**Global config file (recommended)** — a fixed per-user path unaffected by reinstall or upgrade:

```bash
haoyuan config          # creates the file on first run and prints its path
haoyuan config --open   # open it directly in your editor
```

Path: `~/.config/haoyuan/config.json` (on Windows: `C:\Users\<you>\.config\haoyuan\config.json`; override with the `HAOYUAN_CONFIG` environment variable):

The file is created automatically on first startup (or by the npm postinstall), and its directory is created if missing.

```json
{
  "PROVIDER": "",
  "MODEL": "",
  "DEEPSEEK_API_KEY": "",
  "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
  "DEEPSEEK_MODEL": "deepseek-flash",
  "ZHIPU_API_KEY": "",
  "ZHIPU_BASE_URL": "https://open.bigmodel.cn/api/coding/paas/v4",
  "ZHIPU_MODEL": "glm-5.3-flash",
  "MIMO_API_KEY": "",
  "MIMO_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
  "MIMO_MODEL": "mimo-v2.6-flash",
  "providers": {}
}
```

- For built-in providers you can add `DEEPSEEK_MODELS` / `ZHIPU_MODELS` / `MIMO_MODELS` (comma-separated) to fully customize the model list; `*_THINKING_MODELS`, `*_MAX_OUTPUT`, and `*_SUPPORTS_THINKING` are optional.
- Any OpenAI-compatible provider can be added to the `providers` object, not just the three built-ins:

```json
{
  "providers": {
    "my-intranet": {
      "base_url": "http://llm.intranet/v1",
      "api_key": "sk-...",
      "models": ["qwen-max", "qwen-plus"],
      "default_model": "qwen-max",
      "supports_thinking": false,
      "max_output_tokens": 8192
    }
  }
}
```

- `PROVIDER` / `MODEL` can pin the default model (e.g. `"MODEL": "deepseek-v4-pro"` or `"MODEL": "my-intranet/qwen-max"`; leave empty to auto-select based on configured keys).
- **Two-way sync between the web settings page and the config file**: adding/editing providers, models, and the default model in "Settings → Model Configuration" writes back to the file immediately; if you edit the file directly and save, the service reloads it on the next request (no restart needed).

**In-package config (optional)**:

```bash
copy api\configs\secrets_example.py api\configs\secrets_local.py
```

Edit `api/configs/secrets_local.py` with the same fields (as Python constants). This is intended for source deployments; for a global npm install the file lives inside the package directory and is removed on upgrade, so prefer the global config.

**Environment variables** (highest priority):

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

Priority: environment variables > global config file > `secrets_local.py`. After editing the global config file, no restart is needed (the service hot-reloads); the `key_source` field of the health check `GET /api/health` shows where the key came from.

**When no key is configured, the local `mock` model is used automatically**, exercising sessions, tool calls, approvals, events, and the frontend end to end.

---

## 3. Interface

| Workbench (light, default) | Workbench (English) |
|---|---|
| ![](../screenshots/workbench-light.png) | ![](../screenshots/workbench-en.png) |

| Workbench (Traditional Chinese) | Workbench (dark) |
|---|---|
| ![](../screenshots/workbench-tw.png) | ![](../screenshots/workbench-dark.png) |

| Supervisor console | Skills library |
|---|---|
| ![](../screenshots/console.png) | ![](../screenshots/skills.png) |

| Settings and language entry | Expand button after collapsing the sidebar |
|---|---|
| ![](../screenshots/settings.png) | ![](../screenshots/collapsed.png) |

Mobile right-hand insights panel:  
![](../screenshots/mobile-panel.png)

Key interactions:

- Top session tabs: click to switch conversations; `×` closes a tab (session data is not affected)
- New tasks no longer offer preset questions; just describe the task in the input box and the session title is summarized automatically
- Address-bar routing: `/#/s/<session-id>` maps to a specific session and can be copied, refreshed, or opened in a new window
- `Ctrl / Cmd + K`: command palette (navigation, sessions, actions)
- `Ctrl / Cmd + N`: new task
- `Ctrl / Cmd + B`: collapse / expand the sidebar
- `Enter`: send; `Shift + Enter`: newline (`Ctrl / Cmd + Enter` also sends)
- Approval card: `A` approves, `R` rejects
- Language switching: top-right of the workbench, bottom of the sidebar on any page, and Settings → Appearance
- Type while a session is running: input is merged into the current execution as an "additional instruction" without interrupting the task
- The right panel is collapsed by default; click the top-right button to open Overview / Plan / Files / Changes / Artifacts, and drag to resize
- Files and diffs use a large preview overlay to avoid reading code in a narrow column

---

## 4. Architecture

```text
hao-yuan/
├── api/
│   ├── main.py                    FastAPI entry (extension routes + plugin routes + static frontend)
│   ├── configs/                   Configuration, model registry, secrets
│   ├── core/
│   │   ├── contracts.py           Tool / Agent / Policy / ToolContext
│   │   ├── storage.py             SQLite (WAL) storage layer
│   │   ├── events.py              Event bus (broadcast + batched persistence + replay)
│   │   ├── gateway.py             Model gateway (streaming + degradation + fallback)
│   │   ├── context.py             Context compression / aging / hard budget
│   │   ├── runtime.py             Agent main loop
│   │   ├── session_manager.py     Concurrency gate / queue / approvals / resume
│   │   ├── policy.py              Permission gate
│   │   ├── tools.py               Tool registry and execution
│   │   ├── agents.py              Agent registry
│   │   └── plugin.py              Plugin discovery / dependencies / lifecycle
│   ├── harness/                   Sandbox / skills / symbol index / fix loop / supervision / orchestration / embodied
│   ├── tools/                     builtin / dev / plan
│   ├── adapters/providers/        deepseek / mimo / mock
│   ├── plugins/                   coding / plans / supervisor / orchestrator / embodied
│   ├── extensions/                System / sessions / skills / settings / files / usage / plugins / approvals / real-time events (SSE / WebSocket)
│   ├── skills/                    Core skills
│   ├── tests/                     28 backend tests
│   └── data/                      Runtime data (gitignored)
├── web/                           Vue 3 + Vite
├── docs/screenshots/              UI screenshots
├── start.bat / stop.bat
├── start.sh / stop.sh
├── dev.bat
├── desktop.exe                    Graphical desktop console (start/stop services / open the web UI)
└── desktop/                       desktop.exe source and build scripts
```

### Data and boundaries

- Database: `api/data/haoyuan.db` (WAL)
- Artifacts: `api/data/artifacts/<session_id>/`
- Runtime ports: `api/data/runtime.json` (the backend writes `api_port`, the frontend writes `web_port`, and the desktop console writes `api_port_config` / `web_port_config`)
- All file tools are constrained by the session workspace allowlist and reject `../` and absolute-path escapes.
- High-risk tools (file writes, patch, delete, move, shell, git, robot motion) require approval.
- `run_shell` hard-blocks catastrophic commands (such as `rm -rf /`, disk formatting, and shutdown).
- Artifact HTML is previewed through an endpoint with a sandbox CSP, preventing model-generated pages from reading local credentials.
- Secrets are read only from environment variables or `secrets_local.py`; they are never stored in the database or returned in plaintext.
- Real keys live in `api/configs/secrets_local.py`, which is ignored by `.gitignore`; `git add --dry-run` verifies they never enter the repository.

---

## 5. Plugin Development

Create a directory under `api/plugins/`:

```
api/plugins/my-plugin/
├── plugin.json
├── plugin.py
├── routes.py        # optional
└── skills/          # optional
    └── my-skill.md
```

`plugin.json`:

```json
{
  "name": "my-plugin",
  "title": "My Plugin",
  "version": "1.0.0",
  "description": "What this plugin adds",
  "author": "you",
  "requires": ["coding"],
  "default_enabled": true,
  "backend": "plugin.py",
  "routes": "routes.py",
  "contributes": {
    "tools": ["my_tool"],
    "agents": ["my_agent"],
    "skills": true
  },
  "frontend": {
    "nav": [{ "label": "My Plugin", "path": "/my-plugin", "icon": "puzzle" }],
    "commands": [{ "id": "my-plugin.run", "title": "Run my plugin" }]
  }
}
```

`plugin.py`:

```python
from core.contracts import AgentSpec, ToolSpec


async def my_tool(ctx, args):
    return {"echo": args.get("text", "")}


def register(ctx):
    ctx.register_tool(
        ToolSpec(
            name="my_tool",
            description="Echo text",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        my_tool,
    )
    ctx.register_agent(
        AgentSpec(
            name="my_agent",
            title="My Agent",
            instructions="You are ...",
            tools=["my_tool"],
            kind="dev",
        )
    )
    ctx.add_skill_dir("skills")


async def startup(ctx):
    ...


async def shutdown(ctx):
    ...
```

Plugin capabilities:

- `requires` controls dependency ordering; missing dependencies are isolated and the error is recorded.
- `startup / shutdown` lifecycle hooks.
- `ctx.events.subscribe(sink)` subscribes to global events (this is how the orchestrator receives employee completion events).
- Enabled/disabled state is persisted in SQLite; after toggling, restart the API to load/unload routes.
- The frontend obtains `contributes` and `frontend` metadata via `/api/plugins`.

### Why this design

It borrows WordPress's "small kernel + installable plugins": the kernel only handles sessions, events, policy, models, and the tool protocol; all business capabilities live in plugins.  
It also adopts the DeepSeek Harness idea that "the harness itself is pluggable": an embodied agent is just an independent harness plugin, so you can keep adding harnesses for rovers, robot arms, humanoid robots, and more without touching the kernel.

---

## 6. Self-Test Results

The following was executed in the delivery environment:

```bash
cd api
python -m pytest -q
# 28 passed, 1 warning

cd ../web
npm run build
# ✓ built, 83 modules transformed
```

Test coverage:

- Health check, models, skills, plugins, and approval listing
- A complete mock-model session (message → event → done)
- Coding session: write file → tool event → artifact → workspace tree read
- Human approval flow: pending → approve → tool execution → file written to disk
- Session rename / hide / restore / clear / permanent delete
- Global gate and default workspace settings, usage, and CSV export
- Plugin enabled-state persistence
- Orchestrator git worktree end to end (create → dispatch → complete → merge)
- Tool level: sandbox escape, read/write/edit/patch/multi_edit, glob/grep/symbols, shell, delete/move
- Hard blocking of dangerous shell commands
- Symbol index, repo map, pytest parsing, and fix guidance
- Plan HTML artifact generation
- Intent routing: greetings, small talk, and general Q&A (such as "how are you", "nice weather today", "what is dependency injection") are answered directly without scanning the workspace, triggering tools, or writing (including real deepseek-flash verification)
- Automatic session title from the first message (follows the UI language; mock covers fallback and real-model verification)
- Independent session routing: `/#/s/<session-id>` deep links, tab switching, address-bar editing, refresh restore, and fallback on close

In addition, a real-browser inspection of the production build was done with Playwright + local Chrome:

- Workbench / console / skills / plugins / settings / usage / orchestration pages all load
- Top session tabs and independent routing: open, switch, close, address-bar deep links, and refresh restore
- Default-title summarization, top-right language menu (English / Simplified Chinese switching), and an empty state without preset questions
- Simplified Chinese, Traditional Chinese, and English switching works, and the language persists after refresh
- Language entry points cover the workbench top bar, sidebar bottom, and settings page
- Sidebar collapse/expand between 286px and 76px works; after collapsing, the session list is hidden and the expand button is visible
- The right insights panel is collapsed by default, and its expanded/collapsed state persists
- `Enter` submits and `Shift + Enter` inserts a newline; IME composition does not submit accidentally
- Dark / light themes work
- 430px mobile layout, sidebar drawer, and right insights drawer work
- SSE real-time stream: real DeepSeek reasoning and content deltas are visible before `done`
- No JS errors, no 404 resources, and no WebSocket 404 in the console (the main real-time channel is now SSE)

> Real online verification was completed with the DeepSeek key referenced by the AI assistant: `deepseek-flash` returned `OK`, and usage provider/model = `deepseek/deepseek-flash`. The key is stored only in `api/configs/secrets_local.py`, which is ignored by `.gitignore`; the repository only commits the `secrets_example.py` template. Mock regression tests remain, so the system degrades automatically when offline or without a key.

---

## 7. Harness Fair Benchmark Results

> Latest report: [test/testing/index-2026-10-27.html](../../test/testing/index-2026-10-27.html) (2026-10-27, mimo-v2.6-flash)  
> Historical report: [test/testing/index-2026-10-25.html](../../test/testing/index-2026-10-25.html) (2026-10-25, deepseek-flash)

### 7.1 MiMo fair benchmark (latest)

**Method**: 5 automatically gradable tasks (1 basic adaptive + 4 covering localization / performance / long-horizon / concurrency) × 3 tools; unified `mimo-v2.6-flash`, prompts, seed repository, and budget. Hidden tests are injected after the run, and `tests/` and `pyproject.toml` are SHA-256 verified — tampering scores 0. t1/d1/d3 use the official-r1 interleaved batch; d4/d6 use an independent rerun batch after the code was frozen.

| Rank | Tool | Overall (product-weighted) | Correctness | Speed | Cost | Engineering discipline | Equal-weight |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **98.8** | 100.0 | 94.4 | 96.9 | 100.0 | **98.3 (1st)** |
| 2 | OpenCode | 90.5 | 100.0 | 67.8 | 53.5 | 100.0 | 84.3 (2nd) |
| 3 | Claude Code | 88.9 | 100.0 | 65.1 | 40.9 | 100.0 | 81.2 (3rd) |

Overall = 0.65 × correctness + 0.15 × speed + 0.10 × cost + 0.10 × engineering discipline; the equal-weight formula uses 0.40 / 0.20 / 0.20 / 0.20.

- All three scored 100% correctness; HaoYuan scored **98.8** product-weighted and **98.3** equal-weight, first under both formulas.
- Per task: HaoYuan was fastest on t1 (63.8s), d3 (220.6s), and d4 (469.6s); OpenCode won d1 (111.3s), and Claude Code won d6 (254.5s).
- Cost: total cost for the 5 tasks was **$3.33** for HaoYuan, $6.56 for OpenCode, and $9.04 for Claude Code; per-task costs were $0.666 / $1.313 / $1.809.
- Adaptive intensity: t1, an easy task, took 63.8s and 11 calls without starting a plan or sub-agent; the long-horizon d4 task used preloaded relevant source to reduce repeated exploration (from a 1200s timeout down to 469.6s).
- Key fixes: completed the MiMo provider (previously `resolve("mimo", ...)` silently fell back to deepseek), requirement-aware repo map, a 30KB context pack for complex tasks, process-tree reclamation, strict provider + per-call limits + same-model retries, and lite routing for easy tasks.
- Limitations: the formal comparison used 1 round per task; d4/d6 were independent rerun batches; model latency variance is large (Claude d3 was 623s earlier and 884s this time); d5 lacked discrimination and was not ranked; tasks are self-built and cannot replace public benchmarks such as SWE-bench.

Reproduce:

```bash
cd test/bench
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks t1_multisite_bugfix,d1_needle_regress,d3_perf_cliff --resume
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks d4_multilayer_feature,d6_concurrency_fix --resume
python make_report_mimo_final.py
```

### 7.2 deepseek-flash deep benchmark (historical)

**Method**: 8 automatically gradable coding tasks (5 basic + 3 hard) × 3 rounds per task × 3 tools; unified deepseek-flash, prompts, seed repository, and budget; hidden tests are injected after the run, and `tests/` and `pyproject.toml` are SHA-256 verified — tampering scores 0.

| Rank | Tool | Overall score (product-weighted) | Correctness | Typical speed | Tail latency | Cost | Equal-weight score |
|---|---|---|---|---|---|---|---|
| 1 | **HaoYuan** | **96.6** | 100.0 | 100.0 (median 30.3s) | 67.6 (P90 159.4s) | 82.2 ($0.364) | 95.0 (2nd) |
| 2 | OpenCode | 95.1 | 100.0 | 67.6 (median 44.8s) | 100.0 (P90 107.7s) | 100.0 ($0.299) | 96.8 (1st) |
| 3 | Claude Code | 90.7 | 100.0 | 70.6 (median 42.9s) | 90.7 (P90 118.7s) | 55.4 ($0.540) | 91.7 (3rd) |

Overall = 0.70 × correctness + 0.15 × typical speed + 0.05 × tail latency + 0.10 × cost; the equal-weight formula changes the last two weights to 0.10 / 0.10.

- All three scored 100% correctness; differences were concentrated in speed, tail latency, and token cost; HaoYuan was first product-weighted, while OpenCode overtook it on equal weight.
- HaoYuan had the shortest median task time at 30.3s and was fastest on the median of four tasks (T1/T2/T3/H1); all 24 runs were 100% complete. OpenCode had the best tail latency and per-task cost; Claude Code had the highest token cost.
- Weaknesses: H2 version migration had a 159.4s median (OpenCode: 101.1s), and H3 had a 260s long tail; future work will further compress migration audits and self-test rounds.
- Limitations: covers only deepseek-flash and 3 rounds per task; tasks are self-built and cannot replace public benchmarks such as SWE-bench.
- Self-iteration: during evaluation, Windows pipe adaptation, empty-reply/no-write protection, migration acceptance audits, lightweight git diff audits, and completion ordering were fixed; one "over-testing" negative optimization was rolled back.

Reproduce:

```bash
cd test/bench
python harness_bench.py run --batch final-r1 --tools haoyuan,claude,opencode --tasks all
python aggregate.py
python make_report.py
```

---

## 8. Feature Parity with the AI Assistant

| Capability | HaoYuan | Notes |
|---|---|---|
| Coding toolchain | ✅ | Localization, minimal patches, verification, fix loop, sub-agents |
| Context compression / long-horizon | ✅ | In-turn compression, aging, hard budget, checkpoints, idempotent resume |
| Multi-session parallelism | ✅ | Concurrency gate, FIFO, background tasks decoupled from the frontend |
| Permission gate / diff approval | ✅ | Approval cards, preview, timeout, concurrency-slot yielding |
| Skills library | ✅ | front-matter + rules/BM25 + UI editing |
| Plan documents | ✅ | Standalone HTML artifacts |
| AI supervisor | ✅ | Snapshots, alerts, console conversations, scheduling actions |
| Multi-agent orchestration | ✅ | Task DAG + git worktree + merge metrics |
| Token / cost statistics | ✅ | Daily aggregation, by model, CSV export |
| Plugin mechanism | ✅ Enhanced | Manifest, dependencies, lifecycle, tools/agents/routes/skills/frontend metadata |
| Feishu remote command | ⏳ Not in this release | The interface layer is decoupled and can be added as a plugin |
| ASR / TTS / video rendering | ⏳ Not in this release | The current focus is the core AI coding loop |
| Authoritative benchmarks | ⏳ Public benchmarks not run | Self-built benchmarks are complete: a 5-task MiMo fair benchmark and an 8-task deepseek deep benchmark (see Section 7); public benchmarks such as SWE-bench have not been rerun |

---

## 9. Roadmap (architecture already reserved)

### 9.1 Skills library for local training on 16GB VRAM

Planned built-ins:

- SFT data construction and training scripts for Qwen3.5-0.8B
- RL (preference optimization / verifiable rewards) training scripts
- Memory-friendly configurations: LoRA / QLoRA, gradient accumulation, small batches, sequence-length control
- Organized by "skill": data templates, training configs, evaluation cases, and deployment notes

HaoYuan's current Skill mechanism is already file-based and versionable, so training-methodology documents can later be injected into agents as Skills.

### 9.2 Plugin-based embodied harness

`plugins/embodied` already demonstrates:

- Robot state / sensors / movement / steering / emergency-stop tools
- High-risk action approval
- An HTTP demo bridge

Without changing the kernel, you can later add:

- `embodied-ros2` (ROS2 topics / services)
- `embodied-serial` (Arduino / ESP32)
- `embodied-smolvla` (vision-language-action model)
- Harness plugins for rovers, robot arms, and humanoid robots

---

## 10. API Overview

Unified prefix `/api`, response format `{ code, data, message }`.

| Group | Main endpoints |
|---|---|
| System | `GET /health`, `GET /info`, `GET /models`, `GET /agents`, `GET /tools` |
| Sessions | `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `PATCH /sessions/{id}` |
| Messages | `POST /sessions/{id}/messages`, `GET /sessions/{id}/messages` |
| Events | `GET /sessions/{id}/events?after_id=`, `GET /sessions/{id}/stream`, `WS /ws` |
| Approvals | `GET /approvals`, `POST /approvals/{id}/resolve`, `POST /sessions/{id}/confirm` |
| Skills | `GET/POST /skills`, `GET/PUT/DELETE /skills/{name}` |
| Files | `GET /workspace/tree`, `GET /workspace/file`, `GET /workspace/changes`, `GET /workspace/diff` |
| Settings | `GET/PUT /settings`, `PUT /settings/gate`, `PUT /settings/workspace` |
| Usage | `GET /usage/today`, `GET /usage/daily`, `GET /usage/by-model`, `GET /usage/export.csv` |
| Plugins | `GET /plugins`, `POST /plugins/{name}/toggle` |
| Supervisor | `GET /supervisor/overview`, `GET /supervisor/console`, `POST /supervisor/act`, `POST /supervisor/chat` |
| Orchestration | `POST /orchestrations`, `GET /orchestrations`, `GET /orchestrations/{id}` |

Interactive docs: <http://127.0.0.1:8030/docs> (after a port increment, use the backend log or `api/data/runtime.json`).

---

## 11. Development and Testing

```bash
cd api
python -m pytest -q

cd ../web
npm run build
npm run dev        # dev mode; /api and /ws proxy to the backend's actual port automatically
```

We recommend recording your team's lint / test / build commands in `AGENTS.md`; HaoYuan automatically injects project memory into context.

---

## License

This project is released under the [MIT License](../../LICENSE) and is free to use, modify, and distribute.
