from __future__ import annotations

from core.contracts import AgentSpec
from tools.dev import register_dev_tools, tool_specs


def register(ctx) -> None:
    register_dev_tools(ctx.tools, source=ctx.name)
    ctx.add_skill_dir("skills")
    tool_names = [spec.name for spec in tool_specs()] + ["plan_task", "update_plan", "system_info"]
    ctx.register_agent(
        AgentSpec(
            name="coding",
            title="HaoYuan Coding Agent",
            description="Autonomous repository-aware software engineer.",
            instructions=(
                "Own the engineering outcome. Inspect first, make minimal precise changes, verify with the project's own "
                "commands, and report exactly what changed and what remains unverified. Treat the workspace as production "
                "code: no speculative rewrites, no unrequested formatting churn. When a decision or missing detail blocks "
                "progress, call ask_user mid-task instead of ending the turn and waiting for a new message."
            ),
            tools=tool_names,
            auto_skills=True,
            kind="dev",
        )
    )
    ctx.register_agent(
        AgentSpec(
            name="general",
            title="HaoYuan General Assistant",
            description="Chat-only assistant when no workspace is bound.",
            instructions=(
                "Answer clearly and concisely. Use system_info for questions about this machine's OS, CPU, memory, "
                "disk or uptime. If no workspace is bound and the user needs file or command access, explain that a "
                "workspace must be bound first."
            ),
            tools=["system_info", "calculator", "now", "echo"],
            auto_skills=True,
            kind="general",
        )
    )
