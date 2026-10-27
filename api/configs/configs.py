from __future__ import annotations

import os
from pathlib import Path

from configs.models import auto_default

APP_NAME = "HaoYuan"
APP_VERSION = "1.0.0"
SERVER_HOST = os.getenv("HAOYUAN_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("HAOYUAN_PORT", "8030"))
prefix = "/api"

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
PLUGIN_CENTER_URL = os.getenv("HAOYUAN_PLUGIN_CENTER_URL", "http://127.0.0.1:8180").rstrip("/")
PLUGIN_PACKAGE_MAX_BYTES = int(os.getenv("HAOYUAN_PLUGIN_PACKAGE_MAX_BYTES", str(20 * 1024 * 1024)))

DEFAULT_PROVIDER, DEFAULT_MODEL = auto_default()
DEFAULT_AGENT = os.getenv("HAOYUAN_DEFAULT_AGENT", "coding")
DEFAULT_TENANT_ID = os.getenv("HAOYUAN_TENANT_ID", "default")
DEFAULT_USER_ID = os.getenv("HAOYUAN_USER_ID", "local")

MAX_CONCURRENT_SESSIONS = int(os.getenv("HAOYUAN_MAX_CONCURRENT", "5"))
AGENT_MAX_STEPS = int(os.getenv("HAOYUAN_MAX_STEPS", "30"))
MAX_AUTO_ROLLOVER = int(os.getenv("HAOYUAN_MAX_ROLLOVER", "3"))
GATE_CONFIRM_TIMEOUT = float(os.getenv("HAOYUAN_GATE_TIMEOUT", "600"))
AUTO_APPROVE_HIGH_RISK = os.getenv("HAOYUAN_AUTO_APPROVE", "0").strip() in {"1", "true", "yes"}

LLM_CONNECT_TIMEOUT = float(os.getenv("HAOYUAN_LLM_CONNECT_TIMEOUT", "20"))
LLM_FIRST_CHUNK_TIMEOUT = float(os.getenv("HAOYUAN_LLM_FIRST_CHUNK_TIMEOUT", "90"))
LLM_STREAM_IDLE_TIMEOUT = float(os.getenv("HAOYUAN_LLM_STREAM_IDLE_TIMEOUT", "60"))
LLM_TOTAL_TIMEOUT = float(os.getenv("HAOYUAN_LLM_TOTAL_TIMEOUT", "900"))
TOOL_TIMEOUT_SEC = float(os.getenv("HAOYUAN_TOOL_TIMEOUT", "300"))
TOOL_HEARTBEAT_SEC = float(os.getenv("HAOYUAN_TOOL_HEARTBEAT", "15"))
SHELL_TIMEOUT = float(os.getenv("HAOYUAN_SHELL_TIMEOUT", "120"))

TOOL_RESULT_MAX_BYTES = int(os.getenv("HAOYUAN_TOOL_RESULT_MAX_BYTES", str(8 * 1024)))
TOOL_RESULT_CONTEXT_CHARS = int(os.getenv("HAOYUAN_TOOL_RESULT_CONTEXT_CHARS", "6000"))
TOOL_RESULT_CONTEXT_MARK = "\n...[result truncated; re-read the precise range if needed]"

CONTEXT_COMPACT_TOKENS = int(os.getenv("HAOYUAN_CONTEXT_COMPACT_TOKENS", "32000"))
CONTEXT_KEEP_RECENT = int(os.getenv("HAOYUAN_CONTEXT_KEEP_RECENT", "10"))
CONTEXT_SUMMARY_MAX_CHARS = int(os.getenv("HAOYUAN_CONTEXT_SUMMARY_MAX_CHARS", "2400"))
MID_COMPACT_EVERY = int(os.getenv("HAOYUAN_MID_COMPACT_EVERY", "8"))
MID_COMPACT_TOKENS = int(os.getenv("HAOYUAN_MID_COMPACT_TOKENS", "24000"))
MID_COMPACT_MIN_MSGS = int(os.getenv("HAOYUAN_MID_COMPACT_MIN_MSGS", "14"))
TOOL_AGING_KEEP = int(os.getenv("HAOYUAN_TOOL_AGING_KEEP", "4"))
TOOL_AGING_CHARS = int(os.getenv("HAOYUAN_TOOL_AGING_CHARS", "300"))
CONTEXT_HARD_LIMIT = int(os.getenv("HAOYUAN_CONTEXT_HARD_LIMIT", "96000"))
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
SUBAGENT_MAX_STEPS = int(os.getenv("HAOYUAN_SUBAGENT_MAX_STEPS", "14"))
SUBAGENT_TIMEOUT_SEC = float(os.getenv("HAOYUAN_SUBAGENT_TIMEOUT", "480"))
SUBAGENT_SUMMARY_CHARS = int(os.getenv("HAOYUAN_SUBAGENT_SUMMARY_CHARS", "3000"))

CHECKPOINT_ENABLED = os.getenv("HAOYUAN_CHECKPOINT", "1").strip() not in {"0", "false"}
AUTO_RESUME_ON_BOOT = os.getenv("HAOYUAN_AUTO_RESUME", "1").strip() not in {"0", "false"}
IDEMPOTENT_TOOLS = ("write_file", "edit_file", "apply_patch", "multi_edit", "delete_path", "move_path")
TOOL_ZOMBIE_GRACE_SEC = float(os.getenv("HAOYUAN_TOOL_ZOMBIE_GRACE", "5"))

LITE_MODE = os.getenv("HAOYUAN_LITE_MODE", "1").strip() not in {"0", "false"}
LITE_SINGLE_FILE_MAX_PATHS = 1
LITE_MULTIPHASE_HINTS = (
    "重构", "整个项目", "全量", "批量", "架构", "部署", "上线", "迁移", "端到端",
    "多个文件", "多文件", "完整系统", "平台", "并行", "工作流", "流水线", "全套",
    "微服务", "网页", "站点", "文档站", "可视化", "架构图", "大屏", "落地页",
    "设计系统", "响应式", "多页",
)
LITE_TOOL_SET = (
    "read_file", "read_range", "search_symbol", "apply_patch", "edit_file", "write_file",
    "grep", "glob", "list_dir", "run_shell", "project_scan", "web_audit", "web_scaffold",
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

EVENT_FLUSH_INTERVAL = float(os.getenv("HAOYUAN_EVENT_FLUSH_INTERVAL", "0.4"))
EVENT_FLUSH_BATCH = int(os.getenv("HAOYUAN_EVENT_FLUSH_BATCH", "32"))
WS_SEND_QUEUE_MAX = int(os.getenv("HAOYUAN_WS_QUEUE_MAX", "2000"))
WS_SEND_TIMEOUT = float(os.getenv("HAOYUAN_WS_TIMEOUT", "5"))

SUPERVISOR_INTERVAL = float(os.getenv("HAOYUAN_SUPERVISOR_INTERVAL", "30"))
SUPERVISOR_STALE_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_STALE_SEC", "600"))
SUPERVISOR_AUTO_CANCEL_SEC = float(os.getenv("HAOYUAN_SUPERVISOR_AUTO_CANCEL_SEC", "1800"))
SUPERVISOR_AUTO_RESUME_KEYWORDS = ("服务重启", "中断", "restart", "interrupted")

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
