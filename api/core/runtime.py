from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from configs.configs import (
    AGENT_MAX_STEPS,
    AGENT_MAX_RUN_SEC,
    AGENT_MAX_TOTAL_STEPS,
    APPLY_PATCH_ENABLED,
    ARTIFACTS_DIR,
    CHECKPOINT_ENABLED,
    CHECKPOINT_EVERY_STEPS,
    CONTEXT_PACK_MAX_CHARS,
    DEFAULT_AGENT,
    DELIVERY_AUDIT_NUDGE,
    DELIVERY_DEADLINE_STEPS,
    DELIVERY_MIN_REFERENCE_RATIO,
    DELIVERY_MIN_VISIBLE_CHARS,
    EXPLORATION_MAX_PROMPT_TOKENS,
    EXPLORATION_MAX_SEC,
    IDEMPOTENT_TOOLS,
    LITE_MODE,
    LITE_MULTIPHASE_HINTS,
    LITE_SINGLE_FILE_MAX_PATHS,
    LITE_TOOL_SET,
    LOOP_PATH_SUPPRESS_LIMIT,
    NO_PROGRESS_GUARD,
    NO_PROGRESS_MAX,
    NO_PROGRESS_STREAK,
    REPEAT_READ_LIMIT,
    REPEAT_TOOL_LIMIT,
    REPAIR_LOOP_ENABLED,
    REPO_MAP_ENABLED,
    RUN_MAX_PROMPT_TOKENS,
    SHELL_TIMEOUT_MAX,
    SUBAGENT_ENABLED,
    SUBAGENT_MAX_STEPS,
    SUBAGENT_SUMMARY_CHARS,
    SUBAGENT_TIMEOUT_SEC,
    TEXT_PREFIX_CHARS,
    TEXT_PREFIX_REPEAT_LIMIT,
    TEXT_PREFIX_WINDOW,
    TOOL_COMPRESS_MIN_CHARS,
    TOOL_LOGS_DIR,
    TOOL_RESULT_CONTEXT_CHARS,
    TOOL_RESULT_CONTEXT_MARK,
    TOOL_SCHEMA_TRIM,
    TWO_PHASE_PLAN,
    VERIFY_CODE_EXTS,
    VERIFY_CMD_HINTS,
    VERIFY_GATE,
    VERIFY_MAX_NUDGE,
)
from configs.models import PROVIDERS, THINKING_OFF_PROVIDERS, effective_default_model, resolve
from core.context import compress_tool_output
from core.contracts import ToolCall, ToolContext, ToolResult
from core.instructions import addition_message, classify_instruction, interrupt_message, interrupt_notice
from harness import deliverable as deliverable_check
from harness import durability, reference, repair, repoindex, sysinfo, vision
from harness.skills import SkillLibrary

TERMINAL_STATUSES = {"done", "error", "cancelled"}

COMPLEX_HINTS = (
    "实现", "开发", "重构", "修复", "调试", "排错", "排查", "部署", "上线", "迁移", "接入", "集成",
    "架构", "设计", "优化", "性能", "安全", "数据库", "接口", "算法", "并发", "缓存", "测试", "方案",
    "计划", "规划", "分析", "调研", "评估", "对比", "整个项目", "全量", "批量", "自动化", "脚本",
    "爬虫", "定时", "视频", "音频", "渲染", "剪辑", "字幕", "导出", "水印", "合成", "构建", "网页",
    "站点", "文档站", "可视化", "架构图", "大屏", "落地页", "设计系统", "响应式",
)
SIMPLE_HINTS = (
    "你好", "谢谢", "在吗", "是什么", "什么是", "什么意思", "解释一下", "介绍一下", "总结一下",
    "翻译", "区别", "为什么", "怎么写", "怎么用", "报错什么意思", "格式化", "改写",
)
DEBUG_HINTS = (
    "修复", "修一下", "修好", "缺陷", "报错", "失败", "调试", "排查", "定位问题", "跑不过",
    "测试不过", "failing", "fix", "bug", "debug", "error", "regression",
)
TERMINAL_HINTS = ("命令", "终端", "环境", "安装", "部署", "启动服务", "docker", "install", "deploy", "setup", "shell")
REPORT_HINTS = ("报告", "分析", "总结", "方案", "计划书", "调研", "report", "analysis")
WEB_ARTIFACT_INTENT = (
    "html", "htm", "css", "javascript", "typescript", "vue", "react", "svelte",
    "网页", "页面", "网站", "站点", "前端", "代码", "程序",
)
CODE_WORK_INTENT = (
    "修复", "修一下", "修好", "调试", "排查", "定位问题", "跑不过", "测试不过", "报错",
    "bug", "debug", "regression", "failing",
)
_PLAN_INTENT_RE = re.compile(r"(写|生成|做|出|制定|策划|规划).{0,10}(方案|计划书|计划|报告)|商业计划|调研报告|可行性分析|方案计划书")
_PATH_RE = re.compile(
    r"[\w./\\-]+\.(py|js|ts|tsx|vue|java|go|rs|c|cpp|h|hpp|json|ya?ml|toml|md|sql|sh|bat|ps1|css|html)\b",
    re.I,
)
# Research/evaluation deliverables need the full toolset even when the router
# considers them "normal": subagents, reference diffing, baseline evidence and
# high reasoning are part of the task, not optional polish. Lite mode used to
# swallow exactly those capabilities.
_RESEARCH_HINTS = re.compile(
    r"预训练|训练计划|训练方案|技术方案|方案计划|实施方案|解决方案|可行性|调研|评估|对比|复盘|审计|评审|报告|"
    r"benchmark|feasibility|survey|research|postmortem|audit",
    re.I,
)
_CODE_RE = re.compile(r"(^|\n)\s*(def |class |function |import |from |const |let |var |public |private |func |package |interface |async )")
_NEGATION_RE = re.compile(r"(?:不要|无需|不用|不必|禁止|别)[^。；;！!\n]{0,24}")
_SMALLTALK_RE = re.compile(
    r"^("
    r"(?:你|您)+好|哈喽|哈啰|嗨|(?:hi|hello|hey)(?:\s+there)?|howdy|在吗|在不在|在么|"
    r"早上好|中午好|下午好|晚上好|早安|晚安|good\s+(?:morning|afternoon|evening|night)|"
    r"最近(?:怎么样|好吗|如何|咋样|忙吗|在干嘛)|这几天(?:怎么样|好吗|如何)|今天(?:怎么样|好吗|如何)|还好吗|在干嘛|忙吗|"
    r"how\s+are\s+you(?:\s+doing)?|how's\s+it\s+going|nice\s+to\s+meet\s+you|"
    r"谢谢(?:你|您)?|感谢(?:你|您)?|多谢|辛苦了|thanks|thank you|thx|3q|再见|拜拜|bye|goodbye|"
    r"你是谁|你是哪位|你叫什么(?:名字)?|你的名字(?:是)?(?:什么|啥)?|你是什么|你能做什么|你会做什么|"
    r"你能干什么|你会干什么|你会啥|你的能力(?:是什么|如何|怎么样)?|介绍一下你自己|自我介绍|介绍下你自己|"
    r"嗯|哦|噢|好的|好|行|ok|okay|收到|明白|了解|哈哈|嘿嘿|嘻嘻"
    r")[呀啊哦吧啦呢嘛哈哟了吗呗喔的~～!！。，,.?？…\s]*$",
    re.I,
)
_QA_START_RE = re.compile(r"^(?:请问|可以|能不能|能否|可不可以|是否|如何|怎么|怎样|为什么|为啥|什么|哪些|哪个|多少|多久|会不会|有没有|要不要|该不该|是不是|how|what|why|which|who|when|where|can|could|is|are|do|does|should|would)", re.I)
_REQUEST_MARK_RE = re.compile(r"(?:帮我|帮忙|请你|麻烦你|给我|替我|代为|执行一下|开始做|直接做|help\s+(?:me|us))", re.I)
# Data / finance / quantitative questions look like short "general questions" but
# are real work: they need live data (web_fetch / run_shell) and arithmetic, not
# a chat reply. Treat them as tasks so intent routing cannot switch the tools off.
_DATA_QUERY_RE = re.compile(
    r"计算|算一下|算算|测算|估算|统计|回测|"
    r"盈利|亏损|盈亏|收益|利润|回报|赚了|亏了|涨了|跌了|"
    r"股价|行情|报价|市值|汇率|利率|收益率|估值|市盈率|净值|"
    r"买入|卖出|持仓|仓位|投资|定投|复利|年化|"
    r"交易日|交易情况|成交|开盘价|收盘价|走势|涨跌|涨停|跌停|"
    r"股票|基金|债券|期货|港股|美股|比特币|加密货币|币价|"
    r"数据集|百分比|占比|平均值|中位数|增长率|同比|环比|"
    r"\b(?:stock|share\s+price|cagr|revenue|profit|loss|drawdown|backtest|portfolio|"
    r"calculate|compute|statistics|percentage|benchmark)\b",
    re.I,
)

CHAT_ACTION_HINTS = (
    "帮我", "帮忙", "请你", "麻烦你", "给我", "替我", "代为",
    "执行", "运行", "启动", "停止", "重启", "关闭", "安装", "部署", "构建", "编译",
    "测试", "修复", "修改", "改成", "改一下", "改下", "调整", "替换", "换成", "重构", "实现", "开发",
    "创建", "新建", "编写", "写入", "写个", "写一个", "写一下", "添加", "增加", "加上", "补上", "删除",
    "移除", "删掉", "去掉", "重命名", "移动", "复制", "处理", "弄", "搞", "做个", "做一个", "做一下",
    "查看", "看看", "看一下", "读取", "打开", "列出", "搜索", "查找", "查一下", "检查", "定位", "分析",
    "审查", "评审", "优化", "调试", "排查", "提交", "回滚", "合并", "拉取", "推送", "生成", "设计",
    "规划", "继续", "接着", "下一步", "往下", "开始",
    "change", "adjust", "replace", "tweak", "improve",
    "write", "create", "add", "implement", "fix", "debug", "refactor", "update", "modify", "delete",
    "remove", "rename", "move", "copy", "run", "execute", "build", "compile", "test", "install",
    "deploy", "start", "stop", "restart", "open", "read", "list", "search", "find", "show", "check",
    "analyze", "review", "optimize", "generate", "design", "plan", "commit", "push", "pull", "merge",
    "continue", "proceed",
)
CHAT_CONTEXT_HINTS = (
    "项目", "仓库", "代码", "文件", "目录", "工作区",
    "日志", "分支", "配置", "函数", "模块", "页面", "前端", "后端", "脚本", "命令",
    "project", "repo", "code", "file", "directory", "workspace",
    "branch", "config", "function", "module", "page",
    "frontend", "backend", "script", "command", "error", "bug",
)

READONLY_TOOLS = (
    "read_file", "read_range", "search_symbol", "glob", "grep", "list_dir", "project_scan",
    "baseline_audit", "doc_consistency", "web_screenshot", "describe_image",
    "reference_digest", "reference_compare", "web_audit", "web_fetch",
)
# Tools whose only argument of interest is a file path; loop detection counts
# these per path instead of per exact argument (shifting start/end by a few lines
# used to produce a fresh fingerprint on every call and evade the guard).
_PATH_READ_TOOLS = frozenset({"read_file", "read_range", "reference_digest", "reference_compare", "list_dir"})
# Read-only tools plus shell commands are safe to de-duplicate: re-running the exact
# same command with the same args yields nothing new (observed: the model re-running
# one `python -c` budget calculation 20+ times).
_DUPLICATE_TOOLS = frozenset(READONLY_TOOLS) | {"run_shell"}

# Shell commands that materialise workspace files. A task can be completed entirely
# through the shell (heredoc, redirect, python -c, tee ...), so these writes must be
# tracked exactly like write_file/edit_file. Otherwise the write/verify gates keep
# nudging the model to "actually modify the workspace" after it already finished,
# which costs extra steps and tokens without improving the outcome.
_SHELL_WRITE_RE = re.compile(
    r"(?:^|[;&|]\s*)>{1,2}(?!&|\s*/dev/null)\s*\S|"
    r"\btee\b|\bcp\b|\bmv\b|\btouch\b|\bmkdir\b|\bsed\s+-i\b|\bdd\b|"
    r"\bopen\([^)]*['\"][wax]+|\bwrite_text\(|\bwrite_bytes\(|"
    r"\bto_csv\(|\bto_json\(|\bto_parquet\(|\bjson\.dump\(|\byaml\.dump\(|\bsavefig\(|"
    r"\bnp\.save|\bpd\.to_|\bshutil\.copy|\bshutil\.move",
    re.I,
)
# Interpreted languages: running the script the agent just wrote counts as a real
# verification step, even when no test/lint/build command is involved.
_SCRIPT_RUN_RE = re.compile(
    r"\b(?:python3?|pytest|node|deno|bun|ruby|perl|php|bash|sh|go\s+run|cargo\s+run|"
    r"java|dotnet\s+run|Rscript)\b",
    re.I,
)
_WEB_TOOL_RE = re.compile(
    r"\.(?:html?|css|scss|sass|less|vue|svelte|jsx|tsx)\b|"
    r"\b(?:html|css|web|frontend|front-end|website|landing|page|responsive|react|vue|svelte)\b|"
    r"网页|页面|站点|网站|前端|响应式|落地页|设计系统|大屏|参考页|参考文件",
    re.I,
)


def shell_wrote_files(command: str) -> bool:
    return bool(command and _SHELL_WRITE_RE.search(command))


def looks_like_verification(command: str) -> bool:
    lowered = (command or "").lower()
    if any(hint in lowered for hint in VERIFY_CMD_HINTS):
        return True
    return bool(_SCRIPT_RUN_RE.search(command or ""))


def wants_web_tools(text: str) -> bool:
    return bool(_WEB_TOOL_RE.search(text or ""))


_DOC_TEXT_RE = re.compile(r"简历|resume|\bcv\b|求职|报告|提案|文档|自荐|cover\s+letter|portfolio", re.I)
_DEBUG_TEXT_RE = re.compile(r"修复|调试|报错|失败|排查|\bbug\b|\berror\b|pytest|测试不过|regression|failing", re.I)


_DOC_TARGET_EXTS = (".html", ".htm", ".md")


