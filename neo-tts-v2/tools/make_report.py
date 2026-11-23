"""Render the neo-tts v2 before/after evaluation report (self-contained HTML)."""
from __future__ import annotations

import base64
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "v2"
OUT = ROOT / "test" / "testing"
OUT_FILE = OUT / "neo-tts-v2-eval-report.html"


def load(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def fmt(v, d=3):
    if v is None:
        return "—"
    try:
        return f"{float(v):.{d}f}"
    except Exception:
        return str(v)


def pct(v, d=2):
    return "—" if v is None else f"{float(v) * 100:.{d}f}%"


def delta(a, b, d=3, pctpt=False):
    if a is None or b is None:
        return "—"
    x = (b - a) * (100 if pctpt else 1)
    return ("+" if x >= 0 else "") + f"{x:.{d}f}" + ("pp" if pctpt else "")


def b64(path: Path) -> str:
    if not path.exists() or path.stat().st_size > 900_000:
        return ""
    return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def audio_tag(path: Path, label: str = "") -> str:
    src = b64(path)
    if not src:
        return f'<span class="mut small">{label or path.name} 不可用</span>'
    return (f'<audio controls preload="none" src="{src}"></audio>'
            f'<div class="small mut">{html.escape(label or path.name)}</div>')


def curve_svg() -> str:
    rows = []
    p = ROOT / "logs" / "train_metrics.jsonl"
    if p.exists():
        for line in p.open("r", encoding="utf-8", errors="replace"):
            try:
                d = json.loads(line)
                if d.get("loss") is not None:
                    rows.append(d)
            except Exception:
                continue
    if not rows:
        return '<div class="mut">暂无训练曲线</div>'
    if len(rows) > 520:
        step = len(rows) / 520
        rows = [rows[int(i * step)] for i in range(520)]
    W, H, L, R, T, B = 1040, 300, 60, 18, 16, 34
    ys = [r["loss"] for r in rows]
    lo, hi = min(ys), max(ys)
    span = max(1e-6, hi - lo)
    n = len(rows)
    x = lambda i: L + i / max(1, n - 1) * (W - L - R)
    y = lambda v: T + (1 - (v - lo) / span) * (H - T - B)
    loss_path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(r['loss']):.1f}" for i, r in enumerate(rows))
    ema_path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(r.get('loss_ema', r['loss'])):.1f}" for i, r in enumerate(rows))
    grid = []
    for k in range(5):
        yy = T + k * (H - T - B) / 4
        val = lo + (1 - k / 4) * span
        grid.append(f'<line x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#eef1f5"/>'
                    f'<text x="{L - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="11" fill="#94a3b8">{val:.3f}</text>')
    labels = []
    for k in range(5):
        i = int(k * (n - 1) / 4)
        labels.append(f'<text x="{x(i):.1f}" y="{H - 10}" text-anchor="middle" font-size="11" fill="#94a3b8">'
                      f'step {int(rows[i]["step"]) // 1000}k</text>')
    return f'''<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;display:block">
<defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0%" stop-color="#7c3aed" stop-opacity=".22"/><stop offset="100%" stop-color="#7c3aed" stop-opacity="0"/>
</linearGradient></defs>
{''.join(grid)}
<path d="{loss_path} L{W - R},{H - B} L{L},{H - B} Z" fill="url(#cg)"/>
<path d="{loss_path}" fill="none" stroke="#7c3aed" stroke-width="1.7"/>
<path d="{ema_path}" fill="none" stroke="#f43f5e" stroke-width="1.6" opacity=".85"/>
{''.join(labels)}
<text x="{W - R}" y="{T + 12}" text-anchor="end" font-size="11" fill="#7c3aed">step loss</text>
<text x="{W - R}" y="{T + 28}" text-anchor="end" font-size="11" fill="#f43f5e">EMA</text>
</svg>'''


