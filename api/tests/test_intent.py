from __future__ import annotations

import json

from core.runtime import (
    AgentRuntime,
    detect_kind,
    is_casual_chat,
    is_question,
    is_smalltalk,
    needs_write,
)


class _DummyAgent:
    instructions = ""



def test_greetings_are_smalltalk():
    for text in (
        "你好",
        "你好吗",
        "你你好吗",
        "您好吗",
        "最近怎么样",
        "在吗",
        "谢谢",
        "hi",
        "hello",
        "how are you",
    ):
        assert is_smalltalk(text), text
        assert is_casual_chat(text), text
        assert is_question(text), text
        assert not needs_write(text, False, "dev", True), text


def test_casual_messages_are_not_tasks():
    for text in (
        "今天天气不错",
        "你吃饭了吗",
        "讲个笑话",
        "谢谢你的帮助",
        "1+1 等于几",
        "什么是依赖注入",
        "???",
    ):
        assert is_casual_chat(text), text
        assert not needs_write(text, False, "dev", True), text


def test_work_requests_are_not_casual():
    for text in (
        "你好，帮我修复登录 bug",
        "修复测试失败",
        "重构 app.js",
        "介绍一下这个仓库的架构",
        "跑一下测试",
        "写个脚本",
        "看看 src/main.py",
        "继续执行下一步",
        "改一下",
        "调整一下",
        "删掉这段",
        "做个页面",
    ):
        assert not is_casual_chat(text), text


def test_html_document_with_video_mentions_routes_to_coding():
    text = (
        "帮我书写一个个人副业创业成功的小说，一个HTML页面书写一季的内容。"
        "第一季要录制10个推广视频发布到哔哩哔哩，输出到 D:\\Env\\git\\test\\haoyuan-xiaoshuo"
    )
    assert detect_kind(text) == "dev"


def test_video_storyboard_request_routes_to_video():
    assert detect_kind("帮我写一个短视频分镜脚本") == "video"


def test_plan_request_routes_to_plan():
    assert detect_kind("写一份商业计划书") == "plan"


def test_debug_request_routes_to_coding():
    assert detect_kind("修复视频剪辑脚本的 bug") == "dev"


def test_casual_prompt_skips_workspace_memory(tmp_path):
    (tmp_path / "AGENTS.md").write_text("WORKSPACE MEMORY", encoding="utf-8")
    session = {
        "workspace": str(tmp_path),
        "plan": json.dumps({"title": "Plan", "steps": [{"s": "pending", "t": "do work"}]}),
    }
    runtime = AgentRuntime.__new__(AgentRuntime)
    prompt = runtime._system_prompt(
        session,
        _DummyAgent(),
        "general",
        "mock",
        "mock-deterministic",
        "dev",
        True,
        False,
        [],
        "",
        "",
        True,
    )
    assert "Conversation mode" in prompt
    assert "WORKSPACE MEMORY" not in prompt
    assert "Current plan" not in prompt