def wants_document_workflow(text: str, write_required: bool, kind: str, output_targets: list[str]) -> bool:
    """True for plan/report/page deliverables, false for code changes.

    Such tasks need the document workflow and the research protocol, not the
    coding protocol; the request is about producing a document, not changing
    repository code.
    """
    if not write_required or kind == "general" or is_casual_chat(text or ""):
        return False
    if kind == "plan":
        return True
    if any(hint in (text or "") for hint in CODE_WORK_INTENT) or _CODE_RE.search(text or ""):
        return False
    research = bool(_RESEARCH_HINTS.search(text or "")) or wants_web_tools(text or "")
    for target in output_targets:
        lowered = target.lower()
        if lowered.endswith(_DOC_TARGET_EXTS):
            return True
        # A bare directory is a document target only for plan/report/page work;
        # "write the script into D:\proj\scripts" must stay a coding task.
        if os.path.isdir(target) and research:
            return True
    return research and wants_web_tools(text or "")


def relevant_skills(skills: list, text: str) -> list:
    """Drop domain skills that BM25 pulled in on incidental keyword overlap.

    web/document/debug playbooks are large; shipping them into every prompt for a
    plain repo or math task bloats each request and distracts the model.
    """
    web = wants_web_tools(text)
    doc = bool(_DOC_TEXT_RE.search(text or ""))
    debug = bool(_DEBUG_TEXT_RE.search(text or ""))
    kept = []
    for skill in skills:
        name = getattr(skill, "name", "")
        if name == "web-delivery" and not web:
            continue
        if name == "document-delivery" and not doc:
            continue
        if name == "debug-loop" and not debug:
            continue
        kept.append(skill)
    return kept


SYSTEM_RULES = """You are HaoYuan (豪源), an autonomous AI coding agent. You work directly in a real workspace and deliver verified changes.

# Operating rules
- Work autonomously. Do not ask for permission for read-only actions. For writes or commands, the system shows a preview and asks the user.
- Locate before editing: use search_symbol, grep, read_range, then apply the smallest possible patch.
- Inspect files with the dedicated tools (read_file/read_range/grep/glob/list_dir/search_symbol), not with shell cat/grep/find/head: they are faster, stay inside the workspace, and return cleaner context. Use run_shell mainly for builds, tests, git and commands that have no dedicated tool, and avoid scanning large binaries or sleeping to poll.
- Prefer apply_patch / edit_file / multi_edit over write_file. Never rewrite a whole file for a small change.
- When adding a proxy, wrapper or delegation method, forward *args and **kwargs unchanged and apply only the path/prefix transformation the task requires: `def m(self, *args, **kwargs): return self.inner.m(*args, **kwargs)`. Never redeclare the wrapped method's parameters such as `mode=...`, even if you know its signature; hidden callers may pass arbitrary positional arguments. Do not weaken or rewrite existing tests to fit your implementation.
- Large files: model output is capped, so never emit an entire big file in one tool call. Create it with write_file using a small skeleton, then append the remaining sections in chunks (<= 150 lines each) with apply_patch or edit_file. If a tool result says the arguments were truncated, split the write instead of retrying the same call. If a tool result says "[auto-continued]", the complete prefix was already saved to disk: keep appending from the reported line and never re-send or rewrite the saved part.
- Batch independent tool calls in the same assistant message. Reads can run in parallel; writes run in order.
- Verify code changes: run the project's tests/lint/build once after the final code edit. Documentation-only changes do not require a test run.
- Use the task tool for broad read-only reconnaissance when raw tool output would flood the context. It returns only conclusions.
- Use web_fetch to verify external facts you cannot find in the workspace (licenses, model specs, dataset sizes, API docs). If a fetch fails, label the fact as unverified instead of guessing.
- Use plan_task for multi-step work and update_plan as you progress.
- Match effort to size: a one-symbol fix needs no plan and no whole-repo scan; a multi-file feature needs a short plan and a checklist.
- Numeric fidelity: for a computed value, write full precision unless the task explicitly specifies rounding; never round intermediate results. If a task asks for a numeric value without specifying rounding, write at least 6 significant digits (e.g. 11.428571); never round to 2 decimal places by habit. Check units and axis semantics before computing (e.g. wavelength vs reciprocal-wavelength/Raman shift, log vs linear, encoded categories) and derive the coordinate the task actually names.
- Peak/curve fitting: use a window wide enough to include the baseline on both sides (about 10-20x the peak half-width), fit the background and peak together, and report the background evaluated at the peak center as offset; never take offset from a narrow window.
- Cap exploratory sweeps: after at most two variants of the same analysis/search, commit to the best one, verify it, and finish instead of running another sweep.
- Budget exploration by task type. For a single-symbol fix, commit after roughly 8 reads/searches. For a plan, report, audit or benchmark, read the baseline evidence set first (README, model card, changelog, every stage summary, data-quality/license registry and the real pipeline scripts); do not start writing until the evidence table is complete. Never re-read an unchanged range you already have.
- For research deliverables, use baseline_audit to extract measured facts and doc_consistency to catch cross-section contradictions before finishing.
- Run the project's full verification command at most twice: once after the edit, and once more only if the first run failed and you changed code again. When it passes, stop testing and summarize.
- Never fabricate results. If something cannot be verified, say exactly what is unverified and why.
- Answer in the user's language. Be concise and outcome-oriented.
- If the user only greets you or makes casual conversation, reply naturally and do not inspect the workspace, call tools, or start a task.
- Do not run destructive commands, do not push to git, and do not touch files outside the workspace.
- When the user points at an existing file/page as the format or style source, treat it as a hard reference: call reference_digest, then reuse its palette, typography, layout width, breakpoints, components and interactions. Do not substitute a different built-in template. If a file path is given, never assume you already know its contents from memory.
- Preserve the existing artifact unless the user explicitly asks for a redesign. When a target file already exists, edit it in place and keep its markup, CSS, layout system, section order and naming exactly as they are except for the diff the request requires. Never re-theme, restructure, renumber or "polish" on your own initiative; style/format changes require an explicit user request.
- Deliver only what was asked. Do not add unrequested sections, scaffolding, commentary, checklists, FAQs, interview prep or meta-analysis. For outward-facing documents (resume/CV, cover letter, proposal, report), match the stated audience and keep internal notes, job-description mapping and Q&A material out unless the user explicitly asks for them. For analytical or evaluation deliverables (feasibility study, audit, benchmark report), completeness is part of the request: include assumptions, risks, alternatives, acceptance gates and a summary, but no off-topic padding.
- When a decision, missing detail, or risk check blocks safe progress mid-task, call ask_user with one clear question and 2-4 short options instead of ending your turn. Execution pauses, the user answers, and you continue the same task with that answer. Do not ask for confirmation you do not need.

# Mid-task additions
The user may send new requirements while you are still working. Treat them as parallel workstreams:
- Acknowledge the addition briefly, then judge priority yourself. Urgent or blocking additions come first; keep lower-priority work queued.
- Preserve the original task and all completed progress. Never discard it just because a new requirement arrived.
- Only stop the original task when the user explicitly asks to interrupt, cancel, or replace it.
- If one workstream is blocked on a command, approval, or missing information, advance the other one instead of idling.
- If a plan is active, add the new requirement as a step without erasing completed steps.
"""


RESEARCH_RULES = """# Research and evaluation protocol (plans, reports, audits, benchmarks)
- Before writing, build a baseline evidence table: claim | value | source (file:line or JSON field) | measured/planned.
- Read the baseline project's README, MODEL_CARD, CHANGELOG, reports/*/summary.json, data-quality and license registries, and the real training/serving scripts. A single README headline is not enough.
- Separate the stable release from commercial or experimental branches. Never mix their metrics in one baseline row.
- For data facts (speaker count, gender, hours, license), read the data card or license registry. If a fact is not in the repository, label it as an assumption and state how it will be verified.
- Inventory reusable assets (checkpoints, aligned manifests, vocoders, tokenizers, exports) and mark each as reuse / rebuild / discard.
- Use baseline_audit (baseline directory) to pull measured facts, and doc_consistency (plan file + optional baseline) before finishing. Fix every contradiction instead of hiding it in prose.
- Before finalizing, run a cross-section consistency check: the same entity's numbers and attributes must agree everywhere.
- In the final report, list measured numbers with their source, and label planned numbers explicitly.
"""

DOCUMENT_RULES = """# Document delivery workflow (plans, reports, audits, reference-styled pages)
Follow the steps in order and never loop back to an earlier one:
1. Reference: call reference_digest ONCE per reference file; use read_range only for blocks the digest does not cover. After that the reference is known: do not re-read it, and do not re-check the output directory state.
2. Evidence: call baseline_audit once per baseline project, then read the specific report files it points to. Record every number with its source path. Use web_fetch for external facts you cannot find locally; when a fetch fails, label the fact "unverified" instead of guessing.
3. Decide the plan (architecture, data, stages, budget, gates) in your reasoning before writing anything.
4. Compute budgets with one run_shell python snippet. If the numbers change the plan, update the plan; do not rewrite the snippet more than twice.
5. Write the skeleton: one write_file with the full <style> block copied verbatim from the reference, both navs listing every section id, and the header. Do NOT write </body></html> yet. Then append the sections one at a time (<= 150 lines per apply_patch/edit_file), in order, and add the closing tags only after the last section.
6. Validate: run web_audit (with the reference path) and doc_consistency on the finished page and fix every dead anchor and contradiction. The harness refuses to mark the task done while navigation anchors have no target, the page has no closing tag, or its visible text is a fraction of the reference's length.
7. Finish with a short summary. Do not end the turn to "confirm" anything; the task is unattended.
"""


def estimate_complexity(text: str, plan_active: bool = False) -> str:
    text = (text or "").strip()
    if not text:
        return "normal"
    score = 0
    if len(text) > 280:
        score += 2
    elif len(text) > 80:
        score += 1
    if "```" in text or _CODE_RE.search(text):
        score += 2
    if _PATH_RE.search(text):
        score += 1
    hits = sum(1 for hint in COMPLEX_HINTS if hint in text)
    if hits:
        score += 2 + min(hits - 1, 2)
    if any(hint in text.lower() for hint in ("refactor", "implement", "debug", "deploy", "optimize", "migrate", "architecture")):
        score += 2
    if len(text) < 60 and any(hint in text for hint in SIMPLE_HINTS):
        score -= 1
    if plan_active:
        score += 3
    if score >= 3:
        return "complex"
    if score <= 0:
        return "simple"
    return "normal"


def detect_task_type(text: str) -> str:
    lowered = (text or "").lower()
    if any(hint in lowered for hint in DEBUG_HINTS):
        return "debug"
    if any(hint in lowered for hint in TERMINAL_HINTS):
        return "terminal"
    if any(hint in lowered for hint in REPORT_HINTS) and not _PATH_RE.search(text or ""):
        return "report"
    return "dev"


def detect_kind(text: str) -> str:
    lowered = (text or "").lower()
    # Explicit code/web artifacts must win over incidental keyword matches: a
    # task that only mentions a video while publishing, or that references an
    # HTML page, is a coding task. Otherwise it is routed to the read-only
    # plan agent and can never write the requested file.
    if any(hint in lowered for hint in WEB_ARTIFACT_INTENT):
        return "dev"
    if _PLAN_INTENT_RE.search(text or "") and not _PATH_RE.search(text or ""):
        return "plan"
    if any(hint in lowered for hint in CODE_WORK_INTENT):
        return "dev"
    return "dev"


def is_smalltalk(text: str) -> bool:
    value = (text or "").strip()
    if not value or len(value) > 30:
        return False
    if any(hint in value for hint in COMPLEX_HINTS):
        return False
    return bool(_SMALLTALK_RE.match(value))


def is_question(text: str) -> bool:
    value = (text or "").strip()
    if is_smalltalk(value):
        return True
    if _REQUEST_MARK_RE.search(value):
        return False
    return bool(_QA_START_RE.match(value)) and not _PATH_RE.search(value)


def is_data_query(text: str) -> bool:
    """True for finance/data/compute questions that need real tools, not chat."""
    return bool(_DATA_QUERY_RE.search(text or ""))


def is_casual_chat(text: str) -> bool:
    """Detect greetings, social chat and general questions that need no workspace work."""
    value = (text or "").strip()
    if not value:
        return False
    if is_smalltalk(value):
        return True
    if is_data_query(value):
        return False
    if len(value) > 80:
        return False
    if _PATH_RE.search(value) or _CODE_RE.search(value):
        return False
    lowered = value.lower()
    if any(hint in value for hint in CHAT_ACTION_HINTS):
        return False
    if any(hint in value for hint in COMPLEX_HINTS):
        return False
    if any(hint in lowered for hint in DEBUG_HINTS + TERMINAL_HINTS):
        return False
    if any(hint in lowered for hint in CHAT_CONTEXT_HINTS):
        return False
    return not _REQUEST_MARK_RE.search(value)


SPEC_AUDIT_HINTS = (
    "要求", "必须", "不得", "禁止", "保留", "兼容", "边界", "并发", "幂等", "原子",
    "默认", "补齐", "严格", "所有", "每个", "至少", "不能", "不要修改", "无损",
    "不一致", "超时", "重试", "熔断", "校验",
)


HARD_AUDIT_HINTS = (
    "并发", "幂等", "熔断", "重试", "线程", "事务", "回滚", "版本", "严格", "确定性", "竞态", "超时",
)


def needs_spec_audit(text: str, level: str, workspace: bool, kind: str, qa: bool) -> bool:
    if not workspace or qa or kind not in ("dev", "coding") or level != "complex":
        return False
    value = text or ""
    lowered = value.lower()
    if "版本" not in value and "schema" not in lowered and "migration" not in lowered:
        return False
    return sum(1 for hint in SPEC_AUDIT_HINTS if hint in value) >= 2


READ_ONLY_HINTS = (
    "不要修改", "只读", "仅分析", "只分析", "分析一下", "解释", "审查", "评审", "评估",
    "review", "explain", "analyze", "analysis",
)


def needs_write(text: str, qa: bool, kind: str, workspace: bool) -> bool:
    if not workspace or qa or kind not in ("dev", "coding") or is_casual_chat(text):
        return False
    value = (text or "").lower()
    # A pure data/compute question is research, not a code change. Only require a
    # deliverable when the user names an explicit output path.
    if is_data_query(text) and not _OUTPUT_HINT_RE.search(text or ""):
        return False
    return not any(hint in value for hint in READ_ONLY_HINTS)