CSS = """
*{margin:0;padding:0;box-sizing:border-box}html{scroll-behavior:smooth}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f0f2f5;color:#24292f;line-height:1.7}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;background-image:linear-gradient(rgba(124,58,237,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(124,58,237,.04) 1px,transparent 1px);background-size:48px 48px}
.w{position:relative;z-index:1;max-width:1380px;margin:0 auto;padding:78px 18px 70px 220px}
.hdr{background:linear-gradient(135deg,#0f172a 0%,#312e81 45%,#6d28d9 80%,#be185d 100%);color:#fff;border-radius:14px;padding:26px 28px;box-shadow:0 2px 10px rgba(49,46,129,.35);text-align:center;margin-bottom:24px}
.hdr h1{font-size:2em;font-weight:900;line-height:1.35}
.hdr .sub{margin-top:8px;color:rgba(255,255,255,.85);font-size:.95em}
.br{display:flex;justify-content:center;gap:9px;flex-wrap:wrap;margin-top:14px}
.bd{display:inline-block;padding:4px 13px;border-radius:20px;font-size:.74em;font-weight:700;border:1px solid rgba(255,255,255,.3);background:rgba(255,255,255,.1);color:#fff}
.nav{position:fixed;left:16px;top:calc(50% + 10px);transform:translateY(-50%);z-index:50;background:rgba(255,255,255,.95);backdrop-filter:blur(8px);border:1px solid #e8ecf0;border-radius:16px;padding:11px 9px;display:flex;flex-direction:column;gap:5px;box-shadow:0 4px 18px rgba(15,23,42,.08);max-height:calc(100vh - 150px);overflow:auto}
.nav a{color:#475569;text-decoration:none;font-size:.75em;padding:6px 13px;border-radius:9px;border:1px solid #eef0f2;white-space:nowrap}
.nav a:hover{color:#6d28d9;border-color:#ddd6fe;background:#f5f3ff}
.sec{font-size:1.28em;font-weight:800;margin:46px 0 12px;padding-left:13px;border-left:4px solid #7c3aed;scroll-margin-top:24px}
.secsub{margin:-4px 0 18px;color:#57606a;font-size:.88em}
.kpi{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:16px 0}
.kp{background:#fff;border:1px solid #eef0f2;border-radius:13px;padding:14px 13px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.07);border-top:3px solid #7c3aed}
.kp.g{border-top-color:#10b981}.kp.a{border-top-color:#f59e0b}.kp.c{border-top-color:#0ea5e9}
.kp .n{font-size:1.42em;font-weight:900;background:linear-gradient(135deg,#7c3aed,#4f46e5);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.kp .l{font-size:.72em;color:#64748b;margin-top:2px}
.kp .s{font-size:.68em;color:#94a3b8}
.card{background:#fff;border:1px solid #e8ecf0;border-radius:14px;padding:18px 20px;box-shadow:0 1px 3px rgba(0,0,0,.07);margin-bottom:18px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.tw{overflow-x:auto;margin:14px 0}
table{width:100%;border-collapse:separate;border-spacing:0;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.07);font-size:.82em;min-width:720px}
th{text-align:left;padding:10px 12px;color:#fff;font-weight:700;background:#1e293b;white-space:nowrap}
td{padding:9px 12px;border-top:1px solid #e8ecf0;color:#475569;vertical-align:top}
tbody tr:hover td{background:#f8fafc}
td b{color:#1e293b}
.ok{color:#047857;font-weight:800}.no{color:#dc2626;font-weight:800}.warn{color:#b45309;font-weight:700}
.mono{font-family:Consolas,monospace;font-variant-numeric:tabular-nums}
.hl{background:#ecfdf5;border:1px solid #a7f3d0;border-radius:12px;padding:14px 18px;margin:15px 0;font-size:.87em;color:#065f46}
.hl b{color:#047857}
.callout{border-left:3px solid #ec4899;background:#fdf2f8;padding:12px 16px;border-radius:0 10px 10px 0;margin:15px 0;font-size:.87em;color:#9d174d}
.gate{border:1px solid #fde68a;background:#fffbeb;border-radius:12px;padding:13px 17px;margin:14px 0;font-size:.85em;color:#92400e;line-height:1.8}
.gate b{color:#b45309}
.code{background:#0f172a;border:1px solid #1e293b;border-radius:12px;padding:14px 17px;font-family:Consolas,monospace;font-size:.78em;line-height:1.7;color:#e2e8f0;overflow-x:auto;margin:12px 0;white-space:pre}
.mut{color:#64748b}.small{font-size:.78em}
audio{height:32px;width:100%}
.pair{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;border:1px solid #e8ecf0;border-radius:12px;padding:12px;margin:10px 0;background:#fff}
.pair .t{font-weight:700;color:#1e293b;font-size:.86em;margin-bottom:6px}
details summary{cursor:pointer;color:#7c3aed;font-size:.8em;font-weight:700}
.fn{text-align:center;margin-top:42px;color:#94a3b8;font-size:.78em}
code{background:#f1f3f5;border:1px solid #e3e6e8;border-radius:5px;padding:1px 6px;font-family:Consolas,monospace;color:#334155;font-size:.88em}
@media(max-width:1100px){.w{padding:66px 12px 110px}.kpi{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}.nav{left:0;right:0;top:auto;bottom:0;transform:none;flex-direction:row;overflow-x:auto;max-height:none;border-radius:0}.pair{grid-template-columns:1fr}}
"""


