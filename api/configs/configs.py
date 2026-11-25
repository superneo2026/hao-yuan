from __future__ import annotations

import os
from pathlib import Path

from configs.models import auto_default

APP_NAME = "HaoYuan"
APP_VERSION = "0.0.4"
SERVER_HOST = os.getenv("HAOYUAN_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("HAOYUAN_PORT", "8030"))
prefix = "/api"

# 浏览器跨域白名单：默认只允许本机开发前端，避免任意网站读取本地 API。
CORS_ORIGINS = tuple(
    item.strip() for item in os.getenv("HAOYUAN_CORS_ORIGINS", "").split(",") if item.strip()
)
CORS_ORIGIN_REGEX = os.getenv(
    "HAOYUAN_CORS_ORIGIN_REGEX", r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
)

API_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = API_DIR.parent
WEB_DIST_DIR = PROJECT_DIR / "web" / "dist"

DATA_DIR = Path(os.getenv("HAOYUAN_DATA_DIR", API_DIR / "data")).expanduser().resolve()
DB_PATH = Path(os.getenv("HAOYUAN_DB_PATH", DATA_DIR / "haoyuan.db")).expanduser().resolve()
WORKSPACE_DIR = Path(os.getenv("HAOYUAN_WORKSPACE_DIR", DATA_DIR / "workspaces")).expanduser().resolve()
ARTIFACTS_DIR = Path(os.getenv("HAOYUAN_ARTIFACTS_DIR", DATA_DIR / "artifacts")).expanduser().resolve()
UPLOADS_DIR = Path(os.getenv("HAOYUAN_UPLOADS_DIR", DATA_DIR / "uploads")).expanduser().resolve()
SKILLS_DIR = Path(os.getenv("HAOYUAN_SKILLS_DIR", API_DIR / "skills")).expanduser().resolve()
PLUGINS_DIR = Path(os.getenv("HAOYUAN_PLUGINS_DIR", API_DIR / "plugins")).expanduser().resolve()
GITIGNORE_PLUGINS_DIR = Path(
    os.getenv("HAOYUAN_GITIGNORE_PLUGINS_DIR", API_DIR / "gitignore_plugins")
).expanduser().resolve()
PLUGIN_DIRS = (PLUGINS_DIR, GITIGNORE_PLUGINS_DIR)
# 插件中心地址：默认指向豪源统计云端站点；自建部署可用 HAOYUAN_PLUGIN_CENTER_URL 覆盖
PLUGIN_CENTER_URL = os.getenv("HAOYUAN_PLUGIN_CENTER_URL", "https://hao-yuan.conductorer.com").rstrip("/")
PLUGIN_PACKAGE_MAX_BYTES = int(os.getenv("HAOYUAN_PLUGIN_PACKAGE_MAX_BYTES", str(20 * 1024 * 1024)))
PLUGIN_PACKAGE_MAX_UNCOMPRESSED_BYTES = int(
    os.getenv("HAOYUAN_PLUGIN_PACKAGE_MAX_UNCOMPRESSED_BYTES", str(64 * 1024 * 1024))
)
PLUGIN_PACKAGE_MAX_FILES = int(os.getenv("HAOYUAN_PLUGIN_PACKAGE_MAX_FILES", "2000"))
PLUGIN_CATALOG_MAX_BYTES = int(os.getenv("HAOYUAN_PLUGIN_CATALOG_MAX_BYTES", str(4 * 1024 * 1024)))
# 匿名统计心跳（透明可关闭：HAOYUAN_TELEMETRY=0），密钥与服务端一致，仅用于过滤无关流量
PLUGIN_CENTER_APP_KEY = os.getenv("HAOYUAN_TELEMETRY_APP_KEY", "haoyuan-plugin-center-v1")

DEFAULT_PROVIDER, DEFAULT_MODEL = auto_default()
DEFAULT_AGENT = os.getenv("HAOYUAN_DEFAULT_AGENT", "coding")
DEFAULT_TENANT_ID = os.getenv("HAOYUAN_TENANT_ID", "default")
DEFAULT_USER_ID = os.getenv("HAOYUAN_USER_ID", "local")

MAX_CONCURRENT_SESSIONS = int(os.getenv("HAOYUAN_MAX_CONCURRENT", "5"))
# Steps per segment; at each boundary the agent gets a "continue, don't repeat" nudge.
AGENT_MAX_STEPS = int(os.getenv("HAOYUAN_MAX_STEPS", "60"))
# Total steps a single run may execute, across all rollover segments. This is the
# long-horizon hard budget. It used to default to 200000, which let a looping model
# burn tens of millions of tokens for hours; 600 steps (~10 segments) is already far
# beyond any healthy task. Raise it explicitly for genuinely huge migrations.
AGENT_MAX_TOTAL_STEPS = int(os.getenv("HAOYUAN_MAX_TOTAL_STEPS", "600"))
# Wall-clock budget for one run. 0 disables it. This is the last line of defence
# against a model that keeps emitting tool calls but never converges.
AGENT_MAX_RUN_SEC = float(os.getenv("HAOYUAN_MAX_RUN_SEC", "7200"))
# Maximum automatic boot-resumes for an interrupted run (crash / restart).
MAX_AUTO_ROLLOVER = int(os.getenv("HAOYUAN_MAX_ROLLOVER", "100"))
GATE_CONFIRM_TIMEOUT = float(os.getenv("HAOYUAN_GATE_TIMEOUT", "600"))
AUTO_APPROVE_HIGH_RISK = os.getenv("HAOYUAN_AUTO_APPROVE", "0").strip() in {"1", "true", "yes"}

LLM_CONNECT_TIMEOUT = float(os.getenv("HAOYUAN_LLM_CONNECT_TIMEOUT", "20"))
LLM_FIRST_CHUNK_TIMEOUT = float(os.getenv("HAOYUAN_LLM_FIRST_CHUNK_TIMEOUT", "180"))
LLM_STREAM_IDLE_TIMEOUT = float(os.getenv("HAOYUAN_LLM_STREAM_IDLE_TIMEOUT", "300"))
LLM_TOTAL_TIMEOUT = float(os.getenv("HAOYUAN_LLM_TOTAL_TIMEOUT", "1800"))
TOOL_TIMEOUT_SEC = float(os.getenv("HAOYUAN_TOOL_TIMEOUT", "300"))
TOOL_HEARTBEAT_SEC = float(os.getenv("HAOYUAN_TOOL_HEARTBEAT", "15"))
SHELL_TIMEOUT = float(os.getenv("HAOYUAN_SHELL_TIMEOUT", "120"))
# Upper bound for a single model-requested shell timeout (git clone/build/downloads).
SHELL_TIMEOUT_MAX = float(os.getenv("HAOYUAN_SHELL_TIMEOUT_MAX", "1800"))
# Per-command resource ceilings for run_shell children (0 disables a limit).
SHELL_LIMIT_NOFILE = int(os.getenv("HAOYUAN_SHELL_NOFILE", "4096"))
SHELL_LIMIT_FSIZE_MB = int(os.getenv("HAOYUAN_SHELL_FSIZE_MB", "4096"))
SHELL_LIMIT_NPROC = int(os.getenv("HAOYUAN_SHELL_NPROC", "1024"))
SHELL_LIMIT_MEM_MB = int(os.getenv("HAOYUAN_SHELL_MEM_MB", "0"))
SHELL_LIMIT_CPU_SEC = int(os.getenv("HAOYUAN_SHELL_CPU_SEC", "0"))

# Periodic SQLite maintenance: WAL checkpoint + PRAGMA optimize every 6h.
MAINTENANCE_INTERVAL = float(os.getenv("HAOYUAN_MAINTENANCE_INTERVAL", "21600"))
MAINTENANCE_VACUUM = os.getenv("HAOYUAN_MAINTENANCE_VACUUM", "0").strip() not in {"0", "false"}

TOOL_RESULT_MAX_BYTES = int(os.getenv("HAOYUAN_TOOL_RESULT_MAX_BYTES", str(64 * 1024)))
# Tool output kept in the model context. The old 2000-char cap starved the model:
# every read of a reference page came back clipped, so it slid a 2KB window through
# the file hundreds of times (observed: 611 read_range calls on one HTML file).
# 16k chars (~4k tokens) fits a whole CSS block or a table while still bounding
# history growth; the full result stays in session history for re-reading.
TOOL_RESULT_CONTEXT_CHARS = int(os.getenv("HAOYUAN_TOOL_RESULT_CONTEXT_CHARS", "16000"))
TOOL_RESULT_CONTEXT_MARK = "\n...[result truncated; re-read the precise range if needed]"
# Shell output is compressed structurally before it enters the model context:
# keep the first/last N lines plus every failure-looking line, summarize clean
# runs to one line, and diff repeated failures. The full result is written to
# TOOL_LOGS_DIR for audit instead of being re-injected into the prompt.
TOOL_COMPRESS_ENABLED = os.getenv("HAOYUAN_TOOL_COMPRESS", "1").strip() not in {"0", "false"}
TOOL_COMPRESS_MIN_CHARS = int(os.getenv("HAOYUAN_TOOL_COMPRESS_MIN_CHARS", "4000"))
TOOL_COMPRESS_HEAD_LINES = int(os.getenv("HAOYUAN_TOOL_COMPRESS_HEAD_LINES", "40"))
TOOL_COMPRESS_TAIL_LINES = int(os.getenv("HAOYUAN_TOOL_COMPRESS_TAIL_LINES", "40"))
TOOL_COMPRESS_MAX_ERROR_LINES = int(os.getenv("HAOYUAN_TOOL_COMPRESS_MAX_ERROR_LINES", "120"))
TOOL_LOGS_DIR = DATA_DIR / "tool_logs"
# Tool results shorter than this are never compacted away (keeps small reads intact).
# When the provider-specific MAX_OUTPUT is 0 (unspecified), request this many output
# tokens explicitly. Relying on the provider default silently capped writes at 8192.
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("HAOYUAN_MAX_OUTPUT", "32768"))
# Source preloaded into the system prompt at task start. Re-sent on every step, so it
# is the single biggest fixed cost on long tasks. 12k chars (~3k tokens) is enough to
# orient without duplicating what the agent will read on demand.
CONTEXT_PACK_MAX_CHARS = int(os.getenv("HAOYUAN_CONTEXT_PACK_MAX_CHARS", "6000"))