_OUTPUT_HINT_RE = re.compile(
    # The path must sit in the same clause as the hint keyword: "输出…方案，开发项目的代码目录路径：D:\x"
    # used to register the code directory as a second deliverable.
    # ``gap`` is kept separately so a reference/previous-plan link can be
    # distinguished from a real destination.
    r"(?:输出|保存|写到|写入|生成|交付|放到|存到|放在|导出|output|save|write|deliver)"
    r"(?P<gap>[^\n，,。；;]{0,40}?)"
    r"(?P<path>(?:[A-Za-z]:[\\/]|/)[^\s\"'<>|，。；、）】]+)",
    re.I,
)

# A ``file:///`` URI in the same clause as an output verb is often a reference
# or a previous plan, not a destination. Bare local paths are treated less
# aggressively: "输出训练计划：D:\x" is a real output even though it says 计划.
_URI_REFERENCE_GAP_RE = re.compile(r"(参考|参照|仿照|沿用|风格|模板|已完成|已经完成|计划书|计划)", re.I)
_LOCAL_REFERENCE_GAP_RE = re.compile(r"(参考|参照|仿照|沿用|风格|模板|已完成|已经完成|计划书)", re.I)
_DESTINATION_GAP_RE = re.compile(
    r"(到|至|为|是|保存|输出|写入|写到|生成|交付|放到|存到|放在|导出|output|save|write|deliver)",
    re.I,
)
_DUPLICATE_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]+([A-Za-z]:[\\/].*)$")

_BUDGET_RE = re.compile(
    r"(?:总训练时间|总时间|合计|总共|total)[^\n。；;]{0,24}?"
    r"(?:不超过|≤|<=|最多|under|within)\s*(\d+(?:\.\d+)?)\s*(?:小时|h|hours?)",
    re.I,
)


def budget_contract(text: str) -> str:
    match = _BUDGET_RE.search(text or "")
    if not match:
        return ""
    hours = match.group(1)
    lines = [
        "\n\n# Hard task contract (must obey)",
        f"- The TOTAL training wall time for ALL targets combined must be <= {hours} hours. "
        "This is a total budget, not a per-model budget. The budget table's 合计 row must be <= the total.",
        "- If the sum exceeds the total, reduce parameters/data to the smallest viable sizes; never reinterpret the budget as per-model.",
        "- Start from the smallest viable model (aim for <=150M trainable params and <=2B tokens per target where the gate allows); only scale up when a named gate cannot be met. Cloud is the last resort.",
        "- Use one effective TFLOPS constant per card and include a self-check table whose 合计 equals the sum and is <= the total.",
    ]
    try:
        if float(hours) <= 60:
            lines.append(
                f"- With a {hours}h total across all targets, expect small models (roughly 40-120M trainable params "
                "and 0.5-1.5B tokens per target). If your plan is larger, it cannot fit the total; shrink it before writing."
            )
    except ValueError:
        pass
    return "\n".join(lines) + "\n"


_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _normalize_output_target(raw: str) -> str | None:
    """Turn a matched path/URI into an absolute local path.

    Handles ``file:///D:/...`` and the ``e:///D:/...`` corruption produced when
    the ``e`` of ``file`` is mistaken for a drive letter. Windows drive paths
    are recognised explicitly because ``os.path.isabs`` does not treat them as
    absolute on POSIX.
    """
    value = (raw or "").strip().strip("'\"<>()[]{}，。；;、）】")
    if not value:
        return None
    if value.lower().startswith("file:///"):
        value = unquote(value[8:])
    duplicate = _DUPLICATE_DRIVE_RE.match(value)
    if duplicate:
        value = duplicate.group(1)
    if _DRIVE_PATH_RE.match(value):
        return os.path.normpath(value.replace("/", "\\"))
    return os.path.normpath(value) if os.path.isabs(value) else None


def extract_output_targets(text: str, workspace: str) -> list[str]:
    targets: list[str] = []
    for match in _OUTPUT_HINT_RE.finditer(text or ""):
        gap = match.group("gap") or ""
        raw = (match.group("path") or "").strip()
        is_uri = raw.lower().startswith(("file:///", "e:///"))
        reference_re = _URI_REFERENCE_GAP_RE if is_uri else _LOCAL_REFERENCE_GAP_RE
        if reference_re.search(gap) and not _DESTINATION_GAP_RE.search(gap):
            # "参考/已完成/计划：" links point at prior artifacts, not outputs.
            continue
        normalized = _normalize_output_target(raw)
        if normalized is None:
            continue
        full = os.path.normpath(normalized)
        if full not in targets:
            targets.append(full)
    return targets


def output_target_ready(target: str, since: float) -> bool:
    if os.path.isdir(target):
        # Scratch files (the agent's own .tmp_*.py arithmetic helpers) must not
        # count as the deliverable; only real documents/files do.
        for path in deliverable_check.deliverable_files(target):
            try:
                if os.path.getmtime(path) >= since:
                    return True
            except OSError:
                continue
        return False
    if os.path.isfile(target):
        try:
            return os.path.getmtime(target) >= since
        except OSError:
            return False
    return False


def _tool_fingerprint(call: ToolCall) -> str:
    try:
        args = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        args = str(call.arguments)
    return f"{call.name}:{args}"


def _call_path(call: ToolCall) -> str:
    path = (call.arguments or {}).get("path")
    return str(path) if path else ""


def _normalize_path(path: str, workspace: str) -> str:
    try:
        full = path if os.path.isabs(path) else os.path.join(workspace or "", path)
        return os.path.normcase(os.path.normpath(full))
    except (TypeError, ValueError):
        return path


# Reads of the same path are counted per path, not per exact arguments.
def _path_fingerprint(call: ToolCall) -> str:
    if call.name in _PATH_READ_TOOLS:
        path = _call_path(call)
        if path:
            return f"{call.name}:{os.path.normcase(os.path.normpath(path))}"
    return ""


def announcement_prefix(text: str) -> str:
    """Normalized head of an assistant announcement, for repeat detection."""
    normalized = re.sub(r"\s+", " ", (text or "").strip()).lower()
    normalized = re.sub(r"[^\w\u4e00-\u9fff ]", "", normalized)
    return normalized[:TEXT_PREFIX_CHARS]


_SALVAGE_MIN_CHARS = 400