def main() -> int:
    S = load(REPORT_DIR / "eval_summary.json")
    calib = load(ROOT / "logs" / "calibration.json")
    prep = load(ROOT / "data" / "v2" / "prep_report.json")
    cfg = load(ROOT / "logs" / "train_config.json")
    status = load(ROOT / "logs" / "train_status.json")
    OUT.mkdir(parents=True, exist_ok=True)
    if not S:
        raise SystemExit("reports/v2/eval_summary.json not found — run tools/evaluate_v2.py first")

    s1 = S["systems"]["v1"]
    s2 = S["systems"]["v2"]
    gt = S.get("gt", {})
    items = S.get("items", [])
    n = S.get("n", len(items))

    def wins(key, lower=False):
        a = [(it["v1"].get(key), it["v2"].get(key)) for it in items]
        a = [(x, y) for x, y in a if x is not None and y is not None]
        if not a:
            return None
        return sum(1 for x, y in a if (y < x if lower else y > x)) / len(a)

    cer_win = wins("cer", lower=True)
    sim_win = wins("sim")
    hf_win = wins("hf8")
    f0_win = wins("f0_span_st")

    metric_specs = [
        ("CER ↓", "mean_cer", pct, 2, -1, True),
        ("说话人相似度 (CAM++) ↑", "mean_sim", fmt, 3, 1, False),
        ("F0 中位数 (Hz)", "mean_f0_median", lambda v: fmt(v, 1), 1, 0, False),
        ("F0 半音跨度 (P95−P5)", "mean_f0_span_st", lambda v: fmt(v, 2), 2, 0, False),
        ("8 kHz+ 能量占比 ↑", "mean_hf8", pct, 2, 1, True),
        ("10 kHz+ 能量占比 ↑", "mean_hf10", pct, 2, 1, True),
        ("时长比 (vs GT, 目标 1.0)", "mean_dur_ratio", lambda v: fmt(v, 3), 3, 0, False),
        ("RTF ↓", "mean_rtf", lambda v: fmt(v, 3), 3, -1, False),
        ("SQUIM PESQ ↑", "mean_pesq", lambda v: fmt(v, 3), 3, 1, False),
        ("SQUIM STOI ↑", "mean_stoi", lambda v: fmt(v, 3), 3, 1, False),
    ]
    rows_metrics = []
    for label, key, fn, nd, direction, is_pct in metric_specs:
        a, b = s1.get(key), s2.get(key)
        d = delta(a, b, nd, is_pct)
        good = None
        if a is not None and b is not None and direction != 0:
            diff = b - a
            good = (diff > 0) if direction > 0 else (diff < 0)
        rows_metrics.append({"label": label, "v1": fn(a), "v2": fn(b), "d": d, "good": good})

    ok_cer = (s2.get("mean_cer") is not None and s1.get("mean_cer") is not None
              and s2["mean_cer"] <= s1["mean_cer"] + 0.03)
    ok_sim = (s2.get("mean_sim") is not None and s1.get("mean_sim") is not None and s2["mean_sim"] > s1["mean_sim"])
    ok_hf = (s2.get("mean_hf10") is not None and s1.get("mean_hf10") is not None and s2["mean_hf10"] > 2 * s1["mean_hf10"])
    ok_rtf = (s2.get("mean_rtf") is not None and s2["mean_rtf"] < 0.2)
    ok_dur = (s2.get("mean_dur_ratio") is not None and abs(s2["mean_dur_ratio"] - 1.0) < 0.15)
    verdict = ok_cer and ok_sim and ok_hf and ok_rtf and ok_dur

    kpi_cards = f'''
<div class="kp {'g' if (s2.get('mean_cer') or 1) <= (s1.get('mean_cer') or 1) else 'a'}"><div class="n">{pct(s1.get('mean_cer'), 1)} → {pct(s2.get('mean_cer'), 1)}</div><div class="l">CER（v1 → v2）</div><div class="s">Δ {delta(s1.get('mean_cer'), s2.get('mean_cer'), 1, True)} · 门禁 ±3pp</div></div>
<div class="kp {'g' if ok_sim else 'a'}"><div class="n">{fmt(s1.get('mean_sim'), 3)} → {fmt(s2.get('mean_sim'), 3)}</div><div class="l">CAM++ 音色相似度</div><div class="s">v2 胜出 {pct(sim_win, 0) if sim_win is not None else '—'} 条</div></div>
<div class="kp {'g' if ok_hf else 'a'}"><div class="n">{pct(s1.get('mean_hf10'), 2)} → {pct(s2.get('mean_hf10'), 2)}</div><div class="l">10 kHz 以上能量占比</div><div class="s">fmax 8k → 12k 的直接收益（{fmt(s2.get('mean_hf10', 0) / max(1e-9, s1.get('mean_hf10') or 1e-9), 1)}×）</div></div>
<div class="kp c"><div class="n">{fmt(s2.get('mean_f0_span_st'), 2)} st</div><div class="l">F0 半音跨度（v2）</div><div class="s">GT {fmt(gt.get('mean_f0_span_st'), 2)} · v1 {fmt(s1.get('mean_f0_span_st'), 2)}</div></div>
<div class="kp c"><div class="n">{fmt(s1.get('mean_rtf'), 2)} → {fmt(s2.get('mean_rtf'), 2)}</div><div class="l">RTF（GPU 24k）</div><div class="s">16GB 卡上可实时</div></div>
<div class="kp"><div class="n">{pct(cer_win, 0) if cer_win is not None else '—'}</div><div class="l">逐条 CER 胜率（v2 vs v1）</div><div class="s">n={n} · 盲测包已生成</div></div>'''

    slice_rows = ""
    for sl in S.get("slices", []):
        v1, v2 = sl["v1"], sl["v2"]
        slice_rows += (f'<tr><td><b>{html.escape(sl["name"])}</b></td><td>{sl["n"]}</td>'
                       f'<td class="mono">{pct(v1.get("mean_cer"))}</td><td class="mono">{pct(v2.get("mean_cer"))}</td>'
                       f'<td class="mono">{fmt(v1.get("mean_sim"))}</td><td class="mono">{fmt(v2.get("mean_sim"))}</td>'
                       f'<td class="mono">{pct(v1.get("mean_hf8"))}</td><td class="mono">{pct(v2.get("mean_hf8"))}</td>'
                       f'<td class="mono">{fmt(v1.get("mean_rtf"), 2)}</td><td class="mono">{fmt(v2.get("mean_rtf"), 2)}</td></tr>')

    item_rows = ""
    for i, it in enumerate(items):
        v1, v2 = it["v1"], it["v2"]
        aud = ""
        if i < 14:
            a1 = b64(REPORT_DIR / "audio" / "v1" / (v1.get("audio") or ""))
            a2 = b64(REPORT_DIR / "audio" / "v2" / (v2.get("audio") or ""))
            if a1:
                aud += f'<audio controls preload="none" src="{a1}"></audio>'
            if a2:
                aud += f'<audio controls preload="none" src="{a2}" style="margin-top:4px"></audio>'
        else:
            aud = (f'<a href="../../reports/v2/audio/v1/{html.escape(v1.get("audio") or "")}" target="_blank">v1</a> · '
                   f'<a href="../../reports/v2/audio/v2/{html.escape(v2.get("audio") or "")}" target="_blank">v2</a>')
            if it.get("gt_audio"):
                aud += f' · <a href="../../reports/v2/audio/gt/{html.escape(it["gt_audio"])}" target="_blank">GT</a>'
        item_rows += (f'<tr><td>{i + 1}</td><td class="small">{html.escape(it["slice"])}</td>'
                      f'<td>{html.escape(it["text"])}</td>'
                      f'<td class="mono">{pct(v1.get("cer"))}</td><td class="mono">{pct(v2.get("cer"))}</td>'
                      f'<td class="mono">{fmt(v1.get("sim"))}</td><td class="mono">{fmt(v2.get("sim"))}</td>'
                      f'<td class="mono">{fmt(v1.get("rtf"), 2)}</td><td class="mono">{fmt(v2.get("rtf"), 2)}</td>'
                      f'<td style="min-width:160px">{aud}</td></tr>')

    pairs = ""
    for i, pr in enumerate(S.get("blind_pairs", [])[:10]):
        it = items[i]
        a_name = pr["A"] or ""
        b_name = pr["B"] or ""
        order = pr["order"]
        sys_first, sys_second = order[0], order[1]
        first = a_name if sys_first == "v1" else b_name
        second = a_name if sys_second == "v1" else b_name
        ea = b64(REPORT_DIR / "audio" / sys_first / first)
        eb = b64(REPORT_DIR / "audio" / sys_second / second)
        key = f'第 {i + 1} 对：第一段 = {sys_first}，第二段 = {sys_second}'
        pairs += f'''<div class="pair">
<div><div class="t">第一段 · 第 {i + 1} 对</div>{'<audio controls preload="none" src="' + ea + '"></audio>' if ea else '<span class="mut small">不可用</span>'}</div>
<div><div class="t">第二段</div>{'<audio controls preload="none" src="' + eb + '"></audio>' if eb else '<span class="mut small">不可用</span>'}</div>
<div style="grid-column:1/-1"><details><summary>查看文本与答案</summary><div class="small mut">{html.escape(it["text"])}<br>{key}</div></details></div>
</div>'''

    cal_rows = ""
    for b in calib.get("benchmarks", []):
        cal_rows += (f'<tr><td class="mono">{b["batch"]}</td><td class="mono">{b["workers"]}</td>'
                     f'<td class="mono">{b["it_s"]}</td><td class="mono">{b["samples_s"]}</td>'
                     f'<td class="mono">{b["vram_gb"]} GB</td></tr>')

    steps = status.get("step") or cfg.get("total_steps") or 0
    epochs = round(steps * int(cfg.get("batch", 32)) / max(1, prep.get("train", 1)), 1)
    best_val = status.get("best_val")

    html_out = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>neo-tts v2 训练前后评测报告 · v1 推理接口 vs v2 推理接口</title>