# Context budget. Compaction thresholds used to be fixed at 14k-20k *estimated*
# tokens while the system prompt alone is ~16k real tokens, leaving a 6-10k working
# window; the agent compacted 7 times in 64 steps and never held plan + reference +
# partial output at once. Thresholds now scale with the model's context window and
# the fixed values below act as floors for small-window models.
DEFAULT_CONTEXT_WINDOW = int(os.getenv("HAOYUAN_CONTEXT_WINDOW", str(128 * 1024)))
CONTEXT_COMPACT_RATIO = float(os.getenv("HAOYUAN_CONTEXT_COMPACT_RATIO", "0.55"))
CONTEXT_HARD_RATIO = float(os.getenv("HAOYUAN_CONTEXT_HARD_RATIO", "0.80"))
# estimate_tokens() under-counts CJK-heavy text vs the provider's tokenizer; the
# observed ratio in a real run was ~1.8x, so estimates are inflated by this factor.
TOKEN_ESTIMATE_FACTOR = float(os.getenv("HAOYUAN_TOKEN_ESTIMATE_FACTOR", "1.8"))
CONTEXT_COMPACT_TOKENS = int(os.getenv("HAOYUAN_CONTEXT_COMPACT_TOKENS", "20000"))
CONTEXT_KEEP_RECENT = int(os.getenv("HAOYUAN_CONTEXT_KEEP_RECENT", "10"))
CONTEXT_SUMMARY_MAX_CHARS = int(os.getenv("HAOYUAN_CONTEXT_SUMMARY_MAX_CHARS", "2400"))
MID_COMPACT_EVERY = int(os.getenv("HAOYUAN_MID_COMPACT_EVERY", "4"))
MID_COMPACT_TOKENS = int(os.getenv("HAOYUAN_MID_COMPACT_TOKENS", "14000"))
MID_COMPACT_MIN_MSGS = int(os.getenv("HAOYUAN_MID_COMPACT_MIN_MSGS", "18"))
# After a compaction, do not compact again within this many steps unless the body
# exceeds the trigger by HYSTERESIS_RATIO (prevents compact -> re-read -> compact).
COMPACT_HYSTERESIS_STEPS = int(os.getenv("HAOYUAN_COMPACT_HYSTERESIS_STEPS", "6"))
COMPACT_HYSTERESIS_RATIO = float(os.getenv("HAOYUAN_COMPACT_HYSTERESIS_RATIO", "1.3"))
TOOL_AGING_KEEP = int(os.getenv("HAOYUAN_TOOL_AGING_KEEP", "16"))
TOOL_AGING_CHARS = int(os.getenv("HAOYUAN_TOOL_AGING_CHARS", "300"))
# Off by default: re-aging tool results mid-turn rewrites messages that were
# already sent, which invalidates the provider prefix cache for the rest of the
# turn. Results are compressed once at insertion instead.
MIDTURN_TOOL_AGING = os.getenv("HAOYUAN_MIDTURN_TOOL_AGING", "0").strip() not in {"0", "false"}
CONTEXT_HARD_LIMIT = int(os.getenv("HAOYUAN_CONTEXT_HARD_LIMIT", "48000"))
CONTEXT_HARD_TRUNCATE_CHARS = int(os.getenv("HAOYUAN_CONTEXT_HARD_TRUNCATE_CHARS", "800"))
STRUCTURED_DIGEST_ENABLED = os.getenv("HAOYUAN_STRUCTURED_DIGEST", "1").strip() not in {"0", "false"}
DIGEST_HEAD_CHARS = int(os.getenv("HAOYUAN_DIGEST_HEAD_CHARS", "500"))
DIGEST_TAIL_CHARS = int(os.getenv("HAOYUAN_DIGEST_TAIL_CHARS", "500"))

