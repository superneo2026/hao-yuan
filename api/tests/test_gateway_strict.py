from __future__ import annotations

import asyncio

import pytest

from adapters.providers.deepseek import ProviderHTTPError, _content_text
from core.gateway import ModelGateway, describe_provider_error


def test_strict_route_rejects_unconfigured_provider():
    gateway = ModelGateway()

    async def run():
        async for _event in gateway.stream(
            "aliyun", "qwen-plus", [{"role": "user", "content": "hi"}], strict=True
        ):
            pass

    with pytest.raises(RuntimeError, match="strict route"):
        asyncio.run(run())


def test_describe_provider_error_maps_common_failures():
    assert "API Key" in describe_provider_error(ProviderHTTPError(401, "invalid key"))
    assert "404" in describe_provider_error(ProviderHTTPError(404, "model not found"))
    assert "thinking" in describe_provider_error(ProviderHTTPError(400, "unsupported thinking"))
    assert "tools" in describe_provider_error(ProviderHTTPError(400, "unknown tool_choice"))
    assert "限流" in describe_provider_error(ProviderHTTPError(429, "rate limit"))


def test_content_text_normalizes_string_parts_and_text_blocks():
    assert _content_text("hello") == "hello"
    assert _content_text([{"type": "text", "text": "a"}, {"type": "output_text", "text": "b"}, "c"]) == "abc"
    assert _content_text({"type": "text", "text": "ignored"}) == ""