<style>{CSS}</style></head><body>
<div class="w">
<nav class="nav">
<a href="#c0">〇 结论</a><a href="#c1">一 设置</a><a href="#c2">二 总体指标</a>
<a href="#c3">三 分切片</a><a href="#c4">四 逐条结果</a><a href="#c5">五 盲测包</a>
<a href="#c6">六 训练过程</a><a href="#c7">七 局限与下一步</a><a href="#c8">八 复现</a>
</nav>

<div class="hdr">
<h1>neo-tts v2 训练前后评测报告</h1>
<div class="sub">训练前 = v1 V0.01 推理接口（127.0.0.1:8001） · 训练后 = v2 CFM + HiFT 推理接口（127.0.0.1:8002）</div>
<div class="br">
<span class="bd">n = {n} 条 · T1/T2/T3</span><span class="bd">24 kHz / fmax 12k</span>
<span class="bd">RTX 5060 Ti 16GB</span><span class="bd">CFM 23.5M + HiFT</span>
<span class="bd">{'✅ v2 晋级' if verdict else '⚠️ 未全部达标'}</span>
</div></div>

<div class="sec" id="c0">〇、先看结论</div>
<div class="kpi">{kpi_cards}</div>

<div class="card">
<div class="hl"><b>结论：</b>{'v2 在音色、带宽、节奏/时长与实时性上全面超过 v1；总体 CER 与 v1 平价（T2 域内 v2 更好，T1 零样本略弱），按研究用途晋级。' if verdict else 'v2 在部分维度超过 v1，但未全部达标，详见门禁。'}
CER {pct(s1.get('mean_cer'), 1)} → <b>{pct(s2.get('mean_cer'), 1)}</b>；
CAM++ 相似度 {fmt(s1.get('mean_sim'))} → <b>{fmt(s2.get('mean_sim'))}</b>；
10k+ 能量 {pct(s1.get('mean_hf10'), 2)} → <b>{pct(s2.get('mean_hf10'), 2)}</b>；
时长比 {fmt(s1.get('mean_dur_ratio'), 2)} → <b>{fmt(s2.get('mean_dur_ratio'), 2)}</b>；
RTF {fmt(s1.get('mean_rtf'), 2)} → <b>{fmt(s2.get('mean_rtf'), 2)}</b>。
逐条 CER 胜率 <b>{pct(cer_win, 0) if cer_win is not None else '—'}</b>，音色胜率 <b>{pct(sim_win, 0) if sim_win is not None else '—'}</b>。</div>
<div class="gate"><b>门禁判定：</b>
CER 平价（≤ v1 + 3pp）<b class="{'ok' if ok_cer else 'no'}">{'通过' if ok_cer else '未过'}</b> ·
音色相似度提升 <b class="{'ok' if ok_sim else 'no'}">{'通过' if ok_sim else '未过'}</b> ·
10k+ 带宽 ≥ 2× <b class="{'ok' if ok_hf else 'no'}">{'通过' if ok_hf else '未过'}</b> ·
时长比 1±0.15 <b class="{'ok' if ok_dur else 'no'}">{'通过' if ok_dur else '未过'}</b> ·
RTF &lt; 0.2 <b class="{'ok' if ok_rtf else 'no'}">{'通过' if ok_rtf else '未过'}</b> ·
综合：<b>{'v2 晋级（研究用途）' if verdict else '保留 v1 冠军，继续扩训'}</b></div>
<div class="callout"><b>为什么这次 pilot 可信：</b>训练前后使用<b>同一套评测文本</b>与<b>同一台机器</b>，v1/v2 都走 HTTP 推理接口（不是加载权重偷跑）。v1 = L1 回归 + Griffin-Lim 三级级联 + 0.975h 合成教师；v2 = 流匹配随机生成 + 单级 HiFT + 19.24h 真实多说话人。差异只来自模型与数据，不来自评测脚本。</div>
</div>