SEARCH_MAX_FILES = int(os.getenv("HAOYUAN_SEARCH_MAX_FILES", "4000"))
SEARCH_TIME_BUDGET = float(os.getenv("HAOYUAN_SEARCH_TIME_BUDGET", "20"))
SEARCH_MAX_FILE_BYTES = int(os.getenv("HAOYUAN_SEARCH_MAX_FILE_BYTES", "1000000"))
SEARCH_SKIP_DIRS = (
    ".git", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env", "env1",
    "site-packages", "dist", "build", "out", "target", ".idea", ".vscode", ".next",
    ".nuxt", ".gradle", ".cache", ".pytest_cache", ".mypy_cache", ".tox", "vendor",
    "coverage", ".sass-cache", "bower_components",
)
GREP_MAX_HITS = int(os.getenv("HAOYUAN_GREP_MAX_HITS", "60"))
GREP_MAX_CHARS = int(os.getenv("HAOYUAN_GREP_MAX_CHARS", "4000"))
FILE_READ_CACHE = True

VERIFY_GATE = os.getenv("HAOYUAN_VERIFY_GATE", "1").strip() not in {"0", "false"}
VERIFY_MAX_NUDGE = int(os.getenv("HAOYUAN_VERIFY_MAX_NUDGE", "1"))
VERIFY_CMD_HINTS = (
    "pytest", "unittest", "npm test", "npm run test", "pnpm test", "yarn test",
    "go test", "cargo test", "mvn test", "gradle test", "dotnet test", "jest", "vitest",
    "mocha", "tox ", "nosetests", "ruff", "flake8", "pylint", "mypy", "tsc", "eslint",
    "npm run lint", "npm run build", "npm run typecheck", "vue-tsc", "prettier", "check",
    "validate", "assert",
)
VERIFY_WRITE_TOOLS = ("write_file", "edit_file", "apply_patch", "multi_edit", "delete_path", "move_path")
VERIFY_CODE_EXTS = (
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".java", ".kt", ".go", ".rs", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cs",
    ".rb", ".php", ".swift", ".scala", ".sh", ".bash", ".ps1", ".bat", ".cmd", ".sql",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".env", ".xml", ".html", ".css",
    ".scss", ".less", ".gradle", ".dockerfile",
)

