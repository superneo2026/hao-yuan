from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Awaitable, Callable

from core.contracts import ToolCall, ToolContext, ToolResult, ToolSpec

ToolHandler = Callable[[ToolContext, dict[str, Any]], Any | Awaitable[Any]]


class ToolRegistry:
    def __init__(self):
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        self._specs[spec.name] = spec
        self._handlers[spec.name] = handler

    def unregister_source(self, source: str) -> None:
        for name in [n for n, s in self._specs.items() if s.source == source]:
            self._specs.pop(name, None)
            self._handlers.pop(name, None)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def list_specs(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)

    def names(self) -> list[str]:
        return sorted(self._specs)

    def openai_tools(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        selected = [self._specs[n] for n in names if n in self._specs] if names else list(self._specs.values())
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in selected
        ]

    async def execute(self, call: ToolCall, context: ToolContext, timeout_s: float | None = None) -> ToolResult:
        spec = self._specs.get(call.name)
        if not spec:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=f"unknown tool: {call.name}",
                summary=f"unknown tool {call.name}",
            )
        missing = self._missing_args(spec, call.arguments)
        if missing:
            raw = call.arguments.get("_raw") if isinstance(call.arguments, dict) else None
            if raw is not None:
                error = (
                    "tool arguments were truncated (the model output hit the length limit), so "
                    f"{', '.join(missing)} could not be read. Do not retry the same call: split the work into "
                    "chunks. For large files, create them with write_file using a short skeleton first, then "
                    "append the remaining sections with apply_patch/edit_file (<= 150 lines each)."
                )
            else:
                error = f"missing required args: {', '.join(missing)}"
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=error,
                summary=f"{call.name} argument validation failed",
            )
        handler = self._handlers[call.name]
        limit = timeout_s or spec.timeout_s
        context.call = call
        try:
            if inspect.iscoroutinefunction(handler):
                output = await asyncio.wait_for(handler(context, call.arguments), timeout=limit)
            else:
                output = await asyncio.wait_for(
                    asyncio.to_thread(handler, context, call.arguments), timeout=limit
                )
            if inspect.isawaitable(output):
                output = await asyncio.wait_for(output, timeout=limit)
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=True,
                result=output,
                summary=self.summarize(output),
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=f"tool execution timeout (> {int(limit)}s)",
                summary=f"{call.name} timeout",
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                summary=f"{call.name} failed",
            )

    @staticmethod
    def _missing_args(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
        required = spec.input_schema.get("required", [])
        return [key for key in required if key not in arguments]

    @staticmethod
    def summarize(output: Any, max_chars: int = 1400) -> str:
        if isinstance(output, str):
            text = output
        else:
            try:
                text = json.dumps(output, ensure_ascii=False, default=str)
            except TypeError:
                text = str(output)
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