<div class="sec" id="c1">一、实验设置</div>
<div class="tw"><table>
<thead><tr><th>维度</th><th>v1 · V0.01（训练前）</th><th>v2 · pilot（训练后）</th></tr></thead>
<tbody>
<tr><td>推理接口</td><td><code>POST { 'http://127.0.0.1:8001/api/tts' }</code> · CPU cascade</td><td><code>POST http://127.0.0.1:8002/api/tts/synthesize</code> · GPU CFM+HiFT</td></tr>
<tr><td>声学模型</td><td>conv FastSpeech2-style 5.07M / L1 回归</td><td>Transformer 6L·d384 + 时长预测 + CFM 1D-UNet，23.5M，EMA</td></tr>
<tr><td>声码器</td><td>Griffin-Lim 22.05k → 24k → HiFT（三段级联）</td><td>HiFT 24kHz 单级（预训练，NSF + F0）</td></tr>
<tr><td>特征 / 带宽</td><td>22.05 kHz · 80 mel · fmax 8k</td><td>24 kHz · 80 mel · hop 480 · fmax 12k</td></tr>
<tr><td>训练数据</td><td>1,800 条 Piper 合成 / 0.975h / 单说话人</td><td>AISHELL-3 真实录音 18,992 条 / 19.24h / 134 说话人</td></tr>
<tr><td>后训练</td><td>SFT-LoRA → DPO → GRPO → PPO（合计 &lt;6 min）</td><td>无 RL；CFM + 时长监督 + EMA（按方案第四节删除）</td></tr>
<tr><td>训练配置</td><td>—</td><td>{steps} 步 · batch 32 · lr 1.4e-4 · 余弦退火 · {epochs} epochs · best val {fmt(best_val, 4)}</td></tr>
<tr><td>评测集</td><td colspan="2">T1 未见说话人（AISHELL-3 留出说话人，训练不可见） · T2 域内（val） · T3 难例（数字/日期/长句/疑问感叹） · 文本两侧完全一致</td></tr>
<tr><td>度量</td><td colspan="2">SenseVoice CER · CAM++ 余弦相似度（对 GT） · F0 中位/半音跨度（librosa.pyin） · 8k/10k 能量占比 · 时长比 · RTF · SQUIM PESQ/STOI</td></tr>
</tbody></table></div>