SUBAGENT_ENABLED = os.getenv("HAOYUAN_SUBAGENT", "1").strip() not in {"0", "false"}
# 14 steps was not enough for a baseline audit; the subagent returned nothing and
# the parent re-did every read itself. 40 steps + 15 min handles a real recon task.
SUBAGENT_MAX_STEPS = int(os.getenv("HAOYUAN_SUBAGENT_MAX_STEPS", "40"))
SUBAGENT_TIMEOUT_SEC = float(os.getenv("HAOYUAN_SUBAGENT_TIMEOUT", "900"))
SUBAGENT_SUMMARY_CHARS = int(os.getenv("HAOYUAN_SUBAGENT_SUMMARY_CHARS", "6000"))

CHECKPOINT_ENABLED = os.getenv("HAOYUAN_CHECKPOINT", "1").strip() not in {"0", "false"}
# Save after every step by default: a service restart during a long task must not
# lose the last few minutes of work. Checkpoints replace the previous row, so the
# write cost is one small UPSERT per step.
CHECKPOINT_EVERY_STEPS = int(os.getenv("HAOYUAN_CHECKPOINT_EVERY", "1"))
AUTO_RESUME_ON_BOOT = os.getenv("HAOYUAN_AUTO_RESUME", "1").strip() not in {"0", "false"}
IDEMPOTENT_TOOLS = ("write_file", "edit_file", "apply_patch", "multi_edit", "delete_path", "move_path")
TOOL_ZOMBIE_GRACE_SEC = float(os.getenv("HAOYUAN_TOOL_ZOMBIE_GRACE", "5"))

