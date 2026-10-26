from __future__ import annotations

from core.contracts import AgentSpec
from harness.embodied import register_embodied_tools


def register(ctx) -> None:
    register_embodied_tools(ctx.tools, source=ctx.name)
    ctx.register_agent(
        AgentSpec(
            name="robot",
            title="HaoYuan Embodied Agent",
            description="Robot planning and control harness (demo bridge).",
            instructions=(
                "You are the planning brain of an embodied robot. Scan before moving, keep speeds conservative, and use "
                "emergency stop when uncertain. All irreversible motion requires user approval."
            ),
            tools=[
                "robot_status", "robot_scan", "robot_stop", "robot_estop", "robot_reset_estop",
                "robot_move", "robot_turn", "robot_goto", "echo", "now", "calculator",
            ],
            auto_skills=True,
            kind="robot",
        )
    )