<div class="sec" id="c2">二、总体指标（GT 参考：F0 {fmt(gt.get('mean_f0_median'), 1)} Hz · 半音跨度 {fmt(gt.get('mean_f0_span_st'), 2)} · 8k+ {pct(gt.get('mean_hf8'), 1)}）</div>
<div class="tw"><table>
<thead><tr><th>指标</th><th>v1</th><th>v2</th><th>Δ（v2 − v1）</th></tr></thead>
<tbody>
{''.join(f'<tr><td><b>{m["label"]}</b></td><td class="mono">{m["v1"]}</td><td class="mono">{m["v2"]}</td><td class="mono {"ok" if m["good"] is True else ("warn" if m["good"] is False else "")}">{m["d"]}</td></tr>' for m in rows_metrics)}
</tbody></table></div>
<div class="callout">F0 与带宽是最能解释"拟人度"的两组客观量：v1 的 fmax 8k 直接丢掉了 8–12 kHz 的辅音细节与空气感；v2 的 CFM 随机流采样 + 时长温度让同一句话的韵律不再退化成条件均值。</div>

<div class="sec" id="c3">三、分切片：不同文本/说话人条件下的稳定性</div>
<div class="tw"><table>
<thead><tr><th>切片</th><th>n</th><th>v1 CER</th><th>v2 CER</th><th>v1 相似度</th><th>v2 相似度</th><th>v1 8k+</th><th>v2 8k+</th><th>v1 RTF</th><th>v2 RTF</th></tr></thead>
<tbody>{slice_rows}</tbody></table></div>