LITE_MODE = os.getenv("HAOYUAN_LITE_MODE", "1").strip() not in {"0", "false"}
LITE_SINGLE_FILE_MAX_PATHS = 1
LITE_MULTIPHASE_HINTS = (
    "重构", "整个项目", "全量", "批量", "架构", "部署", "上线", "迁移", "端到端",
    "多个文件", "多文件", "完整系统", "平台", "并行", "工作流", "流水线", "全套",
    "微服务", "网页", "站点", "文档站", "可视化", "架构图", "大屏", "落地页",
    "设计系统", "响应式", "多页", "HTML", "页面", "报告", "方案", "预训练",
    "训练计划", "训练方案", "评估", "调研", "对比", "复盘", "审计",
)
LITE_TOOL_SET = (
    "read_file", "read_range", "search_symbol", "apply_patch", "edit_file", "write_file",
    "grep", "glob", "list_dir", "run_shell", "project_scan", "web_audit", "web_scaffold",
    "reference_digest", "reference_compare", "baseline_audit", "doc_consistency",
    "web_screenshot", "describe_image", "web_fetch", "ask_user", "task",
)
TOOL_SCHEMA_TRIM = os.getenv("HAOYUAN_TOOL_SCHEMA_TRIM", "1").strip() not in {"0", "false"}
TWO_PHASE_PLAN = True

REPO_INDEX_MAX_FILES = int(os.getenv("HAOYUAN_REPO_INDEX_MAX_FILES", "6000"))
REPO_INDEX_TIME_BUDGET = float(os.getenv("HAOYUAN_REPO_INDEX_TIME_BUDGET", "8"))
REPO_INDEX_CODE_EXTS = (".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")
REPO_MAP_MAX_TOKENS = int(os.getenv("HAOYUAN_REPO_MAP_MAX_TOKENS", "2000"))
REPO_MAP_ENABLED = os.getenv("HAOYUAN_REPO_MAP", "1").strip() not in {"0", "false"}
SYMBOL_SEARCH_LIMIT = int(os.getenv("HAOYUAN_SYMBOL_SEARCH_LIMIT", "30"))
APPLY_PATCH_ENABLED = os.getenv("HAOYUAN_APPLY_PATCH", "1").strip() not in {"0", "false"}

