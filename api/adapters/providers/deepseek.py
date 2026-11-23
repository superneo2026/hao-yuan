from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator

import httpx

from configs.configs import DEFAULT_MAX_OUTPUT_TOKENS, LLM_FIRST_CHUNK_TIMEOUT, LLM_STREAM_IDLE_TIMEOUT, LLM_TOTAL_TIMEOUT
from configs.configs import LLM_CONNECT_TIMEOUT
from configs.models import ProviderConfig


class ProviderHTTPError(RuntimeError):
    def __init__(self, status: int, body: str, retry_after: str | None = None):
        self.status = int(status)
        self.body = body
        self.retry_after = retry_after
        super().__init__(f"model gateway HTTP {status}: {body[:600]}")


def _content_text(value: Any) -> str:
    """OpenAI-compatible content may be a string or a list of text parts.

    Qwen and some gateways return content arrays; the rest of the runtime expects
    a string, so normalize here instead of failing the whole stream.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(part.get("content"), str):
                    parts.append(part["content"])
        return "".join(parts)
    return ""


# 复用一个长连接客户端：每一次模型调用都重新建 TLS 连接会明显拖慢多步任务。

class DeepSeekProvider:
    name = "deepseek"

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        # Whether the last request carried an explicit max_tokens (used by the
        # 400-retry path to drop only that field).
        self._sent_max_tokens = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(None, connect=LLM_CONNECT_TIMEOUT),
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16, keepalive_expiry=300),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        profile: ProviderConfig,
        model: str,
        thinking: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        try:
            async for event in self._stream_once(
                messages, tools, profile, model, thinking, use_temperature=True
            ):
                yield event
        except ProviderHTTPError as exc:
            body = (exc.body or "").lower()
            # 部分模型（如 Kimi K3、OpenAI o 系列）只接受 temperature=1，去掉该参数重试。
            if exc.status == 400 and "temperature" in body:
                async for event in self._stream_once(
                    messages, tools, profile, model, thinking, use_temperature=False
                ):
                    yield event
            # A provider that rejects our explicit max_tokens (model limit lower
            # than DEFAULT_MAX_OUTPUT_TOKENS) gets the request again without it.
            elif exc.status == 400 and "max_tokens" in body and self._sent_max_tokens:
                self._sent_max_tokens = False
                async for event in self._stream_once(
                    messages, tools, profile, model, thinking, use_max_tokens=False
                ):
                    yield event
            # Some OpenAI-compatible models reject reasoning_effort, thinking or tools.
            # Drop only the offending field and retry instead of falling back to
            # another model or disabling everything at once.
            elif exc.status == 400 and "reasoning_effort" in body:
                async for event in self._stream_once(
                    messages, tools, profile, model, thinking, use_reasoning_effort=False
                ):
                    yield event
            elif exc.status == 400 and any(token in body for token in ("thinking", "reasoning")):
                async for event in self._stream_once(
                    messages, tools, profile, model, thinking, use_thinking=False
                ):
                    yield event
            elif exc.status == 400 and any(token in body for token in ("tool", "function")):
                async for event in self._stream_once(
                    messages, tools, profile, model, thinking, use_tools=False
                ):
                    yield event
            else:
                raise

    async def _stream_once(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        profile: ProviderConfig,
        model: str,
        thinking: str = "",
        use_temperature: bool = True,
        use_thinking: bool = True,
        use_tools: bool = True,
        use_max_tokens: bool = True,
        use_reasoning_effort: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not profile.api_key:
            raise RuntimeError(f"{profile.name} API key is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if use_temperature:
            payload["temperature"] = 0.2
        # Always request an explicit output ceiling. Leaving it unset made the
        # provider apply its own default (8192 on zhipu), which cut a single
        # write_file of a full HTML page in half.
        max_output = profile.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
        self._sent_max_tokens = False
        if max_output > 0 and use_max_tokens:
            payload["max_tokens"] = max_output
            self._sent_max_tokens = True
        if tools and use_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if not profile.supports_thinking or not use_thinking:
            pass
        elif thinking == "off":
            payload["thinking"] = {"type": "disabled"}
        elif thinking in ("low", "high"):
            payload["thinking"] = {"type": "enabled"}
            if use_reasoning_effort:
                payload["reasoning_effort"] = thinking
        elif model in profile.thinking_models:
            payload["thinking"] = {"type": "enabled"}
            if use_reasoning_effort:
                payload["reasoning_effort"] = "high"

        headers = {
            "Authorization": f"Bearer {profile.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{profile.base_url.rstrip('/')}/chat/completions"

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_buffers: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish_reason = "stop"
        started = time.monotonic()
        first = True

        client = self._get_client()
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise ProviderHTTPError(
                    response.status_code, body, response.headers.get("retry-after")
                )
            lines = response.aiter_lines()
            while True:
                budget = LLM_FIRST_CHUNK_TIMEOUT if first else LLM_STREAM_IDLE_TIMEOUT
                if LLM_TOTAL_TIMEOUT:
                    budget = min(budget, max(1.0, LLM_TOTAL_TIMEOUT - (time.monotonic() - started)))
                try:
                    line = await asyncio.wait_for(lines.__anext__(), timeout=budget)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    phase = "first chunk" if first else "stream idle"
                    raise TimeoutError(f"model response {phase} timeout ({int(budget)}s)") from exc
                first = False
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if chunk.get("usage"):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = choice.get("finish_reason") or finish_reason
                delta = choice.get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield {"type": "reasoning", "text": reasoning}
                content = _content_text(delta.get("content"))
                if content:
                    text_parts.append(content)
                    yield {"type": "delta", "text": content}
                for item in delta.get("tool_calls") or []:
                    index = int(item.get("index", 0))
                    buf = tool_buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if item.get("id"):
                        buf["id"] = item["id"]
                    function = item.get("function") or {}
                    if function.get("name"):
                        buf["name"] = function["name"]
                    if function.get("arguments"):
                        buf["arguments"] += function["arguments"]

        calls = []
        for index in sorted(tool_buffers):
            buf = tool_buffers[index]
            try:
                args = json.loads(buf["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": buf["arguments"]}
            calls.append(
                {
                    "id": buf["id"] or f"call_{index}",
                    "type": "function",
                    "function": {"name": buf["name"], "arguments": json.dumps(args, ensure_ascii=False)},
                }
            )
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(text_parts) or None,
            "reasoning_content": "".join(reasoning_parts) or None,
        }
        if calls:
            message["tool_calls"] = calls
        usage_dict = {
            "prompt_tokens": int((usage or {}).get("prompt_tokens") or 0),
            "completion_tokens": int((usage or {}).get("completion_tokens") or 0),
            "cached_tokens": int(((usage or {}).get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
            "reasoning_tokens": int(((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
        }
        yield {
            "type": "message",
            "message": message,
            "usage": usage_dict,
            "finish_reason": finish_reason,
            "provider": profile.name,
            "model": model,
        }
