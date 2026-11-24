from __future__ import annotations

import os

from core.runtime import budget_contract, extract_output_targets, output_target_ready


def test_extract_output_targets_reads_output_hint():
    prompt = "参考页：D:/ref/page.html。请输出评估方案到：D:/Env/out/eval"
    targets = extract_output_targets(prompt, r"D:\Env")
    normalized = [os.path.normpath(item) for item in targets]
    assert os.path.normpath(r"D:\Env\out\eval") in normalized
    assert all(not item.lower().endswith("page.html") for item in normalized)


def test_extract_output_targets_normalizes_file_uri():
    prompt = "输出方案到：file:///C:/Users/Administrator/Downloads/plan"
    targets = extract_output_targets(prompt, r"D:\Env")
    normalized = [os.path.normpath(item) for item in targets]
    assert os.path.normpath(r"C:\Users\Administrator\Downloads\plan") in normalized
    assert all(not item.lower().startswith("e:") for item in normalized)


def test_extract_output_targets_skips_reference_and_previous_plan_links():
    prompt = (
        "输出对比报告 参考：file:///D:/Env/git/html/ref.html\n"
        "输出对比报告 已完成预训练计划：file:///D:/Env/git/neo-tts/v2/test/plan/neo-tts-v2-pretrain-plan.html\n"
        "输出评测报告到：D:\\Env\\git\\neo-tts\\v2\\test\\testing\n"
    )
    targets = extract_output_targets(prompt, r"D:\Env")
    normalized = [os.path.normpath(item) for item in targets]
    assert os.path.normpath(r"D:\Env\git\neo-tts\v2\test\testing") in normalized
    assert not any(item.lower().endswith("ref.html") for item in normalized)
    assert not any(item.lower().endswith("neo-tts-v2-pretrain-plan.html") for item in normalized)


def test_extract_output_targets_keeps_local_plan_output():
    prompt = "输出训练计划：D:\\Env\\out\\plan.html"
    targets = extract_output_targets(prompt, r"D:\Env")
    assert [os.path.normpath(item) for item in targets] == [
        os.path.normpath(r"D:\Env\out\plan.html")
    ]


def test_extract_output_targets_repairs_duplicate_drive_prefix():
    prompt = "输出到：e:\\D:\\Env\\git\\neo-tts\\v2\\test\\plan"
    targets = extract_output_targets(prompt, r"D:\Env")
    assert [os.path.normpath(item) for item in targets] == [
        os.path.normpath(r"D:\Env\git\neo-tts\v2\test\plan")
    ]


def test_output_target_ready_requires_new_file(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    old = out / "old.html"
    old.write_text("<html></html>", encoding="utf-8")
    os.utime(old, (0, 0))
    since = 1.0
    assert output_target_ready(str(out), since) is False
    new = out / "index.html"
    new.write_text("<html></html>", encoding="utf-8")
    assert output_target_ready(str(out), since) is True


def test_output_target_ready_accepts_file_target(tmp_path):
    target = tmp_path / "report.html"
    target.write_text("<html></html>", encoding="utf-8")
    assert output_target_ready(str(target), 1.0) is True
    assert output_target_ready(str(tmp_path / "missing.html"), 1.0) is False


def test_budget_contract_detects_total_budget():
    text = "不论什么模型，总训练时间不超过50小时。请输出最小算力方案。"
    contract = budget_contract(text)
    assert "TOTAL" in contract
    assert "50" in contract
    assert "40-120M" in contract


def test_budget_contract_ignores_plain_task():
    assert budget_contract("write a hello world page") == ""
