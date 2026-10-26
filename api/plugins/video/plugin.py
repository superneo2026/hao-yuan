from __future__ import annotations

from core.contracts import AgentSpec
from tools.plan import make_storyboard, tool_specs


def register(ctx) -> None:
    spec = next(s for s in tool_specs(ctx.name) if s.name == "make_storyboard")
    ctx.register_tool(spec, make_storyboard)
    ctx.add_skill_dir("skills")
    ctx.register_agent(
        AgentSpec(
            name="video",
            title="HaoYuan Video Director",
            description="Video concept and storyboard author.",
            instructions=(
                "Design a compelling short video. Deliver a shot-by-shot storyboard with timecodes, visuals, narration and "
                "on-screen text through make_storyboard. Be explicit that this is a production plan, not a rendered video."
            ),
            tools=["plan_task", "update_plan", "make_storyboard", "read_file", "list_dir"],
            auto_skills=True,
            kind="video",
        )
    )
