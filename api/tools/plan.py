from __future__ import annotations

import html
import json
import os
from datetime import datetime
from typing import Any

from configs.configs import ARTIFACTS_DIR
from core.contracts import ToolContext, ToolSpec


def _emit(ctx: ToolContext, event: str, payload: dict[str, Any]) -> None:
    try:
        events = ctx.runtime.events
        import asyncio

        asyncio.get_running_loop().create_task(events.emit(ctx.session_id, event, payload))
    except RuntimeError:
        pass


def _current_plan(ctx: ToolContext) -> dict[str, Any]:
    try:
        return json.loads(ctx.session.get("plan") or "{}")
    except (ValueError, TypeError):
        return {}


async def _save_plan(ctx: ToolContext, plan: dict[str, Any]) -> None:
    encoded = json.dumps(plan, ensure_ascii=False)
    ctx.session["plan"] = encoded
    await ctx.runtime.storage.update_session(ctx.session_id, plan=encoded)
    _emit(ctx, "plan.updated", plan)


async def plan_task(ctx: ToolContext, args: dict[str, Any]) -> str:
    raw_steps = args.get("steps") or []
    steps = []
    for index, item in enumerate(raw_steps, 1):
        if isinstance(item, str):
            steps.append({"t": item, "s": "pending", "note": ""})
        elif isinstance(item, dict):
            steps.append(
                {
                    "t": str(item.get("t") or item.get("text") or item.get("title") or f"Step {index}"),
                    "s": str(item.get("s") or item.get("status") or "pending"),
                    "note": str(item.get("note") or ""),
                }
            )
    plan = {"title": str(args.get("title") or "Execution plan"), "steps": steps, "updated_at": datetime.now().isoformat(timespec="seconds")}
    await _save_plan(ctx, plan)
    lines = [f"Plan set: {plan['title']} ({len(steps)} steps)"]
    for index, step in enumerate(steps, 1):
        lines.append(f"{index}. [{step['s']}] {step['t']}")
    return "\n".join(lines)


async def update_plan(ctx: ToolContext, args: dict[str, Any]) -> str:
    plan = _current_plan(ctx)
    steps = plan.get("steps") or []
    index = int(args.get("index") or args.get("step") or 0)
    status = str(args.get("status") or args.get("s") or "done")
    note = str(args.get("note") or "")
    if index < 1 or index > len(steps):
        return f"Invalid step index {index}; plan has {len(steps)} steps."
    steps[index - 1]["s"] = status
    if note:
        steps[index - 1]["note"] = note
    plan["steps"] = steps
    plan["updated_at"] = datetime.now().isoformat(timespec="seconds")
    await _save_plan(ctx, plan)
    done = sum(1 for step in steps if step.get("s") == "done")
    return f"Step {index} -> {status}. Progress {done}/{len(steps)}."


def _doc_html(title: str, subtitle: str, body: str) -> str:
    escaped_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escaped_title}</title>
