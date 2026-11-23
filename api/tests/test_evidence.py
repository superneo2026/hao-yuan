from __future__ import annotations

import asyncio
import json

from harness import evidence, reference
from tools import dev

from tests.test_tools import ctx_for


def _write_baseline(tmp_path):
    stage = tmp_path / "reports" / "aishell3" / "stage1"
    stage.mkdir(parents=True)
    (stage / "summary.json").write_text(
        json.dumps(
            {
                "stage": "pretrain",
                "steps": 30000,
                "minutes": 143.31,
                "params_m": 12.089,
                "best_val_mel": 0.4959,
            }
        ),
        encoding="utf-8",
    )
    final = tmp_path / "reports" / "aishell3"
    (final / "final_eval.json").write_text(
        json.dumps({"n": 9, "metrics": {"cer": 0.0789, "rtf": 0.042, "f0_median": 256.86}}),
        encoding="utf-8",
    )
    data = tmp_path / "data"
    data.mkdir()
    (data / "data_quality.json").write_text(
        json.dumps(
            {
                "selected": {"utterances": 19688, "speakers": 138, "hours": 20.001},
                "gender": {"female": 19688},
                "vocab_size": 1576,
                "mel_stats": {"sample_rate": 22050, "n_mels": 80, "hop_length": 256},
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_baseline_audit_extracts_measured_facts(tmp_path):
    root = _write_baseline(tmp_path)
    text = evidence.baseline_audit(str(root))
    assert "params_M" in text
    assert "12.089" in text
    assert "30000" in text
    assert "138" in text
    assert "19688" in text
    assert "0.0789" in text


def test_doc_consistency_flags_gender_contradiction(tmp_path):
    root = _write_baseline(tmp_path)
    plan = tmp_path / "plan.html"
    plan.write_text(
        "<html><body><table>"
        "<tr><td>AISHELL-3</td><td>20 h / 138 人 / 全女声</td></tr>"
        "<tr><td>AISHELL-3</td><td>20 h / 138（女 118 / 男 20）</td></tr>"
        "</table></body></html>",
        encoding="utf-8",
    )
    report = evidence.doc_consistency(str(plan), str(root))
    assert "must fix" in report
    assert "全女声" in report
    assert "118" in report
    assert "19688" in report


def test_doc_consistency_accepts_clean_plan(tmp_path):
    root = _write_baseline(tmp_path)
    plan = tmp_path / "plan.html"
    plan.write_text(
        "<html><body><p>AISHELL-3: 20 h / 138 speakers / 19,688 utterances.</p></body></html>",
        encoding="utf-8",
    )
    report = evidence.doc_consistency(str(plan), str(root))
    assert "no cross-section contradictions" in report


def test_reference_digest_includes_copy_ready_css(tmp_path):
    ref = tmp_path / "ref.html"
    ref.write_text(
        "<html><head><style>.w{max-width:1500px}.kpi{display:grid}</style></head>"
        "<body><h1>x</h1></body></html>",
        encoding="utf-8",
    )
    digest = reference.digest(str(ref))
    assert "copy-ready inline css" in digest
    assert ".w{max-width:1500px}" in digest


def test_task_subagent_spec_is_registered():
    from core.harness import harness_instance

    assert "task" in harness_instance().tools.names()


def test_planner_agent_exposes_evidence_and_write_tools():
    from core.harness import harness_instance

    planner = harness_instance().agents.get("planner")
    assert "baseline_audit" in planner.tools
    assert "doc_consistency" in planner.tools
    assert "write_file" in planner.tools
    assert "reference_digest" in planner.tools
    assert "web_screenshot" in planner.tools


def test_web_screenshot_tool_is_registered():
    from core.harness import harness_instance

    assert "web_screenshot" in harness_instance().tools.names()


def test_web_screenshot_reports_missing_browser(tmp_path, monkeypatch):
    page = tmp_path / "index.html"
    page.write_text("<html><body><h1>x</h1></body></html>", encoding="utf-8")
    monkeypatch.setattr(dev, "_find_browser", lambda: None)
    result = asyncio.run(dev.web_screenshot(ctx_for(tmp_path), {"path": "index.html"}))
    assert "no Chrome/Edge" in result


def test_evidence_tool_handlers_resolve_workspace_paths(tmp_path):
    root = _write_baseline(tmp_path)
    context = ctx_for(root)
    assert "12.089" in dev.baseline_audit(context, {"path": "."})
    plan = root / "plan.html"
    plan.write_text(
        "<html><body><p>AISHELL-3: 全女声 / 女 118 / 男 20</p></body></html>",
        encoding="utf-8",
    )
    assert "must fix" in dev.doc_consistency(context, {"path": "plan.html", "baseline": "."})
