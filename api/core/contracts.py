from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high"]
SideEffect = Literal["none", "write", "irreversible"]


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    risk: RiskLevel = "low"
    side_effect: SideEffect = "none"
    timeout_s: float = 30
    readonly: bool = True
    confirm: bool = False
    subagent: bool = False
    source: str = "core"


class ToolCall(BaseModel):
    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    call_id: str
    name: str
    ok: bool
    result: Any = None
    error: str | None = None
    summary: str = ""
    artifact_id: str | None = None
    elapsed_ms: int = 0


class AgentSpec(BaseModel):
    name: str
    title: str
    description: str = ""
    instructions: str = ""
    tools: list[str] = Field(default_factory=list)
    auto_skills: bool = True
    kind: str = "dev"
    source: str = "core"


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    reasoning: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ModelResponse(BaseModel):
    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str = "stop"
    model: str = ""
    provider: str = ""
    fallbacks: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    allowed: bool
    requires_approval: bool = False
    reason: str = ""
    risk: RiskLevel = "low"


@dataclass
class ToolContext:
    runtime: Any
    session: dict[str, Any]
    workspace: str
    call: ToolCall | None = None
    emit: Any = None
    run_id: str = ""

    @property
    def session_id(self) -> str:
        return str(self.session.get("id") or "")

    def restrict(self, relative_path: str) -> str:
        from harness.sandbox import SafeWorkspace

        return str(SafeWorkspace(self.workspace).resolve(relative_path))


@dataclass
class RunState:
    session_id: str
    run_id: str
    step: int = 0
    total_steps: int = 0
    cursor: int = 0
    pending_calls: list[dict[str, Any]] = field(default_factory=list)
    repair_fingerprints: dict[str, int] = field(default_factory=dict)
    last_write_step: int = 0
    last_verify_step: int = 0
    last_shell_step: int = 0
    verify_nudges: int = 0
    rollovers: int = 0
    escalated: bool = False
    final_text: str = ""
