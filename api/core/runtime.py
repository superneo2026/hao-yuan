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

from configs.configs import (
    AGENT_MAX_STEPS,
    AGENT_MAX_TOTAL_STEPS,
    APPLY_PATCH_ENABLED,
    ARTIFACTS_DIR,
    CHECKPOINT_ENABLED,
    CHECKPOINT_EVERY_STEPS,
    DEFAULT_AGENT,
    IDEMPOTENT_TOOLS,
    LITE_MODE,
    LITE_MULTIPHASE_HINTS,
    LITE_SINGLE_FILE_MAX_PATHS,
    LITE_TOOL_SET,
    MAX_SESSION_COST,
    REPAIR_LOOP_ENABLED,
    REPO_MAP_ENABLED,
    SUBAGENT_ENABLED,
    SUBAGENT_MAX_STEPS,
    SUBAGENT_SUMMARY_CHARS,
    SUBAGENT_TIMEOUT_SEC,
    TOOL_RESULT_CONTEXT_CHARS,
    TOOL_RESULT_CONTEXT_MARK,
    TOOL_SCHEMA_TRIM,
    TWO_PHASE_PLAN,
    VERIFY_CODE_EXTS,
    VERIFY_CMD_HINTS,
    VERIFY_GATE,
    VERIFY_MAX_NUDGE,
)
from configs.models import price_for, resolve
from core.contracts import ToolCall, ToolContext, ToolResult
from harness import durability, reference, repair, repoindex, sysinfo
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
VIDEO_INTENT = ("视频", "剪辑", "分镜", "配音", "口播", "字幕", "成片", "宣传片", "短视频", "storyboard")
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

READONLY_TOOLS = ("read_file", "read_range", "search_symbol", "glob", "grep", "list_dir", "project_scan")

