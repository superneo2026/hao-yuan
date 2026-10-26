from __future__ import annotations

import asyncio
import json
import re
from typing import Any, AsyncGenerator

from configs.models import ProviderConfig
from core.contracts import ToolCall


class MockProvider:
    name = "mock"

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        profile: ProviderConfig,
        model: str,
        thinking: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        last = messages[-1] if messages else {"role": "user", "content": ""}
        if last.get("role") == "tool":
            content = str(last.get("content") or "")
            text = f"工具执行完成，结果已返回：{content[:600]}"
            async for ev in self._emit_text(text):
                yield ev
            yield {
                "type": "message",
                "message": {"role": "assistant", "content": text},
                "usage": self._usage(),
                "finish_reason": "stop",
            }
            return

        user_text = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_text = str(message.get("content") or "")
                break

        call = self._decide(user_text, tools)
        if call:
            preamble = f"我将调用 {call.name} 工具来完成这一步。"
            async for ev in self._emit_text(preamble):
                yield ev
            yield {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": preamble,
                    "tool_calls": [
                        {
                            "id": call.call_id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                    ],
                },
                "usage": self._usage(),
                "finish_reason": "tool_calls",
            }
            return

        text = (
            f"已收到：{user_text}\n\n当前使用本地 mock 模型（未配置 API Key）。"
            "你可以绑定工作区后让我读取、搜索、编辑文件或执行命令；配置 DEEPSEEK_API_KEY 后即可接入真实模型。"
        )
        async for ev in self._emit_text(text):
            yield ev
        yield {
            "type": "message",
            "message": {"role": "assistant", "content": text},
            "usage": self._usage(),
            "finish_reason": "stop",
        }

    async def _emit_text(self, text: str) -> AsyncGenerator[dict[str, Any], None]:
        chunks = [text[i : i + 16] for i in range(0, len(text), 16)] or [""]
        for chunk in chunks:
            yield {"type": "delta", "text": chunk}
            await asyncio.sleep(0)

    @staticmethod
    def _usage() -> dict[str, Any]:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _decide(self, text: str, tools: list[dict[str, Any]]) -> ToolCall | None:
        names = {(tool.get("function") or {}).get("name") for tool in tools if isinstance(tool, dict)}
        lowered = text.lower()

        match = re.search(r"(?:创建|新建|写入|写)(?:一个|文件)?\s*([\w./-]+\.(?:txt|md|py|js|json))", text)
        if match and "write_file" in names:
            path = match.group(1)
            return ToolCall(
                call_id="call_write",
                name="write_file",
                arguments={"path": path, "content": "# HaoYuan\n\nCreated by the mock agent.\n"},
            )
        if ("计算" in text or "calculate" in lowered) and "calculator" in names:
            expr = re.search(r"([0-9][0-9\s+\-*/().%]*[0-9]|[0-9])", text)
            return ToolCall(
                call_id="call_calc",
                name="calculator",
                arguments={"expression": expr.group(1).strip() if expr else "1+1"},
            )
        if ("列" in text or "目录" in text or "list" in lowered) and "list_dir" in names:
            return ToolCall(call_id="call_list", name="list_dir", arguments={"path": "."})
        if ("读取" in text or "打开" in text) and "read_file" in names:
            path_match = re.search(r"([\w./-]+\.\w+)", text)
            if path_match:
                return ToolCall(
                    call_id="call_read", name="read_file", arguments={"path": path_match.group(1)}
                )
        if "echo" in lowered and "echo" in names:
            value = text.split("echo", 1)[-1].strip(" :：") or "hello haoyuan"
            return ToolCall(call_id="call_echo", name="echo", arguments={"text": value})
        if ("时间" in text or "time" in lowered) and "now" in names:
            return ToolCall(call_id="call_now", name="now", arguments={})
        return None