REPAIR_LOOP_ENABLED = os.getenv("HAOYUAN_REPAIR_LOOP", "1").strip() not in {"0", "false"}
REPAIR_REPEAT_ESCALATE = int(os.getenv("HAOYUAN_REPAIR_REPEAT_ESCALATE", "2"))

# No-progress / anti-loop guards. A weak or degraded model can get stuck re-reading
# the same files forever (observed: 600+ identical read_range calls in one run).
# These guards detect repetition even while tool calls keep flowing, which the
# old "only check when the model stops calling tools" gate could never catch.
NO_PROGRESS_GUARD = os.getenv("HAOYUAN_NO_PROGRESS_GUARD", "1").strip() not in {"0", "false"}
# Identical (tool,args) calls allowed before the call is suppressed as a duplicate.
REPEAT_TOOL_LIMIT = int(os.getenv("HAOYUAN_REPEAT_TOOL_LIMIT", "2"))
# Reads of the same path allowed before further reads count as no progress.
REPEAT_READ_LIMIT = int(os.getenv("HAOYUAN_REPEAT_READ_LIMIT", "8"))
# Reads of the same path allowed before further reads are suppressed and answered
# with an authoritative digest instead. Exact-argument dedupe never fired because
# the model shifted start/end by a few lines on every call; path-level counting
# is what catches that.
LOOP_PATH_SUPPRESS_LIMIT = int(os.getenv("HAOYUAN_LOOP_PATH_SUPPRESS_LIMIT", "8"))
# The same assistant announcement ("I'll start by checking ...") repeated this many
# times within the recent window is treated as no progress even if tool args vary.
TEXT_PREFIX_REPEAT_LIMIT = int(os.getenv("HAOYUAN_TEXT_PREFIX_REPEAT_LIMIT", "3"))
TEXT_PREFIX_WINDOW = int(os.getenv("HAOYUAN_TEXT_PREFIX_WINDOW", "8"))
TEXT_PREFIX_CHARS = int(os.getenv("HAOYUAN_TEXT_PREFIX_CHARS", "48"))
# Consecutive steps with no new tool/read/write before the guard fires.
NO_PROGRESS_STREAK = int(os.getenv("HAOYUAN_NO_PROGRESS_STREAK", "2"))
# How many no-progress nudges before the run is terminated as stuck.
NO_PROGRESS_MAX = int(os.getenv("HAOYUAN_NO_PROGRESS_MAX", "2"))
# After this many steps without the requested deliverable, restrict the agent to
# write tools so it stops exploring and ships the file.
DELIVERY_DEADLINE_STEPS = int(os.getenv("HAOYUAN_DELIVERY_DEADLINE_STEPS", "60"))
# Wall-clock / prompt-token exploration budgets: a write task that has not produced
# the deliverable after either limit is switched to write-only mode. One observed
# run burned 67M prompt tokens in 38 minutes without a single write.
EXPLORATION_MAX_SEC = float(os.getenv("HAOYUAN_EXPLORATION_MAX_SEC", "1800"))
EXPLORATION_MAX_PROMPT_TOKENS = int(os.getenv("HAOYUAN_EXPLORATION_MAX_PROMPT_TOKENS", "20000000"))
# Hard cap on prompt tokens for one run, deliverable or not (0 disables).
RUN_MAX_PROMPT_TOKENS = int(os.getenv("HAOYUAN_RUN_MAX_PROMPT_TOKENS", "60000000"))
# How many times the harness may send the deliverable back for completeness fixes
# (dead anchors, missing sections) before the run is marked incomplete.
DELIVERY_AUDIT_NUDGE = int(os.getenv("HAOYUAN_DELIVERY_AUDIT_NUDGE", "2"))
# Minimum visible text for a generated HTML/markdown deliverable when no reference
# exists to compare against; with a reference the floor is a ratio of its size.
DELIVERY_MIN_VISIBLE_CHARS = int(os.getenv("HAOYUAN_DELIVERY_MIN_VISIBLE_CHARS", "2000"))
DELIVERY_MIN_REFERENCE_RATIO = float(os.getenv("HAOYUAN_DELIVERY_MIN_REFERENCE_RATIO", "0.5"))

