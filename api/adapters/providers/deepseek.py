from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator

import httpx

from configs.configs import LLM_FIRST_CHUNK_TIMEOUT, LLM_STREAM_IDLE_TIMEOUT, LLM_TOTAL_TIMEOUT
from configs.models import ProviderConfig


class DeepSeekProvider:
    name = "deepseek"

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        profile: ProviderConfig,
        model: str,
        thinking: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        if not profile.api_key:
            raise RuntimeError(f"{profile.name} API key is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 8192,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if thinking == "off":
            payload["thinking"] = {"type": "disabled"}
        elif thinking in ("low", "high"):
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = thinking
        elif model in profile.thinking_models:
            payload["thinking"] = {"type": "enabled"}
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

        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20)) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"model gateway HTTP {response.status_code}: {body[:600]}")
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
                    content = delta.get("content")
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
