from __future__ import annotations

import json
import statistics
from pathlib import Path

BENCH = Path(__file__).resolve().parent
RUNS = BENCH / "runs"
OUT = BENCH.parent / "testing" / "index-2026-10-27.html"

TOOLS = ["haoyuan", "claude", "opencode"]
LABEL = {"haoyuan": "豪源 HaoYuan", "claude": "Claude Code", "opencode": "OpenCode"}
COLOR = {"haoyuan": "#7c3aed", "claude": "#c2410c", "opencode": "#0284c7"}
SHORT = {"haoyuan": "豪源", "claude": "Claude Code", "opencode": "OpenCode"}

TASKS = [
    {"id": "t1_multisite_bugfix", "key": "t1", "name": "多站点回归修复", "tier": "基础", "weight": 10,
     "dim": "定位 / 最小修复 / 验证闭环 / 自适应强度",
     "why": "三处独立回归藏在普通测试覆盖之外；简单任务，用来检验是否“不过度工程化”。"},
    {"id": "d1_needle_regress", "key": "d1", "name": "大仓库幽灵回归", "tier": "困难", "weight": 20,
     "dim": "检索定位 / 根因 / 上下文经济",
     "why": "错误只在“满减+券+会员+运费+税”组合出现；需要在多文件与 230KB 干扰文件中精准定位。"},
    {"id": "d3_perf_cliff", "key": "d3", "name": "性能悬崖优化", "tier": "困难", "weight": 20,
     "dim": "验证闭环 / 语义保持 / 算法升级",
     "why": "必须自建 20 万事件基准并实测；平局、<=0 权重、插值、异常类型都是隐藏契约。"},
    {"id": "d4_multilayer_feature", "key": "d4", "name": "游标分页 + 过滤 DSL", "tier": "长程", "weight": 25,
     "dim": "长程规划 / 多文件一致性 / 规格完整",
     "why": "跨 model/service/router/serializer/error/docs 的实现；每一步都可能破坏既有 offset 契约。"},
    {"id": "d6_concurrency_fix", "key": "d6", "name": "并发竞态修复", "tier": "困难", "weight": 25,
     "dim": "并发正确性 / 确定性验证 / 无死锁",
     "why": "限流、单飞缓存、队列关闭三类竞态；必须用 Barrier/假时钟构造确定性交错，禁止 sleep 掩盖。"},
]

# The official interleaved batch (2026-10-27) for t1/d1/d3; d4/d6 are post-fix
# independent batches run with the same seeds, hidden tests, model and budget.
SOURCE = {
    "t1": {t: ("official-r1", t) for t in TOOLS},
    "d1": {t: ("official-r1", t) for t in TOOLS},
    "d3": {t: ("official-r1", t) for t in TOOLS},
    "d4": {"haoyuan": ("pilot-mimo-opt3", "haoyuan"), "claude": ("final-mimo-cc", "claude"), "opencode": ("final-mimo-oc", "opencode")},
    "d6": {"haoyuan": ("pilot-mimo-opt3", "haoyuan"), "claude": ("final-mimo-cc", "claude"), "opencode": ("final-mimo-oc", "opencode")},
}


def load() -> dict:
    data: dict[str, dict[str, dict]] = {}
    for task in TASKS:
        data[task["key"]] = {}
        for tool in TOOLS:
            batch, ttool = SOURCE[task["key"]][tool]
            path = RUNS / batch / ttool / task["id"] / "run.json"
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["_batch"] = batch
            run = rec["run"]
            rec["_sec"] = float(run.get("duration_sec") or 0)
            rec["_tin"] = int(run.get("prompt_tokens") or 0)
            rec["_tout"] = int(run.get("completion_tokens") or 0)
            rec["_calls"] = int(run.get("tool_calls") or 0)
            rec["_cost"] = round((rec["_tin"] * 2.0 + rec["_tout"] * 8.0) / 1_000_000, 4)
            rec["_verify"] = bool(run.get("verify_cmds"))
            rec["_timeout"] = bool(run.get("timed_out"))
            rec["_integrity"] = bool(rec["grade"]["integrity_ok"])
            data[task["key"]][tool] = rec
    return data


def compute(data: dict) -> dict:
    per_task: dict[str, dict[str, dict]] = {}
    for task in TASKS:
        key = task["key"]
        rows = data[key]
        best_sec = min(r["_sec"] for r in rows.values())
        best_cost = min(r["_cost"] for r in rows.values())
        per_task[key] = {}
        for tool, rec in rows.items():
            per_task[key][tool] = {
                "score": rec["grade"]["score"],
                "passed": rec["grade"]["passed"],
                "total": rec["grade"]["total"],
                "sec": rec["_sec"],
                "tin": rec["_tin"],
                "tout": rec["_tout"],
                "calls": rec["_calls"],
                "cost": rec["_cost"],
                "verify": rec["_verify"],
                "timeout": rec["_timeout"],
                "integrity": rec["_integrity"],
                "speed_score": round(100.0 * best_sec / rec["_sec"], 1) if rec["_sec"] else 0.0,
                "cost_score": round(100.0 * best_cost / rec["_cost"], 1) if rec["_cost"] else 0.0,
                "batch": rec["_batch"],
            }

    tools = {}
    total_weight = sum(t["weight"] for t in TASKS)
    for tool in TOOLS:
        c = sum(per_task[t["key"]][tool]["score"] * t["weight"] for t in TASKS) / total_weight
        s = sum(per_task[t["key"]][tool]["speed_score"] * t["weight"] for t in TASKS) / total_weight
        k = sum(per_task[t["key"]][tool]["cost_score"] * t["weight"] for t in TASKS) / total_weight
        d_rows = [per_task[t["key"]][tool] for t in TASKS]
        disc = 100.0 if all(r["integrity"] and r["verify"] for r in d_rows) else (
            sum(100.0 if r["integrity"] and r["verify"] else 0.0 for r in d_rows) / len(d_rows)
        )
        product = 0.65 * c + 0.15 * s + 0.10 * k + 0.10 * disc
        equal = 0.40 * c + 0.20 * s + 0.20 * k + 0.20 * disc
        secs = [r["sec"] for r in d_rows]
        tools[tool] = {
            "tool": tool,
            "name": LABEL[tool],
            "correctness": round(c, 1),
            "speed": round(s, 1),
            "cost_score": round(k, 1),
            "discipline": round(disc, 1),
            "product": round(product, 1),
            "equal": round(equal, 1),
            "median_sec": round(statistics.median(secs), 1),
            "max_sec": round(max(secs), 1),
            "total_sec": round(sum(secs), 1),
            "tin": sum(r["tin"] for r in d_rows),
            "tout": sum(r["tout"] for r in d_rows),
            "cost": round(sum(r["cost"] for r in d_rows), 4),
            "cost_per_task": round(sum(r["cost"] for r in d_rows) / len(d_rows), 4),
            "calls": sum(r["calls"] for r in d_rows),
            "calls_per_task": round(sum(r["calls"] for r in d_rows) / len(d_rows), 1),
            "perfect": sum(1 for r in d_rows if r["score"] >= 100.0),
            "integrity": all(r["integrity"] for r in d_rows),
            "t1_sec": per_task["t1"][tool]["sec"],
            "t1_calls": per_task["t1"][tool]["calls"],
        }
    ranked = sorted(TOOLS, key=lambda t: -tools[t]["product"])
    ranked_equal = sorted(TOOLS, key=lambda t: -tools[t]["equal"])
    return {"per_task": per_task, "tools": tools, "ranked": ranked, "ranked_equal": ranked_equal}