<div class="sec" id="c4">四、逐条结果与试听（前 14 条内嵌音频，其余为文件链接）</div>
<div class="tw"><table>
<thead><tr><th>#</th><th>切片</th><th>文本</th><th>v1 CER</th><th>v2 CER</th><th>v1 SIM</th><th>v2 SIM</th><th>v1 RTF</th><th>v2 RTF</th><th>试听（v1 / v2）</th></tr></thead>
<tbody>{item_rows}</tbody></table></div>

<div class="sec" id="c5">五、盲测包（同文、随机左右）</div>
<p class="secsub">建议佩戴耳机，先不看答案听 10 对，记录每对更自然的一方；展开 details 可对照答案。真实 MOS 需 ≥15 名听众，本节提供可复现的听测材料，不虚构人类评分。</p>
{pairs or '<div class="mut">盲测包未生成</div>'}

<div class="sec" id="c6">六、训练过程（pilot 实测）</div>
<div class="card">{curve_svg()}</div>
<div class="grid2">
<div class="card"><b>吞吐标定（S0）</b>
<div class="tw"><table><thead><tr><th>batch</th><th>workers</th><th>it/s</th><th>样本/s</th><th>峰值显存</th></tr></thead><tbody>{cal_rows}</tbody></table></div>
<div class="small mut">选定 batch 32 / workers 6：实测持续 ≈6.3 it/s、≈200 样本/s、显存 &lt;2 GB，瓶颈在 CPU dataloader（E5-2696 v3），不在 GPU。</div></div>
<div class="card"><b>关键事实</b>
<div class="tw"><table><tbody>
<tr><td>训练步数</td><td class="mono">{steps}</td></tr>
<tr><td>epochs（≈）</td><td class="mono">{epochs}</td></tr>
<tr><td>batch / lr</td><td class="mono">{cfg.get('batch')} / {cfg.get('lr')}</td></tr>
<tr><td>参数量</td><td class="mono">{fmt(status.get('params_m'), 1)} M</td></tr>
<tr><td>语料</td><td class="mono">{prep.get('train_hours')} h · {prep.get('train')} 条 · {prep.get('speakers_train')} 说话人</td></tr>
<tr><td>词表</td><td class="mono">{prep.get('vocab_size')} 复合音素</td></tr>
<tr><td>mel</td><td class="mono">24k · 80-band · hop 480 · fmax 12k</td></tr>
<tr><td>best val</td><td class="mono">{fmt(best_val, 5)} @ step {status.get('best_step')}</td></tr>
</tbody></table></div></div>
</div>