SYSTEM_RULES = """You are HaoYuan (豪源), an autonomous AI coding agent. You work directly in a real workspace and deliver verified changes.

# Operating rules
- Work autonomously. Do not ask for permission for read-only actions. For writes or commands, the system shows a preview and asks the user.
- Locate before editing: use search_symbol, grep, read_range, then apply the smallest possible patch.
- Prefer apply_patch / edit_file / multi_edit over write_file. Never rewrite a whole file for a small change.
- Large files: model output is capped, so never emit an entire big file in one tool call. Create it with write_file using a small skeleton, then append the remaining sections in chunks (<= 150 lines each) with apply_patch or edit_file. If a tool result says the arguments were truncated, split the write instead of retrying the same call.
- Batch independent tool calls in the same assistant message. Reads can run in parallel; writes run in order.
- Verify code changes: run the project's tests/lint/build once after the final code edit. Documentation-only changes do not require a test run.
- Use the task tool for broad read-only reconnaissance when raw tool output would flood the context. It returns only conclusions.
- Use plan_task for multi-step work and update_plan as you progress.
- Match effort to size: a one-symbol fix needs no plan and no whole-repo scan; a multi-file feature needs a short plan and a checklist.
- Budget exploration. After roughly 8 exploratory calls (read/grep/search), commit to the best hypothesis and start editing. Do not read files that are not on the failing path, and never re-read an unchanged range you already have.
- Run the project's full verification command at most twice: once after the edit, and once more only if the first run failed and you changed code again. When it passes, stop testing and summarize.
- Never fabricate results. If something cannot be verified, say exactly what is unverified and why.
- Answer in the user's language. Be concise and outcome-oriented.
- If the user only greets you or makes casual conversation, reply naturally and do not inspect the workspace, call tools, or start a task.
- Do not run destructive commands, do not push to git, and do not touch files outside the workspace.
- When the user points at an existing file/page as the format or style source, treat it as a hard reference: call reference_digest, then reuse its palette, typography, layout width, breakpoints, components and interactions. Do not substitute a different built-in template. If a file path is given, never assume you already know its contents from memory.
- Preserve the existing artifact unless the user explicitly asks for a redesign. When a target file already exists, edit it in place and keep its markup, CSS, layout system, section order and naming exactly as they are except for the diff the request requires. Never re-theme, restructure, renumber or "polish" on your own initiative; style/format changes require an explicit user request.
- Deliver only what was asked. Do not add unrequested sections, scaffolding, commentary, checklists, FAQs, interview prep or meta-analysis. For outward-facing documents (resume/CV, cover letter, proposal, report), match the stated audience and keep internal notes, job-description mapping and Q&A material out unless the user explicitly asks for them.
- When a decision, missing detail, or risk check blocks safe progress mid-task, call ask_user with one clear question and 2-4 short options instead of ending your turn. Execution pauses, the user answers, and you continue the same task with that answer. Do not ask for confirmation you do not need.
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
    # task that only mentions "视频" while publishing, or that references an
    # HTML page, is a coding task. Otherwise it is routed to the read-only
    # video/plan agents and can never write the requested file.
    if any(hint in lowered for hint in WEB_ARTIFACT_INTENT):
        return "dev"
    if _PLAN_INTENT_RE.search(text or "") and not _PATH_RE.search(text or ""):
        return "plan"
    if any(hint in lowered for hint in CODE_WORK_INTENT):
        return "dev"
    if any(hint in lowered for hint in VIDEO_INTENT):
        return "video"
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


def is_casual_chat(text: str) -> bool:
    """Detect greetings, social chat and general questions that need no workspace work."""
    value = (text or "").strip()
    if not value:
        return False
    if is_smalltalk(value):
        return True
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
    return not any(hint in value for hint in READ_ONLY_HINTS)


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
        provider, model = resolve(session.get("provider"), session.get("model"))
        level = estimate_complexity(text, any(s.get("s") in ("pending", "doing") for s in _plan_steps(session)))
        lite = self._should_lite(session, level, text)
        task_type = detect_task_type(text)
        qa = is_question(text)
        audit = needs_spec_audit(text, level, bool(session.get("workspace")), requested, qa)
        write_required = level != "simple" and needs_write(text, qa, requested, bool(session.get("workspace")))
        thinking = self._thinking(session, provider, lite, level, qa or casual)
        run = await self.storage.create_run(session_id, provider, model, text)
        run_id = run["id"]

        matched, skill_how = ([], "no skills") if (qa or casual) and not session.get("skills") else self.skills.match(
            requested, text, self._selected_skills(session)
        )
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
            },
            run_id,
        )

        try:
            await self._drive(
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
            )
        except asyncio.CancelledError:
            await self.storage.update_session(session_id, status="error", error="用户取消")
            await self.emit(session_id, "session.status", {"status": "error", "error": "用户取消"}, run_id)
            await self.storage.finish_run(run_id, "cancelled", error="用户取消")
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            await self.storage.update_session(session_id, status="error", error=message[:500])
            await self.emit(session_id, "error", {"message": message}, run_id)
            await self.emit(session_id, "session.status", {"status": "error", "error": message[:500]}, run_id)
            await self.storage.finish_run(run_id, "error", error=message)
        finally:
            await self.events.flush()

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
        if kind == "video":
            return self.agents.get("video")
        if kind == "robot":
            return self.agents.get("robot")
        if kind == "general":
            return self.agents.get("general")
        return self.agents.get(DEFAULT_AGENT)

    def _should_lite(self, session: dict[str, Any], level: str, text: str) -> bool:
        if not LITE_MODE:
            return False
        if level in ("simple", "normal"):
            return True
        if any(step.get("s") in ("pending", "doing") for step in _plan_steps(session)):
            return False
        cleaned = _NEGATION_RE.sub("", text or "")
        if any(hint in cleaned for hint in LITE_MULTIPHASE_HINTS):
            return False
        paths = {match.group(0).lower() for match in _PATH_RE.finditer(text or "")}
        return len(paths) <= LITE_SINGLE_FILE_MAX_PATHS

    def _thinking(self, session: dict[str, Any], provider: str, lite: bool, level: str, qa: bool) -> str:
        selected = (session.get("thinking") or "").strip()
        if selected in ("off", "low", "high"):
            return selected
        if provider == "mock":
            return "off"
        if qa or lite:
            return "off" if qa else "low"
        return "high" if level == "complex" else "low"

    def _tools_for(self, agent, kind: str, lite: bool, workspace: bool) -> list[str]:
        if not agent.tools:
            return []
        if not workspace and getattr(agent, "kind", "") not in ("plan", "video", "robot"):
            chat_safe = {"system_info", "calculator", "now", "echo"}
            return [name for name in agent.tools if name in chat_safe and self.tools.get(name)]
        names = [name for name in agent.tools if self.tools.get(name)]
        if not names:
            return []
        # Plan/video agents already expose a tiny purpose-built toolset; trimming
        # it would remove their primary deliverable tool (make_plan/make_storyboard).
        if lite and TOOL_SCHEMA_TRIM and getattr(agent, "kind", "") not in ("plan", "video"):
            allowed = set(LITE_TOOL_SET) | {"plan_task", "update_plan"}
            names = [name for name in names if name in allowed]
        if not SUBAGENT_ENABLED:
            names = [name for name in names if name != "task"]
        return names

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
    ) -> None:
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
        if REPO_MAP_ENABLED and workspace and kind in ("dev", "coding") and not lite and not qa:
            try:
                repo_map_text = await asyncio.to_thread(repoindex.repo_map, workspace, None, user_text)
            except Exception:
                repo_map_text = ""
            try:
                context_pack_text = await asyncio.to_thread(
                    repoindex.context_pack, workspace, user_text, 30000, 18
                )
            except Exception:
                context_pack_text = ""
        reference_text = ""
        reference_paths: list[str] = []
        if workspace and not casual and not qa:
            try:
                reference_paths = reference.resolve_reference_paths(workspace, user_text)
                blocks = [reference.digest(rel) for rel in reference_paths[:2]]
                reference_text = "\n\n".join(blocks)[:16000]
            except Exception:
                reference_paths = []
                reference_text = ""
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
        )
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
        tool_names = self._tools_for(agent, kind, lite, bool(workspace))
        schemas = self.tools.openai_tools(tool_names)

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
        }
        max_total = AGENT_MAX_TOTAL_STEPS
        session = await self.storage.get_session(session_id) or session

        while True:
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
                return
            state["step"] += 1
            state["total_steps"] += 1

            cursor, injected = await self._inject_pending(session_id, messages, cursor)
            if injected:
                await self.emit(session_id, "instruction.merged", {"count": injected}, run_id)

            session = await self.storage.get_session(session_id) or session
            if MAX_SESSION_COST > 0 and float(session.get("cost_est") or 0) >= MAX_SESSION_COST:
                await self.emit(
                    session_id,
                    "error",
                    {"message": f"cost budget reached ({MAX_SESSION_COST})"},
                    run_id,
                )
                await self.storage.update_session(session_id, status="error", error="cost budget reached")
                await self.storage.finish_run(
                    run_id, "error", error="cost budget reached", step_count=state["total_steps"]
                )
                return
            compaction = await self.context.midturn_compact(session, messages, state["total_steps"])
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
            async for event in self.gateway.stream(provider, model, messages, schemas, thinking):
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
                cost = self._cost(actual_provider, usage, actual_model)
                bill = await self.storage.record_usage(session_id, assistant_row["id"], actual_provider, actual_model, usage, cost)
                await self.emit(session_id, "usage", {**bill, "provider": actual_provider, "model": actual_model}, run_id)
            if fallbacks:
                await self.emit(session_id, "model.fallback", {"fallbacks": fallbacks}, run_id)

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
                    await self.emit(session_id, "instruction.merged", {"count": injected}, run_id)
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

            results = await self._execute_calls(session, parsed_calls, run_id, state)
            for call in parsed_calls:
                result = results.get(call.call_id)
                if result is None:
                    continue
                content_for_context = self._tool_context_text(result)
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
                if result.ok and call.name in ("write_file", "edit_file", "apply_patch", "multi_edit"):
                    path = str(call.arguments.get("path") or "")
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
                    command = str(call.arguments.get("command") or "").lower()
                    if any(hint in command for hint in VERIFY_CMD_HINTS) and "[exit 0]" in str(result.result):
                        state["last_verify_step"] = state["total_steps"]
                await self._register_generated_artifact(session_id, call, result)

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
        spec = self.tools.get(call.name)
        if not spec:
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
        result = await self.tools.execute(call, ctx)
        if result.ok and call.name in IDEMPOTENT_TOOLS:
            await durability.record_effect(self.storage, session["id"], state["total_steps"], call.name, call.arguments, str(result.result), workspace)
        return result

    def _tool_context_text(self, result: ToolResult) -> str:
        payload = {
            "ok": result.ok,
            "result": result.result,
            "error": result.error,
            "artifact_id": result.artifact_id,
        }
        text = json.dumps(payload, ensure_ascii=False, default=str)
        if len(text) > TOOL_RESULT_CONTEXT_CHARS:
            text = text[:TOOL_RESULT_CONTEXT_CHARS] + TOOL_RESULT_CONTEXT_MARK
        return text

    async def _inject_pending(self, session_id: str, messages: list[dict[str, Any]], cursor: int) -> tuple[int, int]:
        rows = await self.storage.list_messages(session_id, after_rowid=cursor)
        new_users = [row for row in rows if row["role"] == "user"]
        if not new_users:
            return cursor, 0
        for row in new_users:
            messages.append({"role": "user", "content": row.get("content") or ""})
        return int(new_users[-1]["seq"]), len(new_users)

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
                    async for event in self.gateway.stream(provider, model, messages, None, audit_thinking):
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
                                self._cost(provider, usage, model),
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
        provider, model = resolve(session.get("provider"), session.get("model"))

        async def run() -> str:
            nonlocal steps, calls, final
            while steps < min(SUBAGENT_MAX_STEPS, AGENT_MAX_STEPS):
                steps += 1
                message = None
                usage = {}
                async for event in self.gateway.stream(provider, model, messages, schemas, "low"):
                    if event.get("type") == "message":
                        message = event.get("message")
                        usage = event.get("usage") or {}
                if not message:
                    break
                if usage:
                    try:
                        await self.storage.record_usage(
                            session["id"], f"sub-{uuid.uuid4().hex[:10]}", provider, model, usage, self._cost(provider, usage, model)
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
                    call = ToolCall(call_id=raw.get("id") or uuid.uuid4().hex[:12], name=function.get("name") or "", arguments=call_args)
                    ctx = ToolContext(runtime=self, session=session, workspace=session.get("workspace") or "", call=call, emit=self.emit)
                    result = await self.tools.execute(call, ctx)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "content": str(result.result if result.ok else result.error)[:6000],
                        }
                    )
            return final

        try:
            final = await asyncio.wait_for(run(), timeout=SUBAGENT_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            return f"[subagent {description}] timed out after {int(SUBAGENT_TIMEOUT_SEC)}s ({steps} steps / {calls} tools)"
        except Exception as exc:
            return f"[subagent {description}] failed: {type(exc).__name__}: {exc}"
        body = (final or "").strip() or f"(subagent ran {steps} steps / {calls} tools but returned no text)"
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
        if call.name not in ("make_plan", "make_storyboard") or not result.ok:
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
    def _cost(provider: str, usage: dict[str, Any], model: str | None = None) -> float:
        price = price_for(provider, model)
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cached = min(int(usage.get("cached_tokens") or 0), prompt)
        hit_price = price.get("cache_hit", price["prompt"])
        return round(
            ((prompt - cached) * price["prompt"] + cached * hit_price + completion * price["completion"]) / 1_000_000, 6
        )

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
                "Exception: for questions about this machine's OS, CPU, memory, disk or uptime, use system_info or the live host information below.\n"
            )
        if kind == "plan":
            parts.append(
                "\n# Plan document mode\nWrite a rigorous proposal. Use make_plan to produce a standalone HTML document with "
                "executive summary, KPIs, sections, tables, risks, milestones, and budget. Keep the document self-contained.\n"
            )
        if kind == "video":
            parts.append(
                "\n# Video storyboard mode\nProduce a shot-by-shot storyboard with duration, visuals, narration, and on-screen text. "
                "Use make_storyboard to generate the deliverable. Do not claim to render actual video.\n"
            )
        if kind in ("dev", "coding") and workspace and not qa:
            parts.append(
                "\n# Coding protocol\n"
                "1. Inspect the project (project_scan / list_dir / repo map) before editing.\n"
                "2. Locate symbols precisely with search_symbol and read_range.\n"
                "3. Apply minimal patches; never rewrite a file unless it is new.\n"
                "4. After code edits, run the relevant verification command once.\n"
                "5. Finish with a short summary of files changed, verification result, and any remaining risk.\n"
            )
            if lite:
                parts.append("This is a lightweight task: keep the loop short, avoid unnecessary planning, and verify once.\n")
            if TWO_PHASE_PLAN and not lite:
                parts.append(
                    "\n# Two-phase discipline\nFor complex tasks, first locate and plan (search_symbol/read_range/plan_task), "
                    "then execute patches, then verify. Do not interleave broad exploration with edits.\n"
                )
            if task_type == "debug":
                parts.append(
                    "\n# Debug protocol\nReproduce the failure, read the failing assertion, fix the smallest root cause, "
                    "and rerun the same test. If the same failure fingerprint repeats, change strategy instead of retrying.\n"
                )
        if matched:
            parts.append(SkillLibrary.render(matched, skill_how))
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


def platform_name() -> str:
    import platform

    return platform.platform()


def level_is_complex(task_type: str, content: str) -> bool:
    return task_type in ("debug", "dev") or bool(content)