# web_fetch: read-only HTTP GET for fact verification in research/plan tasks.
WEB_FETCH_ENABLED = os.getenv("HAOYUAN_WEB_FETCH", "1").strip() not in {"0", "false"}
WEB_FETCH_MAX_CHARS = int(os.getenv("HAOYUAN_WEB_FETCH_MAX_CHARS", "12000"))
WEB_FETCH_TIMEOUT = float(os.getenv("HAOYUAN_WEB_FETCH_TIMEOUT", "20"))
WEB_FETCH_MAX_BYTES = int(os.getenv("HAOYUAN_WEB_FETCH_MAX_BYTES", str(2 * 1024 * 1024)))

EVENT_FLUSH_INTERVAL = float(os.getenv("HAOYUAN_EVENT_FLUSH_INTERVAL", "0.4"))
EVENT_FLUSH_BATCH = int(os.getenv("HAOYUAN_EVENT_FLUSH_BATCH", "32"))
WS_SEND_QUEUE_MAX = int(os.getenv("HAOYUAN_WS_QUEUE_MAX", "2000"))
WS_SEND_TIMEOUT = float(os.getenv("HAOYUAN_WS_TIMEOUT", "5"))

SUPERVISOR_INTERVAL = float(os.getenv("HAOYUAN_SUPERVISOR_INTERVAL", "30"))
SUPERVISOR_STALE_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_STALE_SEC", "600"))
SUPERVISOR_AUTO_CANCEL_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_AUTO_CANCEL_SEC", "1800"))
# A run can emit events every second yet make no progress (same tool, same args).
# Treat that many identical recent tool calls as "stale" so the watchdog fires.
SUPERVISOR_NO_PROGRESS_REPEAT = int(os.getenv("HAOYUAN_SUPERVISOR_NO_PROGRESS_REPEAT", "8"))
SUPERVISOR_AUTO_RESUME = os.getenv("HAOYUAN_SUPERVISOR_AUTO_RESUME", "1").strip() not in {"0", "false"}
SUPERVISOR_RESUME_MAX = int(os.getenv("HAOYUAN_SUPERVISOR_RESUME_MAX", "1000"))
SUPERVISOR_RESUME_BACKOFF_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_RESUME_BACKOFF_SEC", "60"))
SUPERVISOR_RESUME_MAX_BACKOFF_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_RESUME_MAX_BACKOFF_SEC", "1800"))
SUPERVISOR_RESUME_KEYWORDS = (
    "max steps",
    "stale",
)

ORCH_ISOLATION = os.getenv("HAOYUAN_ORCH_ISOLATION", "worktree")
ORCH_MAX_TASKS = int(os.getenv("HAOYUAN_ORCH_MAX_TASKS", "12"))
ORCH_MAX_PARALLEL = int(os.getenv("HAOYUAN_ORCH_MAX_PARALLEL", "4"))
ORCH_BUDGET_SEC = int(os.getenv("HAOYUAN_ORCH_BUDGET_SEC", "7200"))
ORCH_PORT_BASE = int(os.getenv("HAOYUAN_ORCH_PORT_BASE", "8300"))
ORCH_PORT_STRIDE = int(os.getenv("HAOYUAN_ORCH_PORT_STRIDE", "5"))
ORCH_WORKTREE_DIR = ".haoyuan/wt"
ORCH_BRANCH_PREFIX = "haoyuan/"
ORCH_CONTRACT_FILE = ".haoyuan/CONTRACT.md"
ORCH_BLACKBOARD_FILE = ".haoyuan/BLACKBOARD.md"

PLAN_TEMPLATES_DIR = DATA_DIR / "plan_templates"
