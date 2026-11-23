from __future__ import annotations

from core.runtime import AgentRuntime


class _DummyAgent:
    instructions = ""


def test_complex_reference_research_task_is_not_lite():
    runtime = AgentRuntime.__new__(AgentRuntime)
    text = (
        "D:\\Env\\git\\neo-tts\\v1 是预训练项目；输出第二个预训练计划方案。"
        "HTML页面的风格参考：file:///D:/Env/git/html/llm/qwen36-35b-a3b-llm-posttraining-agent-interview.html；"
        "输出HTML页面到：D:\\Env\\git\\neo-tts\\v2\\plan"
    )
    assert runtime._should_lite({}, "complex", text) is False


def test_research_task_is_not_lite_even_when_normal():
    runtime = AgentRuntime.__new__(AgentRuntime)
    assert runtime._should_lite({}, "normal", "写一份训练计划方案") is False


def test_complex_task_gets_high_thinking_even_if_lite():
    runtime = AgentRuntime.__new__(AgentRuntime)
    assert runtime._thinking({"thinking": ""}, "deepseek", True, "complex", False) == "high"


def test_research_protocol_is_injected_into_system_prompt(tmp_path):
    runtime = AgentRuntime.__new__(AgentRuntime)
    prompt = runtime._system_prompt(
        {"workspace": str(tmp_path)},
        _DummyAgent(),
        "dev",
        "deepseek",
        "deepseek-flash",
        "dev",
        False,
        False,
        [],
        "",
        "",
        False,
        "",
        "",
        research=True,
    )
    assert "baseline evidence table" in prompt
    assert "doc_consistency" in prompt