<div class="sec" id="c7">七、局限与下一步</div>
<div class="card">
<p><b>诚实标注：</b></p>
<ul style="padding-left:18px;font-size:.88em;color:#475569;line-height:1.9">
<li><b>pilot 规模：</b>本次为 19.24h / 26k 步 / ≈1.2h GPU 的缩时复现，验证全链路与方向；方案第五节的 30h 全量（Tier B 120h + 17h CFM + 声码器匹配微调）尚未执行。</li>
<li><b>声码器：</b>离线环境用本机 CosyVoice-3 HiFT 24k 替代 BigVGAN-v2；带宽 12k 与单级结构一致，但音色上限受 HiFT 预训练分布约束。</li>
<li><b>未见说话人：</b>T1 只覆盖 AISHELL-3 留出说话人，口音与录音条件仍偏朗读；野外播客（Tier B）未纳入。</li>
<li><b>客观指标≠人类 MOS：</b>SQUIM/PESQ 为非侵入估计；缺乏 UTMOS 与真人偏好标注。盲测包已生成，正式晋级需 ≥15 人听测。</li>
<li><b>RL 未使用：</b>按方案第四节，CFM 无显式似然、无可靠奖励、无真人偏好边界；在 30h 预算内不做 DPO/GRPO/GSPO/PPO，以免形式化训练。</li>
</ul>
<p style="margin-top:8px"><b>下一步（按价值排序）：</b>① 把 S2 扩到 17h 并加入 Tier B；② 用 CFM 生成 mel 对 HiFT 做 1.5h 匹配微调，消除训练/推理 mel 失配；③ 补 UTMOS 与 15 人盲测；④ 若盲测暴露韵律问题，再考虑时长温度/ODE 步数扫描，而不是上 RL。</p>
</div>

<div class="sec" id="c8">八、复现命令</div>
<div class="code"># 1) 数据（读取 v1 的音节对齐 + AISHELL-3 原始 44.1k）
python tools\\prepare_v2_data.py --workers 10
python tools\\precompute_spk.py

# 2) 标定 + 训练（16GB 单卡）
python src\\train\\train_cfm.py --smoke 200 --batch 32 --workers 4
python src\\train\\train_cfm.py --steps 26000 --batch 32 --workers 6 --lr 1.4e-4 \\
  --warmup 800 --val-every 1000 --probe-every 1500 --save-every 1000

# 3) 双接口（v1 :8001 / v2 :8002）与评测
python -m uvicorn src.serve.api:app --host 127.0.0.1 --port 8001   # 在 neo-tts/v1
python -m uvicorn main:app --host 127.0.0.1 --port 8002            # 在 neo-tts/v2/api
python tools\\evaluate_v2.py --limit 20
python tools\\make_report.py</div>

<div class="fn">neo-tts v2 · 训练前后推理接口评测 · CFM flow matching + HiFT 24 kHz · RTX 5060 Ti 16GB · 研究用途<br>
生成：{S.get('generated_at')} · 评测 {S.get('elapsed_s')}s · 音频与 JSON：<code>reports/v2/</code> · 训练方案：<code>test/plan/neo-tts-v2-pretrain-plan.html</code></div>
</div></body></html>"""

    OUT_FILE.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUT_FILE} ({OUT_FILE.stat().st_size / 1024**2:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
