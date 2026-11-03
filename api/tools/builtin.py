from __future__ import annotations

import ast
from datetime import datetime, timezone
from typing import Any

from core.contracts import ToolContext, ToolSpec
from harness import sysinfo


def echo(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"text": args.get("text", "")}


_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}
_UNARY_OPS = {ast.UAdd: lambda a: +a, ast.USub: lambda a: -a}


def _eval(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval(node.left)
        right = _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only + - * / // % ** are supported")


def calculator(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    expression = str(args.get("expression") or "").strip()
    if len(expression) > 200:
        raise ValueError("expression too long")
    tree = ast.parse(expression, mode="eval")
    return {"expression": expression, "result": _eval(tree)}


def now(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"now": datetime.now(timezone.utc).isoformat()}


def system_info(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return sysinfo.collect(getattr(ctx, "workspace", "") or "")


def register_builtin_tools(registry, source: str = "core") -> None:
    registry.register(
        ToolSpec(
            name="echo",
            description="Echo text. Useful for connectivity checks.",
            input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            source=source,
        ),
        echo,
    )
    registry.register(
        ToolSpec(
            name="calculator",
            description="Safely evaluate an arithmetic expression (+, -, *, /, //, %, **).",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            source=source,
        ),
        calculator,
    )
    registry.register(
        ToolSpec(
            name="now",
            description="Return the current UTC time.",
            input_schema={"type": "object", "properties": {}},
            source=source,
        ),
        now,
    )
    registry.register(
        ToolSpec(
            name="system_info",
            description="Read-only host information: OS, CPU, memory, disk usage and uptime. Use for questions about this machine's configuration or memory.",
            input_schema={"type": "object", "properties": {}},
            readonly=True,
            risk="low",
            side_effect="none",
            confirm=False,
            source=source,
        ),
        system_info,
    )