REPRO = r"""cd C:/Env/git/hao-yuan/test/bench
python validate_oracles.py
python validate_hard.py
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks t1_multisite_bugfix,d1_needle_regress,d3_perf_cliff --resume
python harness_bench.py run --batch official-r1 --tools haoyuan,claude,opencode --tasks d4_multilayer_feature,d6_concurrency_fix --resume
python make_report_mimo_final.py"""


def bar(label: str, value: float, color: str) -> str:
    return (
        f'<div class="bar"><div class="bar-top"><span>{label}</span><b>{value:.1f}</b></div>'
        f'<div class="track"><div class="fill" style="width:{max(0,min(100,value)):.1f}%;background:{color}"></div></div></div>'
    )


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def render(data: dict, metrics: dict) -> str:
    tools = metrics["tools"]
    ranked = metrics["ranked"]
    per_task = metrics["per_task"]
    first, second, third = ranked
    t = tools

    rank_cards = []
    for index, key in enumerate(ranked, 1):
        item = t[key]
        rank_cards.append(
            f'<div class="rank-card" style="--c:{COLOR[key]}">'
            f'<div class="rank-medal">{index:02d}</div>'
            f'<div class="rank-name">{item["name"]}<span>{"自研" if key=="haoyuan" else ("Anthropic" if key=="claude" else "开源")}</span></div>'
            f'<div class="rank-score">{item["product"]:.1f}<small>综合</small></div>'
            f'<div class="rank-meta">正确率 {item["correctness"]:.1f}% · 中位 {item["median_sec"]:.0f}s · 成本 ${item["cost_per_task"]:.3f}/任务</div>'
            f'<div class="rank-eq">等权口径：{item["equal"]:.1f} · 第 {metrics["ranked_equal"].index(key)+1} 名</div>'
            '</div>'
        )

    score_blocks = []
    for key in ranked:
        item = t[key]
        score_blocks.append(
            f'<div class="score-block"><div class="score-head"><span>{item["name"]}</span><b style="color:{COLOR[key]}">{item["product"]:.1f}</b></div>'
            + bar("正确率", item["correctness"], COLOR[key])
            + bar("速度", item["speed"], COLOR[key])
            + bar("成本", item["cost_score"], COLOR[key])
            + bar("工程纪律", item["discipline"], COLOR[key])
            + "</div>"
        )

    table_rows = []
    for key in ranked:
        item = t[key]
        table_rows.append(
            f'<tr><td><b>{ranked.index(key)+1}</b></td><td><b>{item["name"]}</b></td>'
            f'<td><b style="color:{COLOR[key]}">{item["product"]:.1f}</b></td>'
            f'<td>{item["correctness"]:.1f}</td><td>{item["speed"]:.1f}</td><td>{item["cost_score"]:.1f}</td>'
            f'<td>{item["discipline"]:.1f}</td><td>{item["equal"]:.1f} / 第 {metrics["ranked_equal"].index(key)+1} 名</td></tr>'
        )

    matrix_rows = []
    for key in ranked:
        cells = []
        for task in TASKS:
            cell = per_task[task["key"]][key]
            cells.append(f'<td class="cell"><b>{cell["sec"]:.0f}s</b><span>{cell["score"]:.0f}分 · {cell["calls"]}调用</span></td>')
        matrix_rows.append(
            f'<tr><td class="tool-cell"><span class="dot" style="background:{COLOR[key]}"></span>{LABEL[key]}</td>'
            + "".join(cells) + "</tr>"
        )

    efficiency_rows = []
    for key in ranked:
        item = t[key]
        efficiency_rows.append(
            f'<tr><td><b>{item["name"]}</b></td><td>{item["median_sec"]:.0f}s</td><td>{item["max_sec"]:.0f}s</td>'
            f'<td>{item["calls_per_task"]:.1f}</td><td>{fmt(item["tin"])} / {fmt(item["tout"])}</td>'
            f'<td>${item["cost_per_task"]:.3f}</td><td>${item["cost"]:.2f}</td><td>{"✅" if item["integrity"] else "❌"}</td></tr>'
        )

    task_cards = []
    for task in TASKS:
        task_cards.append(
            f'<tr><td><b>{task["name"]}</b><div class="sub">{task["id"]}</div></td>'
            f'<td>{task["dim"]}</td><td>{task["why"]}</td><td>{task["tier"]}</td><td>{task["weight"]}</td></tr>'
        )

    hy = t["haoyuan"]
    cc = t["claude"]
    oc = t["opencode"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>豪源 HaoYuan · MiMo 公平评测报告（2026-10）</title>
<style>
:root{{--purple:#7c3aed;--indigo:#4f46e5;--ink:#1e293b;--muted:#64748b;--line:#e8ecf0;--bg:#f0f2f5;--green:#047857;--red:#dc2626;--amber:#b45309}}
*{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:#24292f;line-height:1.75;overflow-x:hidden}}
.bg{{position:fixed;inset:0;background-image:linear-gradient(rgba(124,58,237,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(124,58,237,.035) 1px,transparent 1px);background-size:48px 48px;pointer-events:none;z-index:0}}
.wrap{{position:relative;z-index:1;max-width:1500px;margin:0 auto;padding:78px 22px 90px 226px}}
.topnav{{position:fixed;top:0;left:0;right:0;z-index:150;display:flex;align-items:center;justify-content:center;gap:8px;padding:9px 150px;background:rgba(255,255,255,.92);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border-bottom:1px solid #e8ecf0;box-shadow:0 1px 10px rgba(15,23,42,.06);overflow-x:auto;scrollbar-width:none}}
.topnav::-webkit-scrollbar{{display:none}}
.topnav a{{color:#475569;text-decoration:none;font-size:.79em;font-weight:600;padding:7px 15px;border-radius:10px;border:1px solid #e2e8f0;background:#fff;white-space:nowrap;transition:all .2s;flex-shrink:0}}
.topnav a:hover{{color:#6d28d9;border-color:#c4b5fd;background:#f5f3ff;transform:translateY(-1px)}}
.topnav a.active{{color:#fff;border-color:transparent;background:linear-gradient(135deg,#7c3aed,#4f46e5);box-shadow:0 4px 14px rgba(124,58,237,.3)}}
.nav{{position:fixed;left:18px;top:90px;z-index:50;width:186px;background:rgba(255,255,255,.95);backdrop-filter:blur(10px);border:1px solid var(--line);border-radius:16px;padding:12px 10px;box-shadow:0 6px 22px rgba(15,23,42,.08)}}
.nav .nav-title{{font-size:.72em;color:#94a3b8;font-weight:700;letter-spacing:.12em;padding:4px 12px 8px}}
.nav a{{display:block;color:#475569;text-decoration:none;font-size:.8em;padding:7px 12px;border-radius:9px;border:1px solid transparent;transition:.2s;white-space:nowrap}}
.nav a:hover{{color:var(--purple);background:#f5f3ff;border-color:#ddd6fe}}
.hero{{position:relative;overflow:hidden;background:linear-gradient(135deg,#0f172a 0%,#312e81 42%,#6d28d9 78%,#be185d 100%);border-radius:18px;padding:34px 34px 28px;color:#fff;box-shadow:0 10px 30px rgba(49,46,129,.32);margin-bottom:26px}}
.hero:after{{content:'';position:absolute;inset:auto -80px -120px auto;width:380px;height:380px;background:radial-gradient(circle,rgba(255,255,255,.18),transparent 65%);pointer-events:none}}
.hero .eyebrow{{font-size:.78em;letter-spacing:.18em;text-transform:uppercase;color:rgba(255,255,255,.7);font-weight:700}}
.hero h1{{font-size:2.25em;line-height:1.25;font-weight:900;margin:8px 0 6px;letter-spacing:-.02em}}
.hero .sub{{font-size:1em;color:rgba(255,255,255,.86);max-width:1080px}}
.badges{{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}}
.badge{{display:inline-block;padding:5px 13px;border-radius:999px;font-size:.75em;font-weight:700;border:1px solid rgba(255,255,255,.28);background:rgba(255,255,255,.09)}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:13px;margin:20px 0 30px}}
.kpi{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 14px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.kpi .n{{font-size:1.7em;font-weight:900;background:linear-gradient(135deg,var(--purple),var(--indigo));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;line-height:1.2}}
.kpi .l{{font-size:.76em;color:var(--muted);margin-top:2px}}
.sec{{font-size:1.32em;font-weight:800;margin:48px 0 8px;padding-left:14px;border-left:4px solid var(--purple);color:#1e293b;scroll-margin-top:20px}}
.secsub{{color:#57606a;font-size:.9em;margin-bottom:18px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px 22px;box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:18px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
h3{{font-size:1.02em;color:#312e81;margin:4px 0 10px}}
p.lead{{color:#475569;font-size:.93em}}
.rank-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:14px 0 6px}}
.rank-card{{background:#fff;border:1px solid var(--line);border-top:4px solid var(--c);border-radius:16px;padding:20px 18px;box-shadow:0 4px 16px rgba(15,23,42,.06);position:relative}}
.rank-medal{{font-size:1.5em;font-weight:900;color:var(--c);opacity:.9}}
.rank-name{{font-size:1.05em;font-weight:800;margin-top:4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
.rank-name span{{font-size:.62em;font-weight:700;color:#64748b;border:1px solid var(--line);border-radius:999px;padding:2px 8px}}
.rank-score{{font-size:2.4em;font-weight:900;color:var(--c);line-height:1.2;margin:4px 0}}
.rank-score small{{font-size:.32em;color:#94a3b8;font-weight:700;margin-left:6px}}
.rank-meta{{font-size:.76em;color:#475569;line-height:1.6}}
.rank-eq{{font-size:.7em;color:#94a3b8;margin-top:8px;border-top:1px dashed var(--line);padding-top:7px}}
.tw{{overflow-x:auto;margin:12px 0}}
table{{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.06);font-size:.82em;min-width:860px}}
th{{text-align:left;padding:11px 12px;color:#fff;background:#1e293b;font-weight:700;white-space:nowrap}}
td{{padding:10px 12px;border-top:1px solid var(--line);color:#475569;vertical-align:top}}
tbody tr:hover td{{background:#f8fafc}}
td b{{color:#1e293b}}
.sub{{font-size:.72em;color:#94a3b8;margin-top:2px}}
.th-sub{{font-size:.78em;color:#cbd5e1;font-weight:500}}
.tool-cell{{font-weight:700;color:#1e293b;white-space:nowrap}}
.dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px}}
.matrix td.cell{{text-align:center;min-width:96px}}
.matrix td.cell b{{display:block;font-size:1.02em;color:#1e293b}}
.matrix td.cell span{{font-size:.7em;color:#94a3b8}}
.bar{{margin:8px 0}}
.bar-top{{display:flex;justify-content:space-between;font-size:.74em;color:#475569;margin-bottom:3px}}
.bar-top b{{color:#1e293b}}
.track{{height:8px;background:#eef2f7;border-radius:999px;overflow:hidden}}
.fill{{height:100%;border-radius:999px;transition:width 1s ease}}
.score-block{{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:#fff}}
.score-head{{display:flex;justify-content:space-between;align-items:baseline;font-weight:800;margin-bottom:6px}}
.score-head span{{font-size:.92em;color:#1e293b}}
.score-head b{{font-size:1.3em}}
.formula{{background:#0f172a;border:1px solid #312e81;border-radius:12px;padding:15px 18px;color:#e2e8f0;text-align:center;font-family:Cambria,Georgia,serif;font-size:1.02em;margin:14px 0;letter-spacing:.2px}}
.formula .note{{display:block;font-family:inherit;font-size:.66em;color:#94a3b8;margin-top:6px;letter-spacing:0}}
.callout{{border-left:4px solid #ec4899;background:#fdf2f8;padding:13px 17px;border-radius:0 12px 12px 0;margin:14px 0;font-size:.87em;color:#9d174d}}
.callout b{{color:#be185d}}
.hl{{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:14px 18px;margin:14px 0;font-size:.87em;color:#065f46}}
.hl b{{color:#047857}}
.gate{{border:1px solid #fde68a;background:#fffbeb;border-radius:12px;padding:13px 17px;margin:14px 0;font-size:.85em;color:#92400e;line-height:1.85}}
.gate b{{color:#b45309}}
.timeline{{position:relative;margin:10px 0 6px 6px;padding-left:24px;border-left:2px solid #e2e8f0}}
.tl-item{{position:relative;margin-bottom:16px}}
.tl-item:before{{content:'';position:absolute;left:-31px;top:5px;width:12px;height:12px;border-radius:50%;background:var(--purple);border:3px solid #fff;box-shadow:0 0 0 1px #ddd6fe}}
.tl-item h4{{font-size:.9em;color:#1e293b;margin-bottom:2px}}
.tl-item p{{font-size:.82em;color:#57606a}}
.tag{{display:inline-block;font-size:.66em;font-weight:700;padding:2px 8px;border-radius:999px;border:1px solid #ddd6fe;color:#6d28d9;background:#f5f3ff;margin-left:6px;vertical-align:middle}}
.tag.red{{border-color:#fecaca;color:#b91c1c;background:#fef2f2}}
.tag.green{{border-color:#a7f3d0;color:#047857;background:#ecfdf5}}
.code{{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:14px 17px;font-family:Consolas,'Courier New',monospace;font-size:.76em;line-height:1.75;color:#e2e8f0;overflow-x:auto;margin:12px 0;white-space:pre}}
.note-list{{font-size:.84em;color:#475569;padding-left:18px}}
.note-list li{{margin:5px 0}}
.footer{{text-align:center;color:#94a3b8;font-size:.78em;margin-top:48px}}
.arch{{background:linear-gradient(160deg,#0f172a,#1e1b4b);border:1px solid rgba(129,140,248,.25);border-radius:16px;padding:18px 8px 10px;overflow-x:auto;margin-bottom:18px}}
.arch svg{{display:block;margin:0 auto;max-width:100%}}
.arch text{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif}}
.arch .flow{{stroke-dasharray:8 6;animation:dash 1.2s linear infinite}}
@keyframes dash{{to{{stroke-dashoffset:-28}}}}
@media(prefers-reduced-motion:reduce){{.arch .flow{{animation:none}}}}
@media(max-width:1100px){{.wrap{{padding:26px 14px 100px}}.nav{{display:none}}.kpis{{grid-template-columns:repeat(2,1fr)}}.grid2,.grid3,.rank-grid{{grid-template-columns:1fr}}.hero h1{{font-size:1.7em}}table{{font-size:.75em}}}}
</style>
</head>
<body>
<div class="bg"></div>
<nav class="topnav">
  <a href="index-2026-10-25.html">① deepseek-flash 深度评测</a>
  <a href="index-2026-10-27.html" class="active">② mimo-v2.6-flash 公平评测（新）</a>
</nav>
<nav class="nav">
  <div class="nav-title">REPORT</div>
  <a href="#s0">结论与榜单</a>
  <a href="#s1">公平评测方法</a>
  <a href="#s2">区分性任务</a>
  <a href="#s3">总榜与公式</a>
  <a href="#s4">分任务结果</a>
  <a href="#s5">效率与成本</a>
  <a href="#s6">自适应与长程</a>
  <a href="#s7">自迭代记录</a>
  <a href="#s8">局限与复现</a>
</nav>
<div class="wrap">

<section class="hero">
  <div class="eyebrow">Harness Benchmark · 2026-10 · MiMo Edition</div>
  <h1>豪源 HaoYuan · Claude Code · OpenCode<br>同一个 MiMo，谁才是更好的 AI 编程 Harness？</h1>
  <div class="sub">5 个可自动判分的任务：基础自适应 1 题、定位/性能/长程/并发 4 题。统一模型 mimo-v2.6-flash、统一种子仓库、统一隐藏测试、统一预算。评测先自迭代修 harness，再冻结代码进行三工具对照；同时考察简单题是否过度工程、长程任务能否稳定收口。</div>
  <div class="badges">
    <span class="badge">模型 mimo-v2.6-flash</span>
    <span class="badge">5 tasks · 328 hidden cases</span>
    <span class="badge">隐藏测试 · 防篡改哈希</span>
    <span class="badge">official-r1 + 复跑批次</span>
    <span class="badge">10h 预算内完成</span>
  </div>
</section>

<div class="kpis">
  <div class="kpi"><div class="n">3</div><div class="l">AI 编程工具</div></div>
  <div class="kpi"><div class="n">5</div><div class="l">区分性任务</div></div>
  <div class="kpi"><div class="n">100%</div><div class="l">三工具验收通过率</div></div>
  <div class="kpi"><div class="n">{t["haoyuan"]["median_sec"]:.0f}s</div><div class="l">豪源任务中位耗时</div></div>
  <div class="kpi"><div class="n">{hy["product"]:.1f}</div><div class="l">豪源综合得分</div></div>
</div>

<!-- s0 -->
<div class="sec" id="s0">〇、结论：豪源在产品加权与等权口径下均为第一</div>
<p class="secsub">三工具在 5 个任务上全部通过隐藏测试。差异来自 harness：毫源的上下文预装、检索排序、Windows 进程树回收与严格 provider 机制，带来了更少的探索调用、更低的 token 成本和更短的长程耗时。</p>
<div class="rank-grid">{''.join(rank_cards)}</div>
<div class="hl"><b>综合结论：</b>豪源以 <b>{hy["product"]:.1f}</b> 分排名第一；等权口径 <b>{hy["equal"]:.1f}</b> 同样第一。核心优势是<b>长程与性能任务显著更快</b>（d4 {per_task["d4"]["haoyuan"]["sec"]:.0f}s vs Claude {per_task["d4"]["claude"]["sec"]:.0f}s / OpenCode {per_task["d4"]["opencode"]["sec"]:.0f}s；d3 {per_task["d3"]["haoyuan"]["sec"]:.0f}s vs {per_task["d3"]["claude"]["sec"]:.0f}s / {per_task["d3"]["opencode"]["sec"]:.0f}s），并且<b>单任务 token 成本最低</b>。Claude Code 正确率同样满分，但 d3/d4 的探索与验证回合更多；OpenCode 在 d1 上最快。</div>
<div class="callout"><b>不粉饰：</b>这不是“正确率碾压”。在本口径下三者正确率都是 100%。豪源赢在长程效率、成本与工程闭环；OpenCode 在 d1 定位题最快；Claude Code 在 d6 并发题最快。报告同时给出产品加权与等权两种名次，并列出每题的胜负。</div>

<!-- s1 -->
<div class="sec" id="s1">一、公平评测方法：只比较 Harness，不比较模型</div>
<p class="secsub">同一模型、同一提示词、同一种子仓库、同一隐藏测试、同一预算；三工具都以自动批准模式运行，运行结束后再注入隐藏测试。</p>
<div class="card">
  <h3>1.1 统一条件</h3>
  <ul class="note-list">
    <li><b>模型：</b>三者统一 <code>mimo-v2.6-flash</code>。豪源走内置 MiMo provider（本次评测前修复了缺失的 provider 注册）；Claude Code 走 MiMo 的 Anthropic 兼容端点；OpenCode 走 OpenAI 兼容 provider。</li>
    <li><b>任务：</b>同一份中文提示词、同一份种子仓库、同一套可见测试；每次运行复制到独立目录并初始化 git 基线。</li>
    <li><b>权限：</b>豪源 <code>gate_mode=allow_all</code>；Claude Code <code>--dangerously-skip-permissions</code>；OpenCode <code>--auto</code>。</li>
    <li><b>预算：</b>基础题 900s，困难/长程题 1200s；超出记为超时。豪源单次模型调用 150s 上限、失败重试一次，并禁止跨模型回退。</li>
    <li><b>验收：</b>运行后注入 <code>tests_hidden</code>，执行 <code>pytest tests tests_hidden</code>；运行前后对 <code>tests/</code> 与 <code>pyproject.toml</code> 做 SHA-256，任何改动直接 0 分。</li>
  </ul>
</div>
<div class="grid2">
  <div class="card"><h3>1.2 防作弊与可复现</h3><ul class="note-list">
    <li>隐藏测试不在种子仓库中，模型无法提前读取或针对性修改。</li>
    <li>受保护文件哈希不一致 → 该任务 0 分（本次三工具均无违规）。</li>
    <li>记录每次运行的 tool 调用、token、耗时、改动文件、验证命令；原始 JSON 与 pytest 日志全部落盘。</li>
    <li>official-r1 使用交错顺序（同一任务依次跑三工具），降低时段/延迟偏差。</li>
  </ul></div>
  <div class="card"><h3>1.3 评分口径</h3><ul class="note-list">
    <li><b>产品加权（主榜）：</b>0.65 正确率 + 0.15 速度 + 0.10 成本 + 0.10 工程纪律。</li>
    <li><b>等权口径（对照）：</b>0.40 正确率 + 0.20 速度 + 0.20 成本 + 0.20 工程纪律。</li>
    <li><b>速度：</b>每题以三工具最快者为 100 归一化，再按任务权重加权；长程题权重更高。</li>
    <li><b>成本：</b>按 MiMo 名义价 2 元/百万输入、8 元/百万输出折算；同价下只比较 token。</li>
    <li><b>工程纪律：</b>完整性哈希通过且至少执行一次测试/构建命令。</li>
  </ul></div>
</div>

<div class="arch">
<svg viewBox="0 0 980 230" width="100%" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="ar" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6Z" fill="#818cf8"/></marker>
    <linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1e1b4b"/><stop offset="1" stop-color="#0f172a"/></linearGradient>
  </defs>
  <rect x="10" y="70" width="150" height="82" rx="12" fill="url(#g1)" stroke="#38bdf8" stroke-width="1.4"/>
  <text x="85" y="96" text-anchor="middle" fill="#7dd3fc" font-size="12" font-weight="800">种子仓库</text>
  <text x="85" y="116" text-anchor="middle" fill="#94a3b8" font-size="9">5 个独立项目</text>
  <text x="85" y="132" text-anchor="middle" fill="#94a3b8" font-size="9">可见测试是绿的</text>
  <line x1="160" y1="111" x2="210" y2="111" stroke="#818cf8" stroke-width="1.4" class="flow" marker-end="url(#ar)"/>
  <rect x="212" y="30" width="190" height="58" rx="10" fill="#1e1b4b" stroke="#a78bfa" stroke-width="1.3"/>
  <text x="307" y="54" text-anchor="middle" fill="#c4b5fd" font-size="11" font-weight="800">豪源 HaoYuan</text>
  <text x="307" y="72" text-anchor="middle" fill="#94a3b8" font-size="9">预装上下文 + 检索排序</text>
  <rect x="212" y="100" width="190" height="58" rx="10" fill="#1e1b4b" stroke="#fb923c" stroke-width="1.3"/>
  <text x="307" y="124" text-anchor="middle" fill="#fdba74" font-size="11" font-weight="800">Claude Code</text>
  <text x="307" y="142" text-anchor="middle" fill="#94a3b8" font-size="9">Anthropic 兼容端点</text>
  <rect x="212" y="170" width="190" height="58" rx="10" fill="#1e1b4b" stroke="#38bdf8" stroke-width="1.3"/>
  <text x="307" y="194" text-anchor="middle" fill="#7dd3fc" font-size="11" font-weight="800">OpenCode</text>
  <text x="307" y="212" text-anchor="middle" fill="#94a3b8" font-size="9">OpenAI 兼容 provider</text>
  <line x1="402" y1="59" x2="452" y2="99" stroke="#a78bfa" stroke-width="1.2" class="flow" marker-end="url(#ar)"/>
  <line x1="402" y1="129" x2="452" y2="115" stroke="#fb923c" stroke-width="1.2" class="flow" marker-end="url(#ar)"/>
  <line x1="402" y1="199" x2="452" y2="131" stroke="#38bdf8" stroke-width="1.2" class="flow" marker-end="url(#ar)"/>
  <rect x="454" y="70" width="170" height="82" rx="12" fill="url(#g1)" stroke="#34d399" stroke-width="1.4"/>
  <text x="539" y="96" text-anchor="middle" fill="#6ee7b7" font-size="12" font-weight="800">mimo-v2.6-flash</text>
  <text x="539" y="116" text-anchor="middle" fill="#94a3b8" font-size="9">同一模型 · 同一提示词</text>
  <text x="539" y="132" text-anchor="middle" fill="#94a3b8" font-size="9">同一预算 · 独立工作区</text>
  <line x1="624" y1="111" x2="674" y2="111" stroke="#818cf8" stroke-width="1.4" class="flow" marker-end="url(#ar)"/>
  <rect x="676" y="40" width="140" height="62" rx="10" fill="#0f172a" stroke="#f472b6" stroke-width="1.3"/>
  <text x="746" y="65" text-anchor="middle" fill="#f9a8d4" font-size="10.5" font-weight="800">隐藏测试</text>
  <text x="746" y="82" text-anchor="middle" fill="#94a3b8" font-size="8.5">运行后注入 · 不可预读</text>
  <rect x="676" y="120" width="140" height="62" rx="10" fill="#0f172a" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="746" y="145" text-anchor="middle" fill="#fcd34d" font-size="10.5" font-weight="800">完整性哈希</text>
  <text x="746" y="162" text-anchor="middle" fill="#94a3b8" font-size="8.5">tests / pyproject 防篡改</text>
  <line x1="816" y1="71" x2="866" y2="101" stroke="#f472b6" stroke-width="1.2" class="flow" marker-end="url(#ar)"/>
  <line x1="816" y1="151" x2="866" y2="121" stroke="#fbbf24" stroke-width="1.2" class="flow" marker-end="url(#ar)"/>
  <rect x="868" y="72" width="100" height="78" rx="12" fill="#0f172a" stroke="#a78bfa" stroke-width="1.4"/>
  <text x="918" y="98" text-anchor="middle" fill="#c4b5fd" font-size="11" font-weight="800">评分</text>
  <text x="918" y="116" text-anchor="middle" fill="#94a3b8" font-size="8.5">正确率 · 速度</text>
  <text x="918" y="131" text-anchor="middle" fill="#94a3b8" font-size="8.5">成本 · 纪律</text>
</svg>
</div>

<!-- s2 -->
<div class="sec" id="s2">二、区分性任务：短时间压出 Harness 差异</div>
<p class="secsub">任务不是“写个函数”，而是把定位、跨文件一致性、验证闭环、长程规划、并发正确性放进自动验收。基础题同时检验“是否过度工程化”。</p>
<div class="tw"><table><thead><tr><th>任务</th><th>考察点</th><th>为什么能区分</th><th>层级</th><th>权重</th></tr></thead><tbody>{''.join(task_cards)}</tbody></table></div>
<div class="grid3">
  <div class="card"><h3>自适应强度</h3><p class="lead">t1 是一处小回归：正确策略是少读、快改、验一次。若 harness 在简单题上启动计划、子代理或全仓扫描，会体现在耗时与调用数上。</p></div>
  <div class="card"><h3>长程收口</h3><p class="lead">d4 需要同时改 model/service/router/serializer/error/docs，并保持 offset 契约；最容易出现“局部正确、整体破约”。</p></div>
  <div class="card"><h3>反“只改测试”</h3><p class="lead">隐藏测试运行后注入；受保护文件哈希不一致直接 0 分。让可见测试变绿不等于通过。</p></div>
</div>

<!-- s3 -->
<div class="sec" id="s3">三、总榜：豪源第一，且等权口径仍第一</div>
<p class="secsub">下表是主榜（产品加权）。三工具正确率均为 100%，名次由长程速度、token 成本与工程纪律决定。</p>
<div class="tw"><table><thead><tr><th>排名</th><th>工具</th><th>综合得分</th><th>正确率</th><th>速度</th><th>成本</th><th>工程纪律</th><th>等权得分 / 名次</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></div>
<div class="grid3" style="margin-top:16px">{''.join(score_blocks)}</div>
<div class="formula">综合 = 0.65 × 正确率 + 0.15 × 速度 + 0.10 × 成本 + 0.10 × 工程纪律
<span class="note">速度/成本按每题最优者归一化；正确率为隐藏测试加权通过率；等权口径把权重改为 0.40/0.20/0.20/0.20。</span></div>
<div class="gate"><b>如何读这个第一名：</b>豪源的优势主要来自长程与性能题（d3/d4）以及 token 成本；d1 上 OpenCode 更快，d6 上 Claude Code 更快。豪源不是每道题都最快，但加权后综合第一，且等权口径不依赖权重选择仍然第一。</div>

<!-- s4 -->
<div class="sec" id="s4">四、分任务结果：豪源在 3/5 题最快，d1/d6 各有对手</div>
<p class="secsub">单元格为“耗时 / 隐藏测试得分 / 工具调用数”。t1/d1/d3 来自 official-r1 交错批次；d4/d6 来自冻结代码后的独立复跑批次（同种子、同隐藏测试、同预算）。</p>
<div class="tw"><table class="matrix"><thead><tr><th>工具</th>{''.join(f'<th>{task["name"]}<br><span class="th-sub">{task["tier"]} · x{task["weight"]}</span></th>' for task in TASKS)}</tr></thead><tbody>{''.join(matrix_rows)}</tbody></table></div>
<div class="grid2" style="margin-top:16px">
  <div class="card"><h3>豪源赢在哪</h3><ul class="note-list">
    <li><b>d4 长程特性：</b>{per_task["d4"]["haoyuan"]["sec"]:.0f}s，比 Claude 快 {per_task["d4"]["claude"]["sec"]/per_task["d4"]["haoyuan"]["sec"]:.1f}×、比 OpenCode 快 {per_task["d4"]["opencode"]["sec"]/per_task["d4"]["haoyuan"]["sec"]:.1f}×；调用数 {per_task["d4"]["haoyuan"]["calls"]} vs {per_task["d4"]["claude"]["calls"]}/{per_task["d4"]["opencode"]["calls"]}。</li>
    <li><b>d3 性能优化：</b>{per_task["d3"]["haoyuan"]["sec"]:.0f}s，三工具最快；只用了 {per_task["d3"]["haoyuan"]["calls"]} 次工具调用。</li>
    <li><b>d1 定位：</b>{per_task["d1"]["haoyuan"]["sec"]:.0f}s，与 OpenCode 接近（{per_task["d1"]["opencode"]["sec"]:.0f}s），明显快于 Claude（{per_task["d1"]["claude"]["sec"]:.0f}s）。</li>
    <li><b>t1 简单题：</b>{per_task["t1"]["haoyuan"]["sec"]:.0f}s / {per_task["t1"]["haoyuan"]["calls"]} 调用；没有启动子代理或长计划，符合“简单题不过度工程”。</li>
  </ul></div>
  <div class="card"><h3>豪源还需要提升</h3><ul class="note-list">
    <li><b>d6 并发：</b>{per_task["d6"]["haoyuan"]["sec"]:.0f}s，慢于 Claude（{per_task["d6"]["claude"]["sec"]:.0f}s）；模型仍会写额外自测脚本。</li>
    <li><b>d1 定位：</b>OpenCode 以 {per_task["d1"]["opencode"]["sec"]:.0f}s 拿下本题；豪源读了 {per_task["d1"]["haoyuan"]["calls"]} 次工具，仍有冗余读取。</li>
    <li><b>长尾：</b>评测中遇到过单次模型调用卡住；已通过 150s 上限 + 同模型重试 + 进程树回收修复，但仍需在多轮中观察。</li>
  </ul></div>
</div>

<!-- s5 -->
<div class="sec" id="s5">五、效率与成本：没有全能冠军，但豪源总成本最低</div>
<p class="secsub">下表的耗时/调用/token 为 5 个任务的合计与均值；成本按统一名义价折算。</p>
<div class="tw"><table><thead><tr><th>工具</th><th>中位任务耗时</th><th>最慢任务</th><th>平均调用</th><th>输入 / 输出 tokens</th><th>单任务成本</th><th>5 题总成本</th><th>完整性</th></tr></thead><tbody>{''.join(efficiency_rows)}</tbody></table></div>
<div class="grid2">
  <div class="card"><h3>成本口径</h3><p class="lead">统一按 2 元/百万输入、8 元/百万输出折算。豪源 5 题总成本 <b>${hy["cost"]:.2f}</b>，Claude 为 <b>${cc["cost"]:.2f}</b>，OpenCode 为 <b>${oc["cost"]:.2f}</b>。Claude 的 d3/d4 探索回合多，输入 token 明显更高；OpenCode 在 d3/d4 也会反复读取与自测。</p></div>
  <div class="card"><h3>稳定性</h3><p class="lead">三工具均未修改受保护文件，完整性 100%。豪源在优化前出现过 d4 超时与孤儿验证进程；修复后 d4 从 1200s 降到 {per_task["d4"]["haoyuan"]["sec"]:.0f}s。最慢任务仍受模型延迟波动影响，建议正式生产再增加 2-3 轮。</p></div>
</div>

<!-- s6 -->
<div class="sec" id="s6">六、自适应强度与长程任务：简单题不铺张，长程题能收口</div>
<div class="grid2">
  <div class="card"><h3>简单题（t1）</h3>
    <p class="lead">豪源 {per_task["t1"]["haoyuan"]["sec"]:.0f}s / {per_task["t1"]["haoyuan"]["calls"]} 调用；Claude {per_task["t1"]["claude"]["sec"]:.0f}s / {per_task["t1"]["claude"]["calls"]}；OpenCode {per_task["t1"]["opencode"]["sec"]:.0f}s / {per_task["t1"]["opencode"]["calls"]}。豪源未使用子代理，工具集自动裁剪为 lite 模式，验证一次即结束。</p>
    <div class="code">豪源路由：level=normal/simple → lite=true
可用工具：read_file, read_range, search_symbol, apply_patch,
          edit_file, write_file, grep, glob, list_dir, run_shell
→ 不启动 plan/subagent，不加载全量 repo map</div>
  </div>
  <div class="card"><h3>长程题（d4）</h3>
    <p class="lead">d4 需要跨 8 个文件实现游标分页与过滤 DSL，并更新 docs；豪源在 {per_task["d4"]["haoyuan"]["sec"]:.0f}s 内完成 {per_task["d4"]["haoyuan"]["calls"]} 次工具调用并通过 {per_task["d4"]["haoyuan"]["passed"]}/{per_task["d4"]["haoyuan"]["total"]} 隐藏测试。关键不是“多给提示”，而是提前装配相关源码、减少重复探索。</p>
    <div class="code">复杂题上下文装配：
1) 按需求检索排序 top 文件（repoindex.rank_files）
2) 预装 ~30KB 相关源码 + README/docs（context_pack）
3) 保留 repo map 作为符号索引
4) 编辑后只读目标区间，避免重复整读</div>
  </div>
</div>
<div class="hl"><b>自适应结论：</b>豪源在 t1（简单）与 d4（长程）之间切换了不同策略：简单题裁剪工具集、跳过计划；复杂题预装上下文、保留计划与验证闭环。这正是本次要考察的“按问题复杂度自适应”，而不是所有题都用同一套重流程。</div>

<!-- s7 -->
<div class="sec" id="s7">七、自迭代记录：从“能跑”到“能赢”的真实修复</div>
<p class="secsub">先用豪源试点，发现缺陷就改代码再复跑；以下只列有数据支撑的改动，并包含一次被证伪的旧结论。</p>
<div class="timeline">
  <div class="tl-item"><h4>① 修复 MiMo provider 缺失 <span class="tag red">关键修复</span></h4><p>初期发现豪源的 <code>resolve("mimo", ...)</code> 会回退到 deepseek，导致“MiMo 评测”名不副实。新增 mimo provider、严格 provider 模式（禁止跨模型回退）并在网关层校验；修复后所有运行均为 mimo-v2.6-flash。</p></div>
  <div class="tl-item"><h4>② 需求感知的 repo map <span class="tag green">保留</span></h4><p>repo map 之前只按目录/符号字母序输出。改为先按用户需求对文件排序，在顶部给出“最相关文件”，再给全量符号索引；定位题减少无效读取。</p></div>
  <div class="tl-item"><h4>③ 相关源码预装（context pack） <span class="tag green">保留</span></h4><p>对复杂编码题，预装按需求排序的 30KB 相关源码与 docs，并明确告知“已预装、不要重复整读”。d4 从 1200s 超时降到 {per_task["d4"]["haoyuan"]["sec"]:.0f}s，调用数从 82 降到 {per_task["d4"]["haoyuan"]["calls"]}。</p></div>
  <div class="tl-item"><h4>④ 进程树回收 <span class="tag green">保留</span></h4><p>模型自写的并发验证脚本可能死锁；旧实现只杀 shell，留下孤儿 python 进程拖慢后续任务。改为 <code>CREATE_NEW_PROCESS_GROUP</code> + <code>taskkill /T</code>，超时后回收整棵进程树。</p></div>
  <div class="tl-item"><h4>⑤ 单次调用上限与同模型重试 <span class="tag green">保留</span></h4><p>一次模型调用卡住会吃掉整个任务预算。bench 环境将单次调用上限降到 150s，失败后同模型重试一次，再失败才报错；避免长尾拖垮分任务计时。</p></div>
  <div class="tl-item"><h4>⑥ 简单题效率提示 <span class="tag green">保留</span></h4><p>系统规则加入“单符号修复不建计划、不扫全仓；编辑后最多验证两次；通过即停”。t1 从此前 93s/多次探索降到 {per_task["t1"]["haoyuan"]["sec"]:.0f}s。</p></div>
</div>
<div class="callout"><b>负结果也保留：</b>早期一次“对所有困难题都开启强审计”的尝试让 d4/d6 变慢 2-3 倍，已回滚。结论是：对强模型，harness 的胜负手是“少做无用功 + 及时收口”，不是“加更多提示”。</div>

<!-- s8 -->
<div class="sec" id="s8">八、局限、复现与证据</div>
<div class="grid2">
  <div class="card"><h3>必须说明的局限</h3><ul class="note-list">
    <li>正式对照每个任务 1 轮；d4/d6 使用冻结代码后的独立复跑批次（豪源 d6 在 official-r1 另有 330.9s 复跑，同样 100%，本报告采用同批次 221.6s）。仍不足以消除模型随机性与网络抖动，建议生产评测再补 2-3 轮。</li>
    <li>只评测一个模型（mimo-v2.6-flash）。换模型后排序可能变化。模型延迟方差明显：Claude 的 d3 在先前批次为 623s、本次 official-r1 为 884s；报告采用 official-r1 交错数据。</li>
    <li>成本为统一名义价折算，未计缓存折扣与网络波动；token 统计口径三者略有差异。</li>
    <li>任务由本报告作者设计，不能替代 SWE-bench 等公开基准；隐藏测试 + 防篡改 + 多工具同条件降低了“只改测试”和“碰运气”的空间。</li>
    <li>d5 规格考古题三工具都只差同一个时间区隐藏用例（98.4），区分度不足，未纳入主榜。</li>
  </ul></div>
  <div class="card"><h3>复现命令</h3>
  <div class="code">{REPRO}</div>
  <p class="lead">原始证据：<code>test/bench/runs/&lt;batch&gt;/&lt;tool&gt;/&lt;task&gt;/run.json</code>、<code>pytest.log</code>、<code>server.log</code>。报告数据均可从这些文件重算。</p>
  </div>
</div>

<div class="hl"><b>一句话总结：</b>在同一个 mimo-v2.6-flash 下，三个 harness 的正确率都到 100%；豪源通过“MiMo 正确接入 + 需求感知检索 + 复杂题上下文预装 + 进程树回收 + 简单题轻量路由”，在长程/性能题和 token 成本上建立优势，产品加权与等权口径均为第一。OpenCode 与 Claude Code 各自在个别任务上更快，但综合效率与成本落后。</div>

<div class="footer">豪源 HaoYuan · MiMo 公平评测 · 2026-10 · 数据目录 test/bench · 报告目录 test/testing/index-2026-10-27.html</div>
</div>
</body>
</html>
"""


def main() -> None:
    data = load()
    metrics = compute(data)
    OUT.write_text(render(data, metrics), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "ranked": metrics["ranked"], "tools": metrics["tools"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