<style>
:root{{--bg:#f7f8fb;--surface:#fff;--surface-2:#f0f2f7;--ink:#141821;--ink-2:#3d4453;--muted:#737b8c;--line:#e3e7ef;--brand:#4f46e5}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:var(--ink);background:var(--bg);line-height:1.7}}
.wrap{{max-width:1040px;margin:0 auto;padding:34px 26px 80px}}.topnav{{display:flex;gap:18px;padding:14px 0;border-bottom:1px solid var(--line);font-size:14px}}.topnav b{{font-weight:750}}
.hero{{margin:28px 0 36px;padding:48px 42px;border:1px solid var(--line);border-radius:26px;background:linear-gradient(135deg,#fff,#f4f5ff 60%,#eef8ff);box-shadow:0 18px 50px rgba(20,24,33,.07)}}
.hero h1{{margin:0 0 10px;font-size:clamp(32px,4vw,50px);letter-spacing:-.035em;line-height:1.12}}.hero p{{margin:0;color:var(--ink-2);font-size:18px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0}}.kpi{{padding:20px;border:1px solid var(--line);border-radius:18px;background:var(--surface)}}.kpi b{{display:block;font-size:30px;color:var(--brand);letter-spacing:-.03em}}.kpi span{{color:var(--muted);font-size:13px}}
.sec{{margin:44px 0}}.sec h2{{font-size:26px;margin:0 0 6px;letter-spacing:-.02em}}.sec p{{color:var(--ink-2)}}
.box{{padding:20px 22px;border:1px solid var(--line);border-radius:18px;background:var(--surface)}}.tw{{width:100%;border-collapse:collapse;margin:14px 0}}.tw th,.tw td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:14px}}.tw th{{background:var(--surface-2)}}
.callout{{padding:16px 18px;border-radius:14px;background:#eef2ff;border:1px solid #dbe2ff}}.timeline{{border-left:2px solid var(--line);padding-left:22px}}.tl{{position:relative;margin-bottom:16px}}.tl::before{{content:"";position:absolute;left:-29px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--brand)}}
@media(max-width:760px){{.hero{{padding:30px 22px}}.wrap{{padding:18px 16px 60px}}}}
</style>
</head>
<body>
<div class="wrap">
<nav class="topnav"><b>{escaped_title}</b><span>HaoYuan · Generated document</span></nav>
<header class="hero"><h1>{escaped_title}</h1><p>{html.escape(subtitle)}</p></header>
{body}
</div>
</body>
</html>"""


def _artifact(ctx: ToolContext, filename: str, content: str, kind: str) -> dict[str, Any]:
    directory = ARTIFACTS_DIR / ctx.session_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "kind": kind, "size": path.stat().st_size}


async def _register(ctx: ToolContext, artifact: dict[str, Any]) -> None:
    record = await ctx.runtime.storage.create_artifact(
        ctx.session_id, artifact["path"], artifact["kind"], os.path.basename(artifact["path"]), artifact["size"]
    )
    _emit(ctx, "artifact.created", record)


async def make_plan(ctx: ToolContext, args: dict[str, Any]) -> str:
    title = str(args.get("title") or "方案计划书")
    summary = str(args.get("summary") or args.get("subtitle") or "")
    kpis = args.get("kpis") or []
    sections = args.get("sections") or []
    kpi_html = ""
    if kpis:
        cards = []
        for item in kpis[:6]:
            if isinstance(item, dict):
                value = html.escape(str(item.get("value") or item.get("v") or ""))
                label = html.escape(str(item.get("label") or item.get("l") or item.get("name") or ""))
            else:
                value, label = html.escape(str(item)), ""
            cards.append(f'<div class="kpi"><b>{value}</b><span>{label}</span></div>')
        kpi_html = '<div class="kpis">' + "".join(cards) + "</div>"
    section_html = []
    for index, item in enumerate(sections, 1):
        if isinstance(item, dict):
            heading = html.escape(str(item.get("title") or item.get("h") or f"章节 {index}"))
            content = str(item.get("html") or item.get("body") or item.get("content") or "")
        else:
            heading = f"章节 {index}"
            content = str(item)
        section_html.append(f'<section class="sec" id="sec-{index}"><h2>{heading}</h2>{content}</section>')
    body = kpi_html + "".join(section_html)
    if not section_html:
        body += '<section class="sec"><div class="box">内容由 HaoYuan 生成。</div></section>'
    content = _doc_html(title, summary, body)
    artifact = _artifact(ctx, f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html", content, "plan")
    await _register(ctx, artifact)
    return json.dumps(
        {"ok": True, "title": title, "path": artifact["path"], "artifact_kind": "plan"},
        ensure_ascii=False,
    )


async def make_storyboard(ctx: ToolContext, args: dict[str, Any]) -> str:
    title = str(args.get("title") or "视频分镜脚本")
    theme = str(args.get("theme") or args.get("summary") or "")
    shots = args.get("shots") or []
    rows = []
    for index, shot in enumerate(shots, 1):
        if isinstance(shot, dict):
            scene = html.escape(str(shot.get("scene") or shot.get("shot") or f"镜头 {index}"))
            duration = html.escape(str(shot.get("duration") or shot.get("d") or ""))
            narration = html.escape(str(shot.get("narration") or shot.get("voiceover") or ""))
            visual = html.escape(str(shot.get("visual") or shot.get("desc") or ""))
        else:
            scene, duration, narration, visual = f"镜头 {index}", "", str(shot), ""
        rows.append(
            f"<tr><td>{scene}</td><td>{duration}</td><td>{visual}</td><td>{narration}</td></tr>"
        )
    body = (
        '<section class="sec"><h2>分镜表</h2>'
        '<table class="tw"><thead><tr><th>镜头</th><th>时长</th><th>画面</th><th>口播 / 字幕</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )
    content = _doc_html(title, theme, body)
    artifact = _artifact(ctx, f"storyboard-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html", content, "storyboard")
    await _register(ctx, artifact)
    return json.dumps(
        {"ok": True, "title": title, "path": artifact["path"], "artifact_kind": "storyboard"},
        ensure_ascii=False,
    )


async def reset_if_done(ctx: ToolContext) -> None:
    plan = _current_plan(ctx)
    steps = plan.get("steps") or []
    if steps and all(step.get("s") in ("done", "failed", "skipped") for step in steps):
        await _save_plan(ctx, {"title": plan.get("title", ""), "steps": [], "updated_at": datetime.now().isoformat(timespec="seconds")})


def tool_specs(source: str = "plans") -> list[ToolSpec]:
    return [
        ToolSpec(
            name="plan_task",
            description="Create or replace the visible execution plan for this task. Use for multi-step work.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "object", "properties": {"t": {"type": "string"}, "s": {"type": "string"}}},
                            ]
                        },
                    },
                },
                "required": ["steps"],
            },
            source=source,
        ),
        ToolSpec(
            name="update_plan",
            description="Update one plan step status (pending/doing/done/failed) and optional note.",
            input_schema={
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "status": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["index", "status"],
            },
            source=source,
        ),
        ToolSpec(
            name="make_plan",
            description="Generate a polished standalone HTML proposal/plan document and register it as an artifact.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "kpis": {"type": "array", "items": {"type": "object"}},
                    "sections": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["title", "sections"],
            },
            risk="medium",
            side_effect="write",
            confirm=True,
            readonly=False,
            source=source,
        ),
        ToolSpec(
            name="make_storyboard",
            description="Generate a video storyboard HTML document (shot, duration, visual, narration).",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "theme": {"type": "string"},
                    "shots": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["title", "shots"],
            },
            risk="medium",
            side_effect="write",
            confirm=True,
            readonly=False,
            source=source,
        ),
    ]


def register_plan_tools(registry, source: str = "plans") -> None:
    handlers = {
        "plan_task": plan_task,
        "update_plan": update_plan,
        "make_plan": make_plan,
        "make_storyboard": make_storyboard,
    }
    for spec in tool_specs(source):
        registry.register(spec, handlers[spec.name])
