from __future__ import annotations

from core.contracts import AgentSpec
from tools.plan import tool_specs as plan_specs


def register(ctx) -> None:
    specs = {spec.name: spec for spec in plan_specs(ctx.name)}
    from tools.plan import make_plan, plan_task, update_plan

    for name, handler in (
        ("plan_task", plan_task),
        ("update_plan", update_plan),
        ("make_plan", make_plan),
    ):
        spec = specs[name]
        ctx.register_tool(spec, handler)
    ctx.add_skill_dir("skills")
    ctx.register_agent(
        AgentSpec(
            name="planner",
            title="HaoYuan Plan Author",
            description="Business planning, proposals and analysis documents.",
            instructions=(
                "Act as a senior strategy consultant. Structure the document rigorously: executive summary, goals, KPIs, "
                "sections, tables, milestones, budget, risks, and next actions. If a prior project/version is named, use "
                "baseline_audit to extract measured facts and doc_consistency before finishing; cite sources and label "
                "planned numbers. If the user supplies a reference HTML or an explicit output path, write the document "
                "directly with write_file/apply_patch in the reference style; otherwise deliver through make_plan as a "
                "self-contained HTML artifact."
            ),
            tools=[
                "plan_task", "update_plan", "make_plan", "read_file", "read_range", "grep", "glob",
                "list_dir", "project_scan", "write_file", "apply_patch", "edit_file", "run_shell",
                "web_audit", "web_screenshot", "describe_image", "reference_digest",
                "reference_compare", "baseline_audit", "doc_consistency", "web_fetch", "task", "ask_user",
            ],
            auto_skills=True,
            kind="plan",
        )
    )