def _decode_partial_json_string(body: str) -> str:
    """Decode a JSON string literal that was cut off before its closing quote."""
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == '"':
            break
        if ch == "\\":
            i += 1
            if i >= n:
                break
            esc = body[i]
            if esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            elif esc == "r":
                out.append("\r")
            elif esc in ('"', "\\", "/"):
                out.append(esc)
            elif esc == "b":
                out.append("\b")
            elif esc == "f":
                out.append("\f")
            elif esc == "u" and i + 4 < n:
                try:
                    out.append(chr(int(body[i + 1 : i + 5], 16)))
                    i += 4
                except ValueError:
                    out.append(esc)
            else:
                out.append(esc)
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def salvage_truncated_write(name: str, raw: str) -> dict[str, Any] | None:
    """Recover path + complete-line prefix from a write_file call cut by the output limit.

    A single write_file of a full HTML page exceeded the provider's default
    8192-token ceiling; the JSON never closed and the whole generation was
    thrown away. Salvaging the prefix turns that waste into progress and gives
    the model an exact line to resume from.
    """
    if name != "write_file" or not raw:
        return None
    match = re.search(r'"path"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
    if not match:
        return None
    try:
        path = json.loads('"' + match.group(1) + '"')
    except ValueError:
        return None
    content = re.search(r'"content"\s*:\s*"', raw[match.end() :])
    if not content:
        return None
    text = _decode_partial_json_string(raw[match.end() + content.end() :])
    lines = text.split("\n")
    if len(lines) > 1:
        lines = lines[:-1]  # the last line is almost certainly cut mid-way
    complete = "\n".join(lines)
    if complete and not complete.endswith("\n"):
        complete += "\n"
    if len(complete) < _SALVAGE_MIN_CHARS:
        return None
    return {"path": path, "content": complete, "lines": complete.count("\n")}


def delivery_ledger(state: dict[str, Any]) -> str:
    """Harness-managed task state injected after every compaction.

    The LLM-written summary is prose and loses precise state; this block lists
    deliverable files, how far each got, and what remains, so the agent resumes
    without re-reading its own output.
    """
    lines: list[str] = []
    for target in state.get("output_targets") or []:
        files = deliverable_check.deliverable_files(target)
        if not files:
            lines.append(f"- MISSING {target}: not written yet")
            continue
        for path in files[:4]:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if path.lower().endswith(deliverable_check.HTML_EXTS):
                report = deliverable_check.html_report(path)
                lines.append(
                    f"- WRITTEN {path}: {size} bytes, {report.get('line_count', 0)} lines, "
                    f"{report.get('visible_chars', 0)} visible chars, "
                    f"{report.get('resolved_anchors', 0)}/{report.get('nav_anchors', 0)} nav anchors resolved, "
                    f"closed={report.get('closed', False)}"
                )
                if report.get("dead_anchors"):
                    listed = ", ".join(f"#{anchor}" for anchor in report["dead_anchors"][:12])
                    lines.append(f"    sections still missing (anchors without target): {listed}")
                if not report.get("closed"):
                    lines.append("    document is not closed: continue appending from the end of the file")
            else:
                lines.append(f"- WRITTEN {path}: {size} bytes")
    written = state.get("written_paths") or []
    if written:
        lines.append("- files written this run (oldest first): " + ", ".join(Path(p).name for p in written[-8:]))
    refs = state.get("reference_paths") or []
    if refs:
        lines.append("- reference files (already digested; do not re-read): " + ", ".join(Path(p).name for p in refs))
    lines.append(f"- step {state.get('total_steps', 0)}; next: write the missing sections / fix the listed issues, validate, finish")
    return "\n".join(lines)


def missing_deliverables(state: dict[str, Any]) -> list[str]:
    since = float(state.get("delivery_since") or 0.0)
    return [target for target in (state.get("output_targets") or []) if not output_target_ready(target, since)]


def _describe_deliverable(path: str, since: float) -> tuple[str, bool]:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    try:
        fresh = os.path.getmtime(path) >= since if since else True
    except OSError:
        fresh = False
    if os.path.splitext(path)[1].lower() in deliverable_check.HTML_EXTS:
        report = deliverable_check.html_report(path)
        parts = [
            f"{size:,} B",
            f"{report.get('line_count', 0)} 行",
            f"{report.get('visible_chars', 0)} 可见字符",
            f"{report.get('resolved_anchors', 0)}/{report.get('nav_anchors', 0)} 锚点",
            "已闭合" if report.get("closed") else "未闭合",
        ]
        if report.get("dead_anchors"):
            parts.append("坏锚点 " + ", ".join(f"#{item}" for item in report["dead_anchors"][:5]))
        if report.get("broken_local_links"):
            parts.append("坏链接 " + ", ".join(report["broken_local_links"][:5]))
        return " · ".join(parts), fresh
    return f"{size:,} B", fresh


def task_summary_text(
    session: dict[str, Any],
    state: dict[str, Any],
    status: str,
    error: str = "",
) -> str:
    """Deterministic closing summary shown even when the model never wrote one."""
    labels = {"done": "已完成", "error": "失败", "cancelled": "已取消"}
    lines = ["## 任务收尾总结", "", f"**状态**：{labels.get(status, status or '未知')}"]
    goal = re.sub(r"\s+", " ", str(session.get("first_question") or "")).strip()
    if goal:
        lines.append(f"**目标**：{goal[:220]}{'…' if len(goal) > 220 else ''}")
    if state.get("started_at"):
        seconds = max(0, int(time.time() - float(state["started_at"])))
        suffix = f" · {state.get('total_steps')} 步" if state.get("total_steps") else ""
        lines.append(f"**用时**：{seconds}s{suffix}")
    elif session.get("elapsed_s"):
        lines.append(f"**用时**：{int(session['elapsed_s'])}s")

    since = float(state.get("delivery_since") or 0.0)
    targets = [str(item) for item in (state.get("output_targets") or []) if item]
    produced: list[str] = []
    produced_keys: set[str] = set()
    missing: list[str] = []
    for target in targets:
        if os.path.isdir(target):
            newest = deliverable_check.main_document(deliverable_check.deliverable_files(target))
            if newest:
                newest_path = newest[0]
                desc, fresh = _describe_deliverable(newest_path, since)
                if fresh:
                    produced.append(f"- `{newest_path}` — {desc}")
                    produced_keys.add(os.path.normcase(os.path.normpath(newest_path)))
                else:
                    missing.append(f"- `{target}` — 目录内没有本轮新生成的文件（最新：`{newest_path}`）")
            else:
                missing.append(f"- `{target}` — 目录为空或未生成文件")
        elif os.path.isfile(target):
            desc, fresh = _describe_deliverable(target, since)
            if fresh:
                produced.append(f"- `{target}` — {desc}")
                produced_keys.add(os.path.normcase(os.path.normpath(target)))
            else:
                missing.append(f"- `{target}` — 文件已存在，但不是本轮生成/修改的")
        else:
            missing.append(f"- `{target}` — 不存在或未生成")

    written: list[str] = []
    for item in (state.get("written_paths") or [])[-8:]:
        key = os.path.normcase(os.path.normpath(str(item)))
        if key in produced_keys or deliverable_check.is_temp_file(str(item)):
            continue
        try:
            size = os.path.getsize(item)
        except OSError:
            size = 0
        written.append(f"- `{item}` — {size:,} B")
        produced_keys.add(key)

    if produced:
        lines.append("**已生成**：")
        lines.extend(produced)
    if written:
        lines.append("**本轮写入**：")
        lines.extend(written)
    if missing:
        lines.append("**未完成**：")
        lines.extend(missing)
    if not produced and not written and not missing:
        lines.append("**产出**：本轮没有生成可交付文件。")

    error = (error or str(session.get("error") or "")).strip()
    if error:
        lines.append(f"**原因**：{error[:600]}")
    if missing:
        lines.append(
            "**下一步**：请确认上面未完成的路径；如果该目录只是参考/输入目录，"
            "请在需求里注明“仅参考”，下一轮会跳过它。"
        )
    elif status == "error":
        lines.append("**下一步**：可以在本会话直接追加“继续”，或给出新的目标文件名；我会从现有产出继续，不重复已完成的工作。")
    else:
        lines.append("**下一步**：如需继续迭代，直接在本会话追加要求即可。")
    return "\n".join(lines)



def _workspace_diff(workspace: str, limit: int = 24000) -> str:
    if not workspace:
        return ""
    try:
        def git(*args: str, timeout: float = 10) -> str:
            return subprocess.run(
                ["git", "-C", workspace, *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            ).stdout

        parts = []
        root = git("rev-list", "--max-parents=0", "HEAD").strip().splitlines()
        if root:
            parts.append(git("diff", "--no-color", "--stat", root[0], "HEAD"))
            parts.append(git("diff", "--no-color", root[0], "HEAD", timeout=15))
        parts.append(git("diff", "--no-color", "HEAD", timeout=15))
        untracked = git("ls-files", "--others", "--exclude-standard")
        for relative in untracked.splitlines()[:20]:
            path = Path(workspace) / relative
            if not path.is_file() or path.stat().st_size > 200_000:
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            parts.append(f"--- new file: {relative}\n{content[:4000]}")
        return "\n".join(part for part in parts if part.strip())[:limit]
    except Exception:
        return ""


def _plan_steps(session: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        plan = json.loads(session.get("plan") or "{}")
        return plan.get("steps") or []
    except (ValueError, TypeError):
        return []


class AgentRuntime:
    def __init__(self, harness: Any):
        self.harness = harness
        self.storage = harness.storage
        self.events = harness.events
        self.context = harness.context
        self.tools = harness.tools
        self.agents = harness.agents
        self.policy = harness.policy
        self.gateway = harness.gateway
        self.skills: SkillLibrary = harness.skills
        self.manager = None

    async def emit(self, session_id: str, event_type: str, payload: dict[str, Any] | None = None, run_id: str = "") -> None:
        await self.events.emit(session_id, event_type, payload or {}, run_id=run_id)

    async def run_session(self, session_id: str) -> None:
        session = await self.storage.get_session(session_id)
        if not session:
            raise RuntimeError(f"session not found: {session_id}")
        await self.storage.update_session(session_id, status="running", error="")
        await self.emit(session_id, "session.status", {"status": "running"})
        first = await self.storage.first_user_message(session_id)
        text = (first or {}).get("content") or ""
        last = await self.storage.list_messages(session_id)
        for row in reversed(last):
            if row["role"] == "user":
                text = row["content"] or ""
                break

        requested = self._choose_kind(session, text)
        casual = is_casual_chat(text)
        if casual:
            requested = "general"
        agent = self._choose_agent(session, requested, text)
        try:
            session_meta = json.loads(session.get("meta") or "{}")
        except (ValueError, TypeError):
            session_meta = {}
        requested_provider = str(
            (session_meta or {}).get("requested_provider") or session.get("provider") or ""
        ).strip()
        requested_model = str(
            (session_meta or {}).get("requested_model") or session.get("model") or ""
        ).strip()
        provider, model = resolve(requested_provider, requested_model)
        strict = await self._strict_route()
        if strict:
            if requested_provider and requested_provider not in ("auto", ""):
                conf = PROVIDERS.get(requested_provider)
                if conf and conf.api_key:
                    provider = requested_provider
                    model = requested_model or effective_default_model(conf)
                else:
                    # Keep the requested provider so the gateway can raise a
                    # precise strict-route error instead of silently falling back.
                    provider, model = requested_provider, requested_model or "unknown"
            elif provider == "mock":
                provider, model = "strict", requested_model or "unknown"
        level = estimate_complexity(text, any(s.get("s") in ("pending", "doing") for s in _plan_steps(session)))
        lite = self._should_lite(session, level, text)
        task_type = detect_task_type(text)
        # A data/compute question is answered by using tools, so it must not take
        # the "question mode" path that discourages a task loop.
        qa = is_question(text) and not is_data_query(text)
        audit = needs_spec_audit(text, level, bool(session.get("workspace")), requested, qa)
        write_required = level != "simple" and needs_write(text, qa, requested, bool(session.get("workspace")))
        thinking = self._thinking(session, provider, lite, level, qa or casual)
        run = await self.storage.create_run(session_id, provider, model, text)
        run_id = run["id"]

        matched, skill_how = ([], "no skills") if (qa or casual) and not session.get("skills") else self.skills.match(
            requested, text, self._selected_skills(session)
        )
        matched = relevant_skills(matched, text)
        payload_skills = [{"name": skill.name, "title": skill.title, "source": skill.source} for skill in matched]
        await self.storage.update_session(session_id, skills_used=json.dumps(payload_skills, ensure_ascii=False), lite_mode=1 if lite else 0)
        await self.emit(session_id, "skills.matched", {"skills": payload_skills, "how": skill_how, "kind": requested}, run_id)
        await self.emit(
            session_id,
            "route",
            {
                "provider": provider,
                "model": model,
                "thinking": thinking,
                "level": level,
                "lite": lite,
                "task_type": task_type,
                "kind": requested,
                "agent": agent.name,
                "qa": qa,
                "casual": casual,
                "strict": strict,
            },
            run_id,
        )

        state: dict[str, Any] = {}
        try:
            state = await self._drive(
                session,
                agent,
                requested,
                provider,
                model,
                thinking,
                lite,
                task_type,
                qa,
                audit,
                matched,
                skill_how,
                run_id,
                text,
                write_required,
                casual,
                strict,
            )
            await self._ensure_task_summary(session_id, run_id, session, state)
        except asyncio.CancelledError:
            await self.storage.update_session(session_id, status="error", error="用户取消")
            await self.emit(session_id, "session.status", {"status": "error", "error": "用户取消"}, run_id)
            await self.storage.finish_run(run_id, "cancelled", error="用户取消")
            await self._ensure_task_summary(
                session_id, run_id, session, state, status="cancelled", error="用户取消"
            )
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            await self.storage.update_session(session_id, status="error", error=message[:500])
            await self.emit(session_id, "error", {"message": message}, run_id)
            await self.emit(session_id, "session.status", {"status": "error", "error": message[:500]}, run_id)
            await self.storage.finish_run(run_id, "error", error=message)
            await self._ensure_task_summary(
                session_id, run_id, session, state, status="error", error=message
            )
        finally:
            await self.events.flush()

    async def _strict_route(self) -> bool:
        if os.getenv("HAOYUAN_STRICT_PROVIDER", "").strip().lower() in {"1", "true", "yes"}:
            return True
        try:
            value = await self.storage.get_setting("strict_route", "0")
        except Exception:
            return False
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _selected_skills(self, session: dict[str, Any]) -> list[str]:
        try:
            return list(json.loads(session.get("skills") or "[]"))
        except (ValueError, TypeError):
            return []

    def _choose_kind(self, session: dict[str, Any], text: str) -> str:
        kind = session.get("kind") or "auto"
        if kind == "auto":
            return detect_kind(text)
        if kind in ("coding", "dev"):
            return "dev"
        return kind

    def _choose_agent(self, session: dict[str, Any], kind: str, text: str):
        workspace = session.get("workspace") or ""
        if kind in ("dev", "coding") and not workspace:
            return self.agents.get("general")
        if kind == "plan":
            return self.agents.get("planner")
        if kind == "robot":
            return self.agents.get("robot")
        if kind == "general":
            return self.agents.get("general")
        return self.agents.get(DEFAULT_AGENT)

    def _should_lite(self, session: dict[str, Any], level: str, text: str) -> bool:
        if not LITE_MODE:
            return False
        # Web deliverables and research reports need the full toolset even when
        # the router calls them "normal": subagents, reference diffing, baseline
        # evidence and high reasoning are part of the task, not optional polish.
        if wants_web_tools(text) or _RESEARCH_HINTS.search(text or ""):
            return False
        if any(step.get("s") in ("pending", "doing") for step in _plan_steps(session)):
            return False
        # Complex tasks always run full. Lite used to swallow the subagent tool
        # and high reasoning exactly when they were most valuable.
        if level == "complex":
            return False
        if level in ("simple", "normal"):
            return True
        cleaned = _NEGATION_RE.sub("", text or "")
        if any(hint in cleaned for hint in LITE_MULTIPHASE_HINTS):
            return False
        paths = {match.group(0).lower() for match in _PATH_RE.finditer(text or "")}
        return len(paths) <= LITE_SINGLE_FILE_MAX_PATHS

    def _thinking(self, session: dict[str, Any], provider: str, lite: bool, level: str, qa: bool) -> str:
        # Explicit operator override wins (useful for A/B testing).
        override = os.getenv("HAOYUAN_FORCE_THINKING", "").strip().lower()
        if override in ("off", "low", "high"):
            return override
        # An explicit per-session choice always wins: reasoning-heavy tasks (constraint
        # solving, proofs, hard debugging) measurably need it, so never silently
        # downgrade the caller's request.
        selected = (session.get("thinking") or "").strip()
        if selected in ("off", "low", "high"):
            return selected
        # Providers in THINKING_OFF_PROVIDERS default to no reasoning budget; this is
        # only a fallback when the session did not ask for anything specific.
        if provider in THINKING_OFF_PROVIDERS:
            return "off"
        if provider == "mock":
            return "off"
        if qa:
            return "off"
        # Complex tasks get high reasoning even if a caller forced lite mode;
        # this is where planning, baseline auditing and contradiction checks pay off.
        if level == "complex":
            return "high"
        if lite:
            return "low"
        return "low"

    def _tools_for(self, agent, kind: str, lite: bool, workspace: bool, text: str = "") -> list[str]:
        if not agent.tools:
            return []
        if not workspace and getattr(agent, "kind", "") not in ("plan", "robot"):
            chat_safe = {"system_info", "calculator", "now", "echo", "web_fetch"}
            return [name for name in agent.tools if name in chat_safe and self.tools.get(name)]
        names = [name for name in agent.tools if self.tools.get(name)]
        if not names:
            return []
        # Plan agents already expose a tiny purpose-built toolset; the general
        # assistant only has chat-safe tools. Trimming either with LITE_TOOL_SET
        # would strip their entire toolset, so keep them intact.
        if lite and TOOL_SCHEMA_TRIM and getattr(agent, "kind", "") not in ("plan", "general"):
            allowed = set(LITE_TOOL_SET) | {"plan_task", "update_plan"}
            # Web/reference tool schemas are large and irrelevant to ordinary repo
            # work. Only advertise them when the request is actually about a web
            # deliverable or a reference file; otherwise they are pure token cost.
            if not wants_web_tools(text):
                allowed -= {"web_audit", "web_scaffold", "reference_digest", "reference_compare", "web_screenshot"}
            names = [name for name in names if name in allowed]
        if not SUBAGENT_ENABLED:
            names = [name for name in names if name != "task"]
        return names

    @staticmethod
    def _guarded_tools(names: list[str], state: dict[str, Any]) -> list[str]:
        # When the no-progress guard has decided the agent must ship the file,
        # hide read-only tools so it cannot keep looping on reads.
        if not state.get("write_only"):
            return names
        blocked = set(READONLY_TOOLS)
        allowed = [name for name in names if name not in blocked]
        return allowed or names

    async def _drive(
        self,
        session: dict[str, Any],
        agent,
        kind: str,
        provider: str,
        model: str,
        thinking: str,
        lite: bool,
        task_type: str,
        qa: bool,
        audit: bool,
        matched: list,
        skill_how: str,
        run_id: str,
        user_text: str = "",
        write_required: bool = False,
        casual: bool = False,
        strict: bool = False,
    ) -> dict[str, Any]:
        session_id = session["id"]
        workspace = session.get("workspace") or ""
        host_info = ""
        if sysinfo.wants_host_info(user_text):
            try:
                host_info = sysinfo.summary(sysinfo.collect(workspace))
            except Exception:
                host_info = ""
        repo_map_text = ""
        context_pack_text = ""
        broad_root = _is_broad_root(workspace)
        if REPO_MAP_ENABLED and workspace and not broad_root and kind in ("dev", "coding") and not lite and not qa:
            try:
                repo_map_text = await asyncio.to_thread(repoindex.repo_map, workspace, None, user_text)
            except Exception:
                repo_map_text = ""
            try:
                context_pack_text = await asyncio.to_thread(
                    repoindex.context_pack, workspace, user_text, CONTEXT_PACK_MAX_CHARS, 18
                )
            except Exception:
                context_pack_text = ""
        reference_text = ""
        reference_paths: list[str] = []
        if workspace and not casual and not qa:
            try:
                reference_paths = reference.resolve_reference_paths(workspace, user_text)
                blocks = [reference.digest(rel, 14000) for rel in reference_paths[:2]]
                reference_text = "\n\n".join(blocks)[:18000]
            except Exception:
                reference_paths = []
                reference_text = ""
        output_targets = extract_output_targets(user_text, workspace) if write_required else []
        doc_mode = wants_document_workflow(user_text, write_required, kind, output_targets)
        if doc_mode:
            # Repository playbooks are noise for a document deliverable and used to
            # take up most of the (tiny) context budget.
            matched = [skill for skill in matched if getattr(skill, "name", "") not in ("dev-loop", "debug-loop")]
        system = self._system_prompt(
            session,
            agent,
            kind,
            provider,
            model,
            task_type,
            lite,
            qa,
            matched,
            skill_how,
            repo_map_text,
            casual,
            context_pack_text,
            reference_text,
            research=bool(_RESEARCH_HINTS.search(user_text)),
            doc_mode=doc_mode,
        )
        contract = budget_contract(user_text)
        if contract:
            system += contract
        if host_info:
            system += (
                "\n\n# Live host information (read-only)\n"
                + host_info
                + "\nUse this information to answer the user's question directly. Do not claim you cannot access system information."
            )
        recent, summary, cursor = await self.context.load(session)
        if summary:
            system += "\n\n--- Compressed history memory ---\n" + summary
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}] + recent
        if self.manager and self.manager.consume_interrupt(session_id):
            messages.append({"role": "user", "content": interrupt_notice()})
            await self.emit(session_id, "instruction.interrupted", {"status": "cancelled"}, run_id)
        tool_names = self._tools_for(agent, kind, lite, bool(workspace), user_text)

        resumed = self.manager.consume_resume(session_id) if self.manager else False
        prior_effects = await durability.load_effects(self.storage, session_id) if resumed else {}
        state_effects = prior_effects
        if resumed:
            checkpoint = await durability.latest_checkpoint(self.storage, session_id)
            where = f" from step {checkpoint['step']}" if checkpoint else ""
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"[system] Resuming an interrupted task{where}. Review the plan and checkpoint "
                        "notes first, then continue the unfinished work. Do not repeat completed work and "
                        "do not re-read files you already inspected unless they changed. Writes recorded "
                        "before the interruption will not be repeated."
                    ),
                }
            )
            await self.emit(session_id, "session.resume", {"auto": False, "checkpoint": checkpoint}, run_id)

        await self.emit(session_id, "session.status", {"status": "running"}, run_id)
        state = {
            "run_id": run_id,
            "step": 0,
            "total_steps": 0,
            "started_at": time.time(),
            "last_write_step": 0,
            "last_verify_step": 0,
            "verify_nudges": 0,
            "spec_audit": 0,
            "write_nudges": 0,
            "empty_nudges": 0,
            "trunc_nudges": 0,
            "rollovers": 0,
            "escalated": False,
            "repair_fingerprints": {},
            "final_text": "",
            "effects": state_effects,
            "reference_paths": reference_paths,
            "reference_outputs": [],
            "reference_drift": "",
            "fidelity_nudges": 0,
            "output_targets": output_targets,
            "delivery_since": time.time(),
            "delivery_start_step": 0,
            "delivered_at_step": None,
            "output_nudges": 0,
            "tool_fp_counts": {},
            "read_path_counts": {},
            "write_only": False,
            "stuck_streak": 0,
            "no_progress_nudges": 0,
            "audit_nudges": 0,
            "prompt_tokens_total": 0,
            "last_prompt_tokens": 0,
            "text_prefixes": [],
            "written_paths": [],
            "explore_budget_hit": False,
            "strict_route": strict,
        }
        max_total = AGENT_MAX_TOTAL_STEPS
        session = await self.storage.get_session(session_id) or session

        while True:
            if AGENT_MAX_RUN_SEC > 0 and time.time() - state["started_at"] > AGENT_MAX_RUN_SEC:
                message = f"run exceeded wall-clock budget ({int(AGENT_MAX_RUN_SEC)}s)"
                await self.emit(session_id, "error", {"message": message}, run_id)
                await self.storage.update_session(session_id, status="error", error=message)
                await self.storage.finish_run(run_id, "error", error=message, step_count=state["total_steps"])
                return state
            if state["step"] >= AGENT_MAX_STEPS:
                if state["total_steps"] < max_total:
                    state["rollovers"] += 1
                    state["step"] = 0
                    await self.emit(
                        session_id,
                        "checkpoint.rollover",
                        {"segment": state["rollovers"], "total_steps": state["total_steps"]},
                        run_id,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"[system] Segment budget reached ({state['total_steps']}/{max_total} steps). "
                                "Continue from exactly where you left off; do not repeat completed work or "
                                f"re-read unchanged files. Segment {state['rollovers'] + 1}."
                            ),
                        }
                    )
                    continue
                await self.emit(session_id, "error", {"message": f"reached max steps ({state['total_steps']})"}, run_id)
                await self.storage.update_session(session_id, status="error", error="max steps reached")
                await self.storage.finish_run(run_id, "error", error="max steps reached", step_count=state["total_steps"])
                return state
            state["step"] += 1
            state["total_steps"] += 1

            # Prompt-token budgets: a looping model once burned 67M prompt tokens
            # in 38 minutes without writing anything.
            if RUN_MAX_PROMPT_TOKENS and state["prompt_tokens_total"] >= RUN_MAX_PROMPT_TOKENS:
                message = f"prompt token budget exhausted ({state['prompt_tokens_total']} tokens, {state['total_steps']} steps)"
                await self.emit(session_id, "error", {"message": message}, run_id)
                await self.storage.update_session(session_id, status="error", error=message[:500])
                await self.storage.finish_run(run_id, "error", error=message, step_count=state["total_steps"])
                return state
            if (
                NO_PROGRESS_GUARD
                and write_required
                and not state["write_only"]
                and not state["explore_budget_hit"]
                and missing_deliverables(state)
                and (
                    time.time() - state["started_at"] >= EXPLORATION_MAX_SEC
                    or (EXPLORATION_MAX_PROMPT_TOKENS and state["prompt_tokens_total"] >= EXPLORATION_MAX_PROMPT_TOKENS)
                )
            ):
                # Exploration has cost enough; switch to write-only so the agent
                # ships what it has instead of reading for another hour.
                state["explore_budget_hit"] = True
                state["write_only"] = True
                await self.emit(
                    session_id,
                    "explore.budget",
                    {
                        "elapsed_s": int(time.time() - state["started_at"]),
                        "prompt_tokens": state["prompt_tokens_total"],
                        "step": state["total_steps"],
                    },
                    run_id,
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "[system exploration budget] The exploration budget (wall time / prompt tokens) is "
                            "exhausted and the deliverable does not exist yet. Read-only tools are now disabled. "
                            "Write the deliverable now from what you already know; label unknowns as assumptions "
                            "instead of reading further."
                        ),
                    }
                )

            cursor, injected = await self._inject_pending(session_id, messages, cursor)
            if injected:
                await self.emit(
                    session_id,
                    "instruction.merged",
                    {"count": len(injected), "items": injected},
                    run_id,
                )

            session = await self.storage.get_session(session_id) or session
            compaction = await self.context.midturn_compact(
                session,
                messages,
                state["total_steps"],
                last_prompt_tokens=state["last_prompt_tokens"],
                ledger_text=delivery_ledger(state),
            )
            if compaction.get("compacted"):
                await self.emit(session_id, "context.compact", compaction, run_id)

            # Pre-generate the assistant message id so streaming events (delta/reasoning) and
            # the persisted row share one id; clients correlate them to replace the live bubble.
            msg_id = f"m_{uuid.uuid4().hex[:16]}"
            message: dict[str, Any] | None = None
            usage: dict[str, Any] = {}
            actual_provider, actual_model = provider, model
            fallbacks: list[str] = []
            finish_reason = ""
            # Recompute per step: the no-progress guard can switch the agent to
            # "write-only" mode, which removes read tools from the schema so a
            # looping model physically cannot keep re-reading the same file.
            schemas = self.tools.openai_tools(self._guarded_tools(tool_names, state))
            async for event in self.gateway.stream(
                provider, model, messages, schemas, thinking, strict=bool(state.get("strict_route"))
            ):
                event_type = event.get("type")
                if event_type == "reasoning":
                    await self.emit(session_id, "reasoning", {"msg_id": msg_id, "text": event.get("text")}, run_id)
                elif event_type == "delta":
                    await self.emit(session_id, "delta", {"msg_id": msg_id, "text": event.get("text")}, run_id)
                elif event_type == "message":
                    message = event.get("message")
                    usage = event.get("usage") or {}
                    actual_provider = event.get("provider") or provider
                    actual_model = event.get("model") or model
                    fallbacks = event.get("fallbacks") or []
                    finish_reason = event.get("finish_reason") or finish_reason
            if message is None:
                raise RuntimeError("model returned no message")

            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            raw_calls = message.get("tool_calls") or []
            if usage:
                state["prompt_tokens_total"] += int(usage.get("prompt_tokens") or 0)
                state["last_prompt_tokens"] = int(usage.get("prompt_tokens") or 0)
            # "I'll start by checking the current state of the deliverable directory"
            # repeated 30 times in one run while the tool args kept varying: count
            # repeated announcements as no progress even when every call is new.
            repeated_announcement = False
            prefix = announcement_prefix(content)
            if prefix:
                history = state["text_prefixes"]
                history.append(prefix)
                del history[:-TEXT_PREFIX_WINDOW]
                if history.count(prefix) >= TEXT_PREFIX_REPEAT_LIMIT:
                    repeated_announcement = True
                    await self.emit(
                        session_id,
                        "loop.announcement",
                        {"prefix": prefix[:60], "count": history.count(prefix), "step": state["total_steps"]},
                        run_id,
                    )
            stored_calls = []
            parsed_calls: list[ToolCall] = []
            for index, raw in enumerate(raw_calls):
                function = raw.get("function") or {}
                call_id = raw.get("id") or f"call_{index}"
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except (ValueError, TypeError):
                    arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {"value": arguments}
                if isinstance(arguments.get("_raw"), str) and finish_reason == "length":
                    recovered = salvage_truncated_write(function.get("name") or "", arguments["_raw"])
                    if recovered:
                        # Keep the complete prefix instead of discarding an
                        # 8k-token generation; the executor writes it as usual.
                        arguments = {
                            "path": recovered["path"],
                            "content": recovered["content"],
                            "_salvaged": {"lines": recovered["lines"], "chars": len(recovered["content"])},
                        }
                        await self.emit(
                            session_id,
                            "write.salvaged",
                            {"path": recovered["path"], "lines": recovered["lines"], "chars": len(recovered["content"])},
                            run_id,
                        )
                stored_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": function.get("name") or "",
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )
                parsed_calls.append(ToolCall(call_id=call_id, name=function.get("name") or "", arguments=arguments))

            assistant_row = await self.storage.add_message(
                session_id,
                run_id,
                "assistant",
                content,
                reasoning=reasoning,
                tool_args=stored_calls if stored_calls else None,
                message_id=msg_id,
            )
            if usage:
                bill = await self.storage.record_usage(session_id, assistant_row["id"], actual_provider, actual_model, usage)
                await self.emit(session_id, "usage", {**bill, "provider": actual_provider, "model": actual_model}, run_id)
            if fallbacks:
                await self.emit(
                    session_id,
                    "model.fallback",
                    {"fallbacks": fallbacks, "provider": actual_provider, "model": actual_model},
                    run_id,
                )

            if content or stored_calls:
                assistant_message: dict[str, Any] = {"role": "assistant", "content": content or None}
                if stored_calls:
                    assistant_message["tool_calls"] = stored_calls
                messages.append(assistant_message)
            await self.emit(
                session_id,
                "message.saved",
                {"msg_id": assistant_row["id"], "role": "assistant", "content": content, "has_tools": bool(stored_calls)},
                run_id,
            )

            if finish_reason == "length":
                await self.emit(session_id, "output.truncated", {"step": state["total_steps"]}, run_id)

            if not parsed_calls:
                cursor, injected = await self._inject_pending(session_id, messages, cursor)
                if injected:
                    await self.emit(
                        session_id,
                        "instruction.merged",
                        {"count": len(injected), "items": injected},
                        run_id,
                    )
                    continue
                if finish_reason == "length" and state["trunc_nudges"] < 2:
                    state["trunc_nudges"] += 1
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system] Your previous output hit the model's length limit and was cut off. Continue "
                                "exactly from where it stopped. For large files, never emit the whole file at once: "
                                "create it with a short write_file skeleton, then append the remaining sections with "
                                "apply_patch or edit_file in chunks of at most 150 lines."
                            ),
                        }
                    )
                    continue
                if not (content or "").strip() and state["empty_nudges"] < 1:
                    state["empty_nudges"] += 1
                    await self.emit(session_id, "empty.nudge", {"step": state["total_steps"]}, run_id)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system] Your previous response was empty. Continue the task. If the work is "
                                "complete, reply with a concise summary of changes and verification."
                            ),
                        }
                    )
                    continue
                if write_required and state["last_write_step"] == 0 and state["write_nudges"] < 1:
                    state["write_nudges"] += 1
                    await self.emit(session_id, "write.nudge", {"step": state["total_steps"]}, run_id)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system] No files have been modified yet, but this request requires a code change. "
                                "Inspect the relevant files, implement the change, run the project's verification "
                                "command, and then summarize. Do not stop at analysis."
                            ),
                        }
                    )
                    continue
                if (
                    VERIFY_GATE
                    and state["last_write_step"] > state["last_verify_step"]
                    and state["verify_nudges"] < VERIFY_MAX_NUDGE
                ):
                    state["verify_nudges"] += 1
                    await self.emit(
                        session_id,
                        "verify.nudge",
                        {"nudge": state["verify_nudges"], "last_write_step": state["last_write_step"]},
                        run_id,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system verification gate] You changed code but did not run a verification command. "
                                "Run the relevant test/lint/build now. If verification is impossible, state explicitly "
                                "what is unverified and why. Do not print values as a substitute for assertions."
                            ),
                        }
                    )
                    continue
                if state["reference_drift"] and state["fidelity_nudges"] < 2:
                    state["fidelity_nudges"] += 1
                    await self.emit(
                        session_id,
                        "reference.nudge",
                        {"nudge": state["fidelity_nudges"], "outputs": len(state["reference_outputs"])},
                        run_id,
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system reference fidelity gate] The generated HTML drifted from the reference "
                                "design system. Restore the reference exactly: same palette, font stack, theme mode, "
                                "layout width, breakpoints and component classes. Do not redesign, and do not add "
                                "sections the user did not request.\n\n" + state["reference_drift"]
                            ),
                        }
                    )
                    continue
                missing_outputs = [
                    target for target in state["output_targets"]
                    if not output_target_ready(target, state["delivery_since"])
                ]
                if missing_outputs and state["output_nudges"] < 2:
                    state["output_nudges"] += 1
                    await self.emit(session_id, "delivery.nudge", {"missing": missing_outputs}, run_id)
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system delivery contract] No new deliverable exists at the requested path: "
                                + ", ".join(missing_outputs)
                                + ". Write the final artifact to that exact path now (create the directory if needed). "
                                "Do not finish with a summary until the file exists."
                            ),
                        }
                    )
                    continue
                if missing_outputs:
                    reason = "deliverable not created at: " + ", ".join(missing_outputs)
                    await self.emit(session_id, "error", {"message": reason}, run_id)
                    await self.storage.update_session(session_id, status="error", error=reason[:500])
                    await self.storage.finish_run(run_id, "error", error=reason, step_count=state["total_steps"])
                    return state
                if state["output_targets"]:
                    # Exists is not complete: a page with dead anchors or a
                    # fraction of the reference's length goes back for fixes.
                    issues = self._deliverable_issues(session, state)
                    if issues:
                        if state["audit_nudges"] < DELIVERY_AUDIT_NUDGE:
                            state["audit_nudges"] += 1
                            state["write_only"] = False
                            await self.emit(
                                session_id,
                                "delivery.audit",
                                {"issues": issues, "nudge": state["audit_nudges"], "step": state["total_steps"]},
                                run_id,
                            )
                            messages.append({"role": "user", "content": self._audit_nudge_text(issues)})
                            continue
                        reason = "deliverable incomplete: " + "; ".join(issues)[:600]
                        await self.emit(session_id, "error", {"message": reason}, run_id)
                        await self.storage.update_session(session_id, status="error", error=reason[:500])
                        await self.storage.finish_run(run_id, "error", error=reason, step_count=state["total_steps"])
                        return state
                if (
                    audit
                    and not state["spec_audit"]
                    and state["last_write_step"] > 0
                    and state["last_verify_step"] >= state["last_write_step"]
                ):
                    state["spec_audit"] = 1
                    await self.emit(
                        session_id,
                        "spec.audit.start",
                        {"last_write_step": state["last_write_step"], "last_verify_step": state["last_verify_step"]},
                        run_id,
                    )
                    reviewer = await self._quick_spec_review(session, user_text, provider, model, state)
                    verdict = "GAPS" if "VERDICT: GAPS" in reviewer.upper() else "PASS"
                    await self.emit(session_id, "spec.audit.result", {"verdict": verdict, "report": reviewer[:2000]}, run_id)
                    if verdict == "PASS":
                        state["final_text"] = content
                        break
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "[system spec audit findings] An independent reviewer found possible gaps:\n"
                                + reviewer[:4000]
                                + "\nAddress every real gap, rerun verification, then give the final summary."
                            ),
                        }
                    )
                    continue
                state["final_text"] = content
                break

            if not state["escalated"] and level_is_complex(task_type, content):
                state["escalated"] = True
                await self.emit(session_id, "route", {"level": "complex", "reason": "tool use detected; escalate", "model": actual_model}, run_id)

            # Record call fingerprints BEFORE executing: duplicates can then be
            # suppressed, and the guard can distinguish new work from repetition.
            call_prior: dict[str, int] = {}
            suppressed_paths: dict[str, int] = {}
            new_fingerprints = 0
            new_reads = 0
            for call in parsed_calls:
                fingerprint = _tool_fingerprint(call)
                prior = state["tool_fp_counts"].get(fingerprint, 0)
                call_prior[call.call_id] = prior
                state["tool_fp_counts"][fingerprint] = prior + 1
                overused = False
                path = _call_path(call)
                if path and call.name in READONLY_TOOLS:
                    # Count per resolved path: the same file was read as both
                    # "git/x/index.html" and "D:\Env\git\x\index.html" in one run.
                    key = _normalize_path(path, workspace)
                    seen_path = state["read_path_counts"].get(key, 0)
                    state["read_path_counts"][key] = seen_path + 1
                    if seen_path == 0:
                        new_reads += 1
                    if NO_PROGRESS_GUARD and seen_path + 1 > LOOP_PATH_SUPPRESS_LIMIT:
                        overused = True
                        suppressed_paths[call.call_id] = seen_path + 1
                        await self.emit(
                            session_id,
                            "loop.path_suppressed",
                            {"path": path, "reads": seen_path + 1, "step": state["total_steps"]},
                            run_id,
                        )
                if prior == 0 and not overused:
                    new_fingerprints += 1
            state["_call_prior"] = call_prior
            state["_suppressed_paths"] = suppressed_paths

            results = await self._execute_calls(session, parsed_calls, run_id, state)
            for call in parsed_calls:
                result = results.get(call.call_id)
                if result is None:
                    continue
                salvaged = (call.arguments or {}).get("_salvaged")
                if salvaged and result.ok:
                    result.result = (
                        f"[auto-continued] The write_file call hit the model's output length limit and its JSON "
                        f"was cut off. The complete prefix ({salvaged.get('lines')} lines) was saved to "
                        f"{call.arguments.get('path')}. Continue by appending the next section with apply_patch or "
                        "edit_file (<= 150 lines per call). Do not rewrite the file from the beginning and do not "
                        "re-send the saved lines."
                    )
                    result.summary = f"truncated write salvaged: {salvaged.get('lines')} lines saved"
                content_for_context = self._tool_context_text(result, call, state, session_id)
                await self.storage.add_message(
                    session_id,
                    run_id,
                    "tool",
                    content_for_context,
                    tool_call_id=call.call_id,
                    tool_name=call.name,
                    tool_args=call.arguments,
                )
                messages.append({"role": "tool", "tool_call_id": call.call_id, "content": content_for_context})
                if result.ok and call.name == "describe_image":
                    attachment = vision.native_attachment_message(result.result, workspace)
                    if attachment:
                        messages.append({"role": "user", "content": attachment})
                if result.ok and call.name in ("write_file", "edit_file", "apply_patch", "multi_edit"):
                    path = str(call.arguments.get("path") or "")
                    full = path if os.path.isabs(path) else os.path.join(workspace, path)
                    if os.path.isfile(full) and full not in state["written_paths"]:
                        state["written_paths"].append(full)
                    if Path(path).suffix.lower() in VERIFY_CODE_EXTS:
                        state["last_write_step"] = state["total_steps"]
                    if Path(path).suffix.lower() in (".html", ".htm") and state["reference_paths"]:
                        full = path if os.path.isabs(path) else os.path.join(workspace, path)
                        if os.path.isfile(full):
                            target = os.path.realpath(full)
                            if target not in state["reference_outputs"]:
                                state["reference_outputs"].append(target)
                    await self._register_change_artifact(session_id, call, result)
                if call.name == "run_shell" and result.ok:
                    command = str(call.arguments.get("command") or "")
                    # A shell redirect/heredoc/script is a real workspace write.
                    if shell_wrote_files(command):
                        state["last_write_step"] = state["total_steps"]
                    # Running the script or tests is a real verification step.
                    if looks_like_verification(command) and "[exit 0]" in str(result.result):
                        state["last_verify_step"] = state["total_steps"]
                await self._register_generated_artifact(session_id, call, result)

            wrote = state["last_write_step"] == state["total_steps"]
            if NO_PROGRESS_GUARD:
                missing = missing_deliverables(state)
                # Clear the write-only lock as soon as the deliverable exists;
                # otherwise arm it once the exploration deadline is reached.
                if not missing:
                    state["write_only"] = False
                elif (state["total_steps"] - state["delivery_start_step"]) >= DELIVERY_DEADLINE_STEPS:
                    state["write_only"] = True
                path_overused = any(
                    count > REPEAT_READ_LIMIT for count in state["read_path_counts"].values()
                )
                if state["write_only"]:
                    # In write-only mode only actually shipping the deliverable
                    # counts as progress (temp scripts and suppressed reads do not).
                    made_progress = not missing
                else:
                    made_progress = bool(wrote) or (
                        (bool(new_reads) or (bool(new_fingerprints) and not path_overused))
                        and not repeated_announcement
                    )
                if made_progress:
                    state["stuck_streak"] = 0
                else:
                    state["stuck_streak"] += 1
                has_deliverable = bool(state["output_targets"]) and not missing
                if has_deliverable and state["delivered_at_step"] is None:
                    state["delivered_at_step"] = state["total_steps"]
                if state["stuck_streak"] >= NO_PROGRESS_STREAK:
                    state["stuck_streak"] = 0
                    state["no_progress_nudges"] += 1
                    target_hint = "、".join(missing)
                    if has_deliverable:
                        delivered_hint = "、".join(state["output_targets"])
                        # The file the user asked for already exists; the model is
                        # just spinning. Give one nudge to summarize, then finish as
                        # DONE (not an error) so the user isn't told a good run failed.
                        grace = state["delivered_at_step"] is not None and (
                            state["total_steps"] - state["delivered_at_step"]
                        ) >= NO_PROGRESS_STREAK
                        if state["no_progress_nudges"] >= 2 and grace:
                            issues = self._deliverable_issues(session, state)
                            if issues:
                                # Exists is not complete. Send it back for the
                                # missing sections; a second failure is an error,
                                # never a "deliverable created" success.
                                if state["audit_nudges"] < DELIVERY_AUDIT_NUDGE:
                                    state["audit_nudges"] += 1
                                    state["write_only"] = False
                                    await self.emit(
                                        session_id,
                                        "delivery.audit",
                                        {"issues": issues, "nudge": state["audit_nudges"], "step": state["total_steps"]},
                                        run_id,
                                    )
                                    messages.append({"role": "user", "content": self._audit_nudge_text(issues)})
                                    continue
                                reason = "deliverable incomplete: " + "; ".join(issues)[:600]
                                await self.emit(session_id, "error", {"message": reason}, run_id)
                                await self.storage.update_session(session_id, status="error", error=reason[:500])
                                await self.storage.finish_run(
                                    run_id, "error", error=reason, step_count=state["total_steps"]
                                )
                                return state
                            summary = "deliverable created: " + delivered_hint
                            if CHECKPOINT_ENABLED:
                                await durability.clear_checkpoints(self.storage, session_id)
                            await self.storage.update_session(session_id, status="done", error="")
                            await self.storage.finish_run(
                                run_id, "done", output=summary, step_count=state["total_steps"]
                            )
                            await self.emit(session_id, "done", {"summary": summary, "text": summary}, run_id)
                            await self.emit(session_id, "session.status", {"status": "done"}, run_id)
                            return state
                        guard_text = (
                            "[system no-progress guard] The requested deliverable already exists at: "
                            + delivered_hint + ". Stop calling tools now; do not rerun the same command. "
                            "Reply with a short summary of the deliverable and finish."
                        )
                        if repeated_announcement:
                            guard_text += (
                                " You have announced the same step (\""
                                + prefix[:60]
                                + "\") several times in a row; announcing is not progress."
                            )
                        await self.emit(
                            session_id,
                            "no_progress.nudge",
                            {
                                "streak": state["no_progress_nudges"],
                                "finalize": True,
                                "delivered": state["output_targets"],
                            },
                            run_id,
                        )
                    elif missing:
                        state["write_only"] = True
                        guard_text = (
                            "[system no-progress guard] You are repeating the same tool calls without making "
                            "progress. Stop re-reading; you already have the content you need. The requested "
                            "deliverable does not exist yet at: " + target_hint + ". Call write_file now to "
                            "create it at that exact path (create the directory first if needed). Read-only "
                            "tools are disabled until the file is written."
                        )
                        await self.emit(
                            session_id,
                            "no_progress.nudge",
                            {
                                "streak": state["no_progress_nudges"],
                                "missing": missing,
                                "read_paths": len(state["read_path_counts"]),
                            },
                            run_id,
                        )
                    else:
                        guard_text = (
                            "[system no-progress guard] You are repeating the same tool calls without making "
                            "progress. Do not call the same tool with the same arguments again. Use the results "
                            "you already have, finish the current step, and produce the final answer."
                        )
                        await self.emit(
                            session_id,
                            "no_progress.nudge",
                            {
                                "streak": state["no_progress_nudges"],
                                "missing": [],
                                "read_paths": len(state["read_path_counts"]),
                            },
                            run_id,
                        )
                    messages.append({"role": "user", "content": guard_text})
                    if not has_deliverable and state["no_progress_nudges"] > NO_PROGRESS_MAX:
                        if missing:
                            reason = f"no progress: deliverable not created at {target_hint} after repeated retries"
                        else:
                            reason = "no progress: repeated identical tool calls"
                        await self.emit(session_id, "error", {"message": reason}, run_id)
                        await self.storage.update_session(session_id, status="error", error=reason)
                        await self.storage.finish_run(
                            run_id, "error", error=reason, step_count=state["total_steps"]
                        )
                        return state

            if state["reference_paths"] and state["reference_outputs"]:
                state["reference_drift"] = self._reference_drift(
                    state["reference_paths"], state["reference_outputs"]
                )
            await self._repair_after_tests(session, parsed_calls, results, messages, run_id, state)
            await self.storage.update_session(session_id, status="running")
            if CHECKPOINT_ENABLED and (
                CHECKPOINT_EVERY_STEPS <= 1 or state["total_steps"] % CHECKPOINT_EVERY_STEPS == 0
            ):
                await durability.save_checkpoint(
                    self.storage,
                    session_id,
                    state["total_steps"],
                    run_id,
                    cursor,
                    session.get("plan") or "",
                    f"step {state['total_steps']} completed",
                )
                await self.emit(
                    session_id, "checkpoint.saved", {"step": state["total_steps"]}, run_id
                )
                await self.storage.update_run_progress(run_id, state["total_steps"])
        if CHECKPOINT_ENABLED:
            await durability.save_checkpoint(
                    self.storage,
                    session_id,
                    state["total_steps"],
                    run_id,
                    cursor,
                    session.get("plan") or "",
                    f"step {state['total_steps']} completed",
                )
            await self.emit(session_id, "checkpoint.saved", {"step": state["total_steps"]}, run_id)

        if CHECKPOINT_ENABLED:
            await durability.clear_checkpoints(self.storage, session_id)
        await self.storage.finish_run(run_id, "done", output=state["final_text"], step_count=state["total_steps"])
        await self.emit(session_id, "done", {"summary": "turn complete", "text": state["final_text"]}, run_id)
        await self.emit(session_id, "session.status", {"status": "done"}, run_id)
        await self.events.flush()
        await self.storage.update_session(session_id, status="done", error="")
        return state

    async def _execute_calls(
        self,
        session: dict[str, Any],
        calls: list[ToolCall],
        run_id: str,
        state: dict[str, Any],
    ) -> dict[str, ToolResult]:
        results: dict[str, ToolResult] = {}
        readonly: list[ToolCall] = []
        writes: list[ToolCall] = []
        for call in calls:
            spec = self.tools.get(call.name)
            if spec and spec.readonly and not spec.confirm:
                readonly.append(call)
            else:
                writes.append(call)
        if readonly:
            gathered = await asyncio.gather(
                *[self._execute_one(session, call, run_id, state) for call in readonly],
                return_exceptions=True,
            )
            for call, item in zip(readonly, gathered):
                if isinstance(item, Exception):
                    results[call.call_id] = ToolResult(call_id=call.call_id, name=call.name, ok=False, error=str(item))
                else:
                    results[call.call_id] = item
        for call in writes:
            results[call.call_id] = await self._execute_one(session, call, run_id, state)
        return results

    async def _execute_one(self, session: dict[str, Any], call: ToolCall, run_id: str, state: dict[str, Any]) -> ToolResult:
        session_id = session["id"]
        workspace = session.get("workspace") or ""
        await self.emit(session_id, "tool.start", {"call_id": call.call_id, "tool": call.name, "args": call.arguments}, run_id)
        started = time.monotonic()
        prior = (state.get("_call_prior") or {}).get(call.call_id, 0)
        suppressed: ToolResult | None = None
        path_reads = (state.get("_suppressed_paths") or {}).get(call.call_id)
        if NO_PROGRESS_GUARD and path_reads:
            # Same file read LOOP_PATH_SUPPRESS_LIMIT times already (with varying
            # ranges): answer with an authoritative digest instead of more bytes.
            suppressed = ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=True,
                result=self._loop_digest(session, call, int(path_reads), state),
                summary="path over-read; digest returned",
            )
        elif NO_PROGRESS_GUARD and state.get("write_only") and call.name in READONLY_TOOLS:
            suppressed = ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=True,
                result=(
                    "[no-progress guard] Read-only tools are disabled because the requested deliverable "
                    "is still missing. Do not read again; call write_file now to create the file."
                ),
                summary="read disabled by no-progress guard",
            )
        elif NO_PROGRESS_GUARD and call.name in _DUPLICATE_TOOLS and prior >= REPEAT_TOOL_LIMIT:
            suppressed = ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=True,
                result=(
                    "[no-progress guard] This exact call was already executed; the result is in the "
                    "history above. Do not repeat it. Use what you already have and write the deliverable."
                ),
                summary="duplicate call suppressed",
            )
        spec = self.tools.get(call.name)
        if suppressed is not None:
            result = suppressed
        elif not spec:
            result = ToolResult(call_id=call.call_id, name=call.name, ok=False, error=f"unknown tool: {call.name}", summary="unknown tool")
        elif call.name == "task" and SUBAGENT_ENABLED:
            text = await self._run_subagent(session, call.arguments, state)
            result = ToolResult(call_id=call.call_id, name=call.name, ok=True, result=text, summary=text[:200])
        else:
            decision = await self.policy.authorize(spec, session)
            if decision.requires_approval:
                from tools import dev as dev_tools

                preview = await asyncio.to_thread(dev_tools.preview, call.name, workspace, call.arguments)
                approved, reason = await self.manager.ask_approval(session, call, run_id, preview)
                if not approved:
                    result = ToolResult(
                        call_id=call.call_id,
                        name=call.name,
                        ok=False,
                        error=f"user rejected: {reason or 'no reason'}",
                        summary=f"{call.name} rejected",
                    )
                else:
                    result = await self._run_tool(session, call, state)
            elif not decision.allowed:
                result = ToolResult(call_id=call.call_id, name=call.name, ok=False, error=decision.reason, summary="policy denied")
            else:
                result = await self._run_tool(session, call, state)

        result.elapsed_ms = int((time.monotonic() - started) * 1000)
        await self.emit(
            session_id,
            "tool.end",
            {
                "call_id": call.call_id,
                "tool": call.name,
                "ok": result.ok,
                "ms": result.elapsed_ms,
                "summary": result.summary,
                "error": result.error,
            },
            run_id,
        )
        return result

    @staticmethod
    def _call_timeout(call: ToolCall) -> float | None:
        """Let run_shell's optional ``timeout`` argument extend the wrapper timeout.

        Without this the registry would still cut the call at the spec default
        (150s) even when the model explicitly asked for a longer build/download.
        """
        if call.name != "run_shell":
            return None
        try:
            requested = float(call.arguments.get("timeout") or 0)
        except (TypeError, ValueError):
            requested = 0.0
        if requested <= 0:
            return None
        return min(requested, SHELL_TIMEOUT_MAX) + 30

    async def _run_tool(self, session: dict[str, Any], call: ToolCall, state: dict[str, Any]) -> ToolResult:
        workspace = session.get("workspace") or ""
        effects = state.get("effects") or {}
        if call.name in IDEMPOTENT_TOOLS and call.call_id in effects:
            return ToolResult(call_id=call.call_id, name=call.name, ok=True, result=effects[call.call_id], summary="restored prior effect")
        ctx = ToolContext(
            runtime=self,
            session=session,
            workspace=workspace,
            call=call,
            emit=self.emit,
            run_id=state.get("run_id") or "",
        )
        result = await self.tools.execute(call, ctx, timeout_s=self._call_timeout(call))
        if result.ok and call.name in IDEMPOTENT_TOOLS:
            await durability.record_effect(self.storage, session["id"], state["total_steps"], call.name, call.arguments, str(result.result), workspace)
        return result

    @staticmethod
    def _safe_component(value: str, fallback: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value or "")).strip("._")
        return (clean or fallback)[:80]

    def _save_tool_log(self, session_id: str, call_id: str, text: str) -> str:
        try:
            directory = TOOL_LOGS_DIR / self._safe_component(session_id, "session")
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{self._safe_component(call_id, uuid.uuid4().hex[:12])}.log"
            path.write_text(text, encoding="utf-8", errors="replace")
            return str(path)
        except OSError:
            return ""

    def _tool_context_text(
        self,
        result: ToolResult,
        call: ToolCall | None = None,
        state: dict[str, Any] | None = None,
        session_id: str = "",
    ) -> str:
        payload = {
            "ok": result.ok,
            "result": result.result,
            "error": result.error,
            "artifact_id": result.artifact_id,
        }
        full_result = result.result
        if call is not None and call.name == "run_shell" and isinstance(full_result, str):
            key = ""
            previous = None
            if state is not None:
                key = "run_shell:" + str(
                    call.arguments.get("command")
                    or json.dumps(call.arguments, ensure_ascii=False, sort_keys=True, default=str)
                )
                previous = (state.get("_tool_failures") or {}).get(key)
            compressed, fingerprint = compress_tool_output(full_result, ok=result.ok, previous=previous)
            if state is not None:
                bucket = state.setdefault("_tool_failures", {})
                if result.ok:
                    bucket.pop(key, None)
                else:
                    bucket[key] = fingerprint
            if (
                compressed != full_result
                and len(full_result) > TOOL_COMPRESS_MIN_CHARS
                and "same failure as previous call" not in compressed
            ):
                log_path = self._save_tool_log(session_id, call.call_id, full_result)
                if log_path:
                    compressed += f"\n[full output: {log_path}]"
            payload["result"] = compressed
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > TOOL_RESULT_CONTEXT_CHARS:
            # Cut at a line boundary when possible so the model never sees half a line.
            cut = text.rfind("\\n", TOOL_RESULT_CONTEXT_CHARS // 2, TOOL_RESULT_CONTEXT_CHARS)
            if cut <= 0:
                cut = TOOL_RESULT_CONTEXT_CHARS
            total = len(text)
            text = text[:cut] + TOOL_RESULT_CONTEXT_MARK.replace(
                "re-read the precise range if needed",
                f"showed {cut} of {total} chars; re-read the precise range if needed",
            )
        return text

    def _loop_digest(self, session: dict[str, Any], call: ToolCall, reads: int, state: dict[str, Any]) -> str:
        workspace = session.get("workspace") or ""
        path = _call_path(call)
        full = path if os.path.isabs(path) else os.path.join(workspace, path)
        if not os.path.isfile(full):
            return f"[loop guard] {path} was read {reads} times in this run and does not exist. Stop reading it."
        deliverables = {
            os.path.normcase(os.path.normpath(item))
            for target in state.get("output_targets") or []
            for item in deliverable_check.deliverable_files(target)
        }
        if os.path.normcase(os.path.normpath(full)) in deliverables:
            # Re-reading its own half-finished output was the dominant loop: give
            # the precise state instead of the bytes.
            return (
                f"[loop guard] {path} is your own deliverable and has been read {reads} times; further reads "
                "are suppressed. Authoritative state:\n" + delivery_ledger(state)
            )
        if Path(full).suffix.lower() in (".html", ".htm", ".css", ".svg", ".js", ".ts", ".jsx", ".tsx", ".vue", ".svelte"):
            try:
                body = reference.digest(full, 9000)
            except Exception as exc:
                body = f"(digest failed: {type(exc).__name__}: {exc})"
        else:
            try:
                raw = Path(full).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return f"[loop guard] {path}: cannot read ({exc}). Stop reading it."
            body = raw[:6000] + ("\n...[clipped at 6000 chars]" if len(raw) > 6000 else "")
        return (
            f"[loop guard] {path} has already been read {reads} times in this run; further reads are suppressed. "
            "Use the digest below together with what you already have, and move on to producing the deliverable.\n\n"
            + body
        )

    def _deliverable_issues(self, session: dict[str, Any], state: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        for target in state.get("output_targets") or []:
            # Only the newest document per target is the deliverable; stale drafts
            # and side files must not block completion.
            for path in deliverable_check.main_document(deliverable_check.deliverable_files(target)):
                found = deliverable_check.completeness_issues(
                    path,
                    reference_paths=state.get("reference_paths") or [],
                    min_visible_chars=DELIVERY_MIN_VISIBLE_CHARS,
                    min_reference_ratio=DELIVERY_MIN_REFERENCE_RATIO,
                )
                issues.extend(f"{Path(path).name}: {item}" for item in found)
        return issues[:8]

    async def _ensure_task_summary(
        self,
        session_id: str,
        run_id: str,
        session: dict[str, Any],
        state: dict[str, Any] | None = None,
        status: str = "",
        error: str = "",
    ) -> None:
        """Persist a closing summary so an error never ends with an empty bubble.

        The model normally writes the final summary. This fallback covers the
        error/cancel paths (and a done run whose final text is empty), where the
        last assistant message otherwise has no content.
        """
        try:
            fresh = await self.storage.get_session(session_id)
            if not fresh:
                # The session was purged/deleted while the run was finishing;
                # do not resurrect it with a summary message.
                return
            session = fresh
            state = state or {}
            status = (status or session.get("status") or "error").strip()
            error = (error or session.get("error") or "").strip()
            if status == "done" and str(state.get("final_text") or "").strip():
                return
            if status not in TERMINAL_STATUSES:
                status = "error" if error else status
            rows = await self.storage.list_messages_tail(session_id, limit=8)
            last_assistant = next(
                (row for row in reversed(rows) if row.get("role") == "assistant"), None
            )
            if last_assistant and str(last_assistant.get("content") or "").strip().startswith(
                "## 任务收尾总结"
            ):
                return
            text = task_summary_text(session, state, status, error)
            row = await self.storage.add_message(session_id, run_id, "assistant", text)
            try:
                await self.storage.finish_run(
                    run_id,
                    status,
                    output=text,
                    error=error,
                    step_count=int(state.get("total_steps") or 0),
                )
            except Exception:
                pass
            await self.emit(
                session_id,
                "message.saved",
                {"msg_id": row["id"], "role": "assistant", "content": text, "has_tools": False},
                run_id,
            )
            await self.emit(session_id, "task.summary", {"status": status, "text": text}, run_id)
        except Exception:
            # A closing summary must never become the only failure the user sees.
            return

    @staticmethod
    def _audit_nudge_text(issues: list[str]) -> str:
        listed = "\n".join(f"- {item}" for item in issues)
        return (
            "[system delivery audit] The deliverable exists but is NOT complete:\n"
            + listed
            + "\nFix every item now: append the missing sections in order (<= 150 lines per apply_patch/edit_file), "
            "close the document, and make every navigation anchor point at an existing id. Do not re-read the "
            "reference or the output directory; use what you already have. Then reply with a short summary."
        )

    async def _inject_pending(
        self, session_id: str, messages: list[dict[str, Any]], cursor: int
    ) -> tuple[int, list[dict[str, Any]]]:
        rows = await self.storage.list_messages(session_id, after_rowid=cursor)
        new_users = [row for row in rows if row["role"] == "user"]
        if not new_users:
            return cursor, []
        merged: list[dict[str, Any]] = []
        for row in new_users:
            content = row.get("content") or ""
            verdict = classify_instruction(content)
            if verdict.kind == "chatter":
                continue
            if verdict.kind == "interrupt":
                messages.append({"role": "user", "content": interrupt_message(content)})
            else:
                messages.append({"role": "user", "content": addition_message(content, verdict.priority)})
            merged.append(
                {
                    "kind": verdict.kind,
                    "priority": verdict.priority,
                    "preview": content.strip()[:160],
                }
            )
        return int(new_users[-1]["seq"]), merged

    async def _repair_after_tests(self, session, calls, results, messages, run_id, state) -> None:
        if not REPAIR_LOOP_ENABLED:
            return
        failures = []
        for call in calls:
            if call.name != "run_shell":
                continue
            result = results.get(call.call_id)
            if not result or result.ok or not repair.is_test_command(str(call.arguments.get("command") or "")):
                continue
            parsed = repair.parse_pytest(str(result.result))
            if parsed["summary"]["failed"]:
                failures.extend(parsed["failures"])
        if not failures:
            return
        fingerprint = repair.failure_fingerprint(failures)
        seen = state["repair_fingerprints"].get(fingerprint, 0) + 1
        state["repair_fingerprints"][fingerprint] = seen
        guidance = repair.repair_guidance(failures, [(fingerprint, seen - 1)])
        snippet = repair.test_snippet(session.get("workspace") or "", failures)
        if snippet:
            guidance += "\n[failing test source snippet]\n" + snippet
        messages.append({"role": "user", "content": guidance})
        await self.emit(str(session.get("id") or ""), "repair.loop", {"failures": len(failures), "fingerprint": fingerprint, "seen": seen}, run_id)

    async def _quick_spec_review(self, session: dict[str, Any], user_text: str, provider: str, model: str, state: dict[str, Any]) -> str:
        workspace = session.get("workspace") or ""
        diff_text = await asyncio.to_thread(_workspace_diff, workspace)
        prompt = (
            "You are a strict acceptance reviewer. You receive the user's requirement and the unified diff of the "
            "workspace. Check every explicit requirement, especially inputs that OMIT optional fields, unknown-field "
            "preservation, boundary values, concurrency/atomicity, and 'must not change' constraints. Only report real "
            "violations; do not request scope expansion. Reply in exactly one of these forms:\n"
            "VERDICT: PASS\n"
            "or\n"
            "VERDICT: GAPS\n- concrete gap 1\n- concrete gap 2\n\n"
            "Requirement:\n" + (user_text or "")[:6000]
        )
        if diff_text.strip():
            prompt += "\n\nUnified diff (possibly truncated):\n" + diff_text[:24000]
            messages = [
                {"role": "system", "content": "Review implementation diffs against explicit requirements."},
                {"role": "user", "content": prompt},
            ]
            for audit_thinking in ("low", "off"):
                try:
                    text = ""
                    usage: dict[str, Any] = {}
                    async for event in self.gateway.stream(
                        provider, model, messages, None, audit_thinking, strict=bool(state.get("strict_route"))
                    ):
                        if event.get("type") == "message":
                            text = str((event.get("message") or {}).get("content") or "")
                            usage = event.get("usage") or {}
                    if usage:
                        try:
                            await self.storage.record_usage(
                                session["id"],
                                f"audit-{uuid.uuid4().hex[:10]}",
                                provider,
                                model,
                                usage,
                            )
                        except Exception:
                            pass
                    if text.strip():
                        return text
                except Exception:
                    continue
        try:
            return await self._run_subagent(
                session,
                {
                    "description": "spec audit",
                    "readonly": True,
                    "prompt": prompt + "\n\nInspect the workspace files directly with read-only tools.",
                },
                state,
            )
        except Exception:
            return "VERDICT: PASS (reviewer unavailable)"

    async def _run_subagent(self, session: dict[str, Any], args: dict[str, Any], state: dict[str, Any]) -> str:
        description = str(args.get("description") or "subtask")[:40]
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return f"[subagent {description}] no prompt provided"
        readonly = bool(args.get("readonly", True))
        allowed = set(READONLY_TOOLS)
        if not readonly:
            allowed |= {"write_file", "edit_file", "apply_patch", "multi_edit", "run_shell", "git"}
        schemas = [s for s in self.tools.openai_tools() if (s.get("function") or {}).get("name") in allowed]
        names = ", ".join((s.get("function") or {}).get("name", "") for s in schemas)
        system = (
            f"You are a subagent dispatched by HaoYuan. Complete one self-contained subtask and return a conclusion.\n"
            f"Workspace: {session.get('workspace') or '(none)'}\n"
            f"Available tools: {names}\n"
            "You cannot ask the user questions. Read-only reconnaissance by default. Report the conclusion first, "
            "then key facts with file paths and line numbers. Never fabricate. Never modify files unless write access is explicit."
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        steps = 0
        calls = 0
        final = ""
        seen_calls: dict[str, int] = {}
        findings: list[str] = []
        provider, model = resolve(session.get("provider"), session.get("model"))

        async def run() -> str:
            nonlocal steps, calls, final
            while steps < min(SUBAGENT_MAX_STEPS, AGENT_MAX_STEPS):
                steps += 1
                message = None
                usage = {}
                async for event in self.gateway.stream(
                    provider, model, messages, schemas, "low", strict=bool(state.get("strict_route"))
                ):
                    if event.get("type") == "message":
                        message = event.get("message")
                        usage = event.get("usage") or {}
                if not message:
                    break
                if usage:
                    try:
                        await self.storage.record_usage(
                            session["id"], f"sub-{uuid.uuid4().hex[:10]}", provider, model, usage
                        )
                    except Exception:
                        pass
                tool_calls = message.get("tool_calls") or []
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.get("content"),
                        **({"tool_calls": tool_calls} if tool_calls else {}),
                    }
                )
                if not tool_calls:
                    final = message.get("content") or ""
                    break
                for raw in tool_calls:
                    function = raw.get("function") or {}
                    try:
                        call_args = json.loads(function.get("arguments") or "{}")
                    except (ValueError, TypeError):
                        call_args = {}
                    calls += 1
                    dedupe_key = f"{function.get('name') or ''}:{json.dumps(call_args, ensure_ascii=False, sort_keys=True)}"
                    seen_calls[dedupe_key] = seen_calls.get(dedupe_key, 0) + 1
                    if seen_calls[dedupe_key] > REPEAT_TOOL_LIMIT:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": raw.get("id") or uuid.uuid4().hex[:12],
                                "content": "[subagent guard] duplicate call suppressed; use the earlier result and return your conclusion.",
                            }
                        )
                        continue
                    call = ToolCall(call_id=raw.get("id") or uuid.uuid4().hex[:12], name=function.get("name") or "", arguments=call_args)
                    ctx = ToolContext(runtime=self, session=session, workspace=session.get("workspace") or "", call=call, emit=self.emit)
                    result = await self.tools.execute(call, ctx, timeout_s=self._call_timeout(call))
                    body = str(result.result if result.ok else result.error)
                    if call.name == "run_shell":
                        body, _fingerprint = compress_tool_output(body, ok=result.ok)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "content": body[:TOOL_RESULT_CONTEXT_CHARS],
                        }
                    )
                    if result.ok and body:
                        findings.append(f"- {call.name}: {body[:400].replace(chr(10), ' ')}")
                    if result.ok and call.name == "describe_image":
                        attachment = vision.native_attachment_message(
                            result.result, session.get("workspace") or ""
                        )
                        if attachment:
                            messages.append({"role": "user", "content": attachment})
            return final

        try:
            final = await asyncio.wait_for(run(), timeout=SUBAGENT_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            return f"[subagent {description}] timed out after {int(SUBAGENT_TIMEOUT_SEC)}s ({steps} steps / {calls} tools)"
        except Exception as exc:
            return f"[subagent {description}] failed: {type(exc).__name__}: {exc}"
        final_text = (final or "").strip()
        if not final_text and findings:
            # Never hand the parent an empty result: that makes it repeat all the
            # reconnaissance itself (one observed cause of the main-agent loop).
            final_text = (
                "Partial findings (subagent hit its step limit without a final answer):\n"
                + "\n".join(findings[-12:])
            )
        body = final_text or f"(subagent ran {steps} steps / {calls} tools but returned no text)"
        return f"[subagent {description} - {steps} steps / {calls} tools]\n{body[:SUBAGENT_SUMMARY_CHARS]}"

    async def _register_change_artifact(self, session_id: str, call: ToolCall, result: ToolResult) -> None:
        path = str(call.arguments.get("path") or "")
        if not path:
            return
        session = await self.storage.get_session(session_id)
        workspace = (session or {}).get("workspace") or ""
        full = path if os.path.isabs(path) else os.path.join(workspace, path)
        if not os.path.isfile(full):
            return
        try:
            record = await self.storage.create_artifact(session_id, full, "change", os.path.basename(full), os.path.getsize(full))
            await self.emit(session_id, "artifact.created", record)
        except Exception:
            pass

    async def _register_generated_artifact(self, session_id: str, call: ToolCall, result: ToolResult) -> None:
        if call.name != "make_plan" or not result.ok:
            return
        try:
            info = json.loads(str(result.result))
        except (ValueError, TypeError):
            return
        path = info.get("path")
        if not path or not os.path.isfile(path):
            return
        try:
            record = await self.storage.create_artifact(
                session_id, path, info.get("artifact_kind") or "document", os.path.basename(path), os.path.getsize(path)
            )
            await self.emit(session_id, "artifact.created", record)
        except Exception:
            pass

    @staticmethod
    def _reference_drift(reference_paths: list[str], outputs: list[str]) -> str:
        reports: list[str] = []
        style_refs = [
            ref for ref in reference_paths if Path(ref).suffix.lower() in (".html", ".htm", ".css")
        ]
        for target in dict.fromkeys(outputs):
            for ref in style_refs:
                try:
                    if os.path.realpath(ref) == target:
                        continue
                    report = reference.compare(ref, target)
                except Exception:
                    continue
                match = re.search(r"style fidelity:\s*(\d+)/100", report)
                if match and int(match.group(1)) < 85:
                    reports.append(report)
                    break
        return "\n\n".join(reports)

    def _system_prompt(
        self,
        session: dict[str, Any],
        agent,
        kind: str,
        provider: str,
        model: str,
        task_type: str,
        lite: bool,
        qa: bool,
        matched: list,
        skill_how: str,
        repo_map_text: str,
        casual: bool = False,
        context_pack_text: str = "",
        reference_text: str = "",
        research: bool = False,
        doc_mode: bool = False,
    ) -> str:
        workspace = session.get("workspace") or ""
        parts = [SYSTEM_RULES]
        if agent.instructions:
            parts.append("\n# Agent charter\n" + agent.instructions)
        parts.append(
            "\n# Environment\n"
            f"- OS: {os.name} ({platform_name()})\n"
            f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"- Workspace: {workspace or '(none; chat-only mode)'}\n"
            f"- Mode: {kind} / task type: {task_type} / model: {provider}/{model}\n"
            f"- Effort: {'lite' if lite else 'full'}\n"
            "- Shell: commands run in the platform shell (cmd.exe on Windows); common tail/head/cat pipes are auto-adapted.\n"
        )
        if not workspace:
            parts.append(
                "\n# Chat-only mode\nNo workspace is bound, so file editing and shell commands are unavailable. "
                "You can still use system_info for read-only host details (OS, CPU, memory, disk, uptime). "
                "Tell the user to bind a workspace only when file or command access is actually needed.\n"
            )
        if qa:
            parts.append(
                "\n# Question mode\nThe user is asking a question, not requesting execution. Answer clearly without starting a task loop. "
                "If the question is about this machine's OS, CPU, memory, disk or uptime, use system_info or the live host information below.\n"
            )
        if casual:
            parts.append(
                "\n# Conversation mode\nThis is casual conversation or a general question, not a workspace task. "
                "Answer directly and naturally. Do not inspect the workspace or start a task loop. "
                "Exception: for questions about this machine's OS, CPU, memory, disk or uptime, use system_info or the live host information below. "
                "For questions that need current or external facts (prices, quotes, news, docs, versions, licenses), use web_fetch on the relevant public URL instead of claiming you have no internet access; if a fetch fails, say so and label the fact unverified.\n"
            )
        if kind == "plan":
            parts.append(
                "\n# Plan document mode\nWrite a rigorous proposal. If the user supplies a reference HTML or an explicit "
                "output path, write the document directly with write_file/apply_patch in the reference style; use make_plan "
                "only when no reference and no target path are given. Include executive summary, KPIs, sections, tables, "
                "risks, milestones, and budget. Keep the document self-contained.\n"
            )
        if doc_mode:
            parts.append("\n" + DOCUMENT_RULES)
        if kind in ("dev", "coding") and workspace and not qa:
            if not doc_mode:
                parts.append(
                    "\n# Coding protocol\n"
                    "1. Inspect the project (project_scan / list_dir / repo map) before editing.\n"
                    "2. Locate symbols precisely with search_symbol and read_range.\n"
                    "3. Apply minimal patches; never rewrite a file unless it is new.\n"
                    "4. After code edits, run the relevant verification command once.\n"
                    "5. Finish with a short summary of files changed, verification result, and any remaining risk.\n"
                )
            parts.append(
                "\n# Acceptance protocol (highest priority)\n"
                "- If the task ships a checker or test entry (e.g. /app/check_*.py, /app/tests, run-tests.sh, *_test.py, pytest), run it and keep iterating until it passes before you finish.\n"
                "- Produce every deliverable at the exact path/format the task names; re-read the requirement before writing the final file.\n"
                "- Numeric deliverables: re-read the requested precision and units; write full precision by default and confirm the value with a second method or an independent calculation before finishing.\n"
                "- You are running unattended: never ask the user questions. If something is ambiguous, choose the most literal reading and proceed.\n"
                "- Do not end the turn with a plan or an apology: end only after the artifacts exist and (if available) the checker passes.\n"
            )
            if lite:
                parts.append("This is a lightweight task: keep the loop short, avoid unnecessary planning, and verify once.\n")
            if TWO_PHASE_PLAN and not lite and not doc_mode:
                parts.append(
                    "\n# Two-phase discipline\nFor complex tasks, first locate and plan (search_symbol/read_range/plan_task), "
                    "then execute patches, then verify. Do not interleave broad exploration with edits.\n"
                )
            if task_type == "debug" and not doc_mode:
                parts.append(
                    "\n# Debug protocol\nReproduce the failure, read the failing assertion, fix the smallest root cause, "
                    "and rerun the same test. If the same failure fingerprint repeats, change strategy instead of retrying.\n"
                )
        if research or kind == "plan" or doc_mode:
            parts.append("\n" + RESEARCH_RULES)
        if matched:
            parts.append(SkillLibrary.render(matched, skill_how, 4000 if lite else 8000))
        if reference_text:
            parts.append(
                "\n\n# Reference source contract\n"
                "The user pointed at an existing file as the format/style source. This digest is the ground truth:\n"
                "- Reproduce its design tokens (palette, font stack, radius, shadows, max-width, breakpoints) instead of a generic theme.\n"
                "- Preserve its information architecture: same nav pattern, section order, component vocabulary (cards, KPIs, tables, SVG diagrams, timelines, callouts, overlays).\n"
                "- Keep its interaction model (sticky nav, scroll spy, login gate, animations) unless the user says otherwise.\n"
                "- If the output file already exists, this is an in-place edit: preserve the existing style 1:1 and change only the requested content. Do not create a fresh visual design.\n"
                "- Never add unrequested meta content. A resume/CV sent to an interviewer must not contain interview Q&A, JD-matching notes or internal prep sections unless explicitly requested.\n"
                "- Before writing, call reference_digest to confirm details; after writing, call web_audit with the reference path and fix drift.\n"
                "If the reference and a built-in scaffold conflict, the reference wins.\n\n"
                + reference_text
            )
        if not casual:
            if context_pack_text:
                parts.append(
                    "\n\n# Preloaded relevant source (current at task start)\n"
                    "These files are already in context. Do not re-read them in full; use read_range only for a "
                    "specific area you still need, or after you have edited the file.\n\n"
                    + context_pack_text
                )
            if repo_map_text:
                parts.append("\n\n# Repository map (paths and key symbols)\n" + repo_map_text)
            project_memory = self._read_project_memory(workspace)
            if project_memory:
                parts.append("\n\n# Project memory (PROJECT.md / AGENTS.md)\n" + project_memory)
            plan = self._plan_text(session)
            if plan:
                parts.append("\n\n# Current plan\n" + plan)
        return "\n".join(parts)

    @staticmethod
    def _plan_text(session: dict[str, Any]) -> str:
        try:
            plan = json.loads(session.get("plan") or "{}")
        except (ValueError, TypeError):
            return ""
        steps = plan.get("steps") or []
        if not steps:
            return ""
        lines = [f"Title: {plan.get('title', '')}"]
        for index, step in enumerate(steps, 1):
            note = f" - {step['note']}" if step.get("note") else ""
            lines.append(f"{index}. [{step.get('s', 'pending')}] {step.get('t', '')}{note}")
        return "\n".join(lines)

    @staticmethod
    def _read_project_memory(workspace: str) -> str:
        if not workspace:
            return ""
        chunks = []
        for name in ("AGENTS.md", "PROJECT.md", "CLAUDE.md", "README.md"):
            path = Path(workspace) / name
            if path.is_file():
                try:
                    chunks.append(f"## {name}\n" + path.read_text(encoding="utf-8", errors="replace")[:3000])
                except OSError:
                    continue
            if len(chunks) >= 2:
                break
        return "\n\n".join(chunks)


_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]?$")


def _is_broad_root(path: str) -> bool:
    """根目录/用户主目录下自动建索引会遍历整个文件系统，既慢又无助于定位项目。"""
    if not path:
        return False
    try:
        real = os.path.realpath(path).rstrip("\\/") or os.sep
    except OSError:
        return False
    if _DRIVE_ROOT_RE.match(path.strip()):
        return True
    home = os.path.realpath(os.path.expanduser("~")).rstrip("\\/") or os.sep
    roots = {os.path.abspath(os.sep).rstrip("\\/") or os.sep, home, "/root", "/home"}
    return real in roots


def platform_name() -> str:
    import platform

    return platform.platform()


def level_is_complex(task_type: str, content: str) -> bool:
    return task_type in ("debug", "dev") or bool(content)
