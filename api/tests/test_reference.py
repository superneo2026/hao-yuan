from __future__ import annotations

from core.runtime import AgentRuntime
from harness import reference
from tools import dev

from tests.test_tools import ctx_for

REFERENCE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><title>参考页面</title>
<style>
:root{--bg:#f0f2f5;--acc:#7c3aed}
body{background:#f0f2f5;font-family:'PingFang SC',sans-serif}
.topnav a{color:#475569;border-radius:10px;box-shadow:0 4px 14px rgba(0,0,0,.1)}
.w{max-width:1500px;margin:0 auto}
.kpi{display:grid;grid-template-columns:repeat(4,1fr)}
@media(max-width:1000px){.kpi{grid-template-columns:repeat(2,1fr)}}
@keyframes dashflow{to{stroke-dashoffset:-30}}
</style></head>
<body>
<nav class="topnav"><a href="#a">概览</a><a href="#b">差距</a></nav>
<header class="hdr"><h1>参考标题</h1></header>
<main>
<section id="a"><h2>架构</h2><div class="box"><svg></svg></div><div class="kpi"><div class="kp">1</div></div></section>
<section id="b"><h2>数据</h2><table><tr><td>x</td></tr></table><div class="cd">card</div></section>
</main>
<script>document.addEventListener('click',()=>{})</script>
</body></html>
"""

TARGET_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><title>输出</title>
<style>
body{background:#0b0e14;color:#e6eaf2;font-family:Consolas,monospace}
.w{max-width:1080px}
</style></head>
<body><header><h1>输出标题</h1></header><section><h2>内容</h2></section></body></html>
"""


def test_digest_extracts_design_contract(tmp_path):
    path = tmp_path / "voice-robot.html"
    path.write_text(REFERENCE_HTML, encoding="utf-8")
    report = reference.digest(str(path))
    assert "参考页面" in report
    assert "#7c3aed" in report
    assert "概览" in report
    assert "topnav" in report
    assert "1500px" in report
    assert "1000px" in report
    assert "dashflow" in report
    assert "addeventlistener" in report
    assert "tables=1" in report and "svg=1" in report


def test_resolve_reference_paths_skips_output_target(tmp_path):
    ref = tmp_path / "ref" / "voice-robot.html"
    ref.parent.mkdir()
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    target = tmp_path / "out" / "result.html"
    target.parent.mkdir()
    target.write_text("<html></html>", encoding="utf-8")
    text = f"参考HTML页面的格式：{ref.as_uri()}\n输出HTML页面到：{target}"
    found = reference.resolve_reference_paths(str(tmp_path), text)
    assert found == [str(ref.resolve())]
    followup = f"没有有效参考页面：{ref.as_uri()}，输出了文件：{target}"
    assert reference.resolve_reference_paths(str(tmp_path), followup) == [str(ref.resolve())]


def test_resolve_requires_hint_and_workspace_bound(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    assert reference.resolve_reference_paths(str(tmp_path), "读取 ref.html") == []
    assert reference.resolve_reference_paths(str(tmp_path), "参考 ref.html 的格式") == [str(ref.resolve())]


def test_compare_flags_theme_and_palette_drift(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text(TARGET_HTML, encoding="utf-8")
    report = reference.compare(str(ref), str(target))
    assert "palette drift" in report
    assert "theme mode mismatch" in report


def test_reference_drift_gate_flags_redesign(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text(TARGET_HTML, encoding="utf-8")
    drift = AgentRuntime._reference_drift([str(ref.resolve())], [str(target.resolve())])
    assert "theme mode mismatch" in drift
    assert "palette drift" in drift


def test_reference_drift_gate_accepts_faithful_copy_and_skips_self(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    same = tmp_path / "same.html"
    same.write_text(REFERENCE_HTML, encoding="utf-8")
    assert AgentRuntime._reference_drift([str(ref.resolve())], [str(same.resolve())]) == ""
    assert AgentRuntime._reference_drift([str(ref.resolve())], [str(ref.resolve())]) == ""


def test_reference_digest_and_compare_tools(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(REFERENCE_HTML, encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text(TARGET_HTML, encoding="utf-8")
    context = ctx_for(tmp_path)
    assert "参考页面" in dev.reference_digest(context, {"path": "ref.html"})
    assert "fidelity" in dev.reference_compare(context, {"reference": "ref.html", "target": "target.html"})
    audit = dev.web_audit(context, {"path": ".", "reference": "ref.html"})
    assert "reference_compare" in audit
