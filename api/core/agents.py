from __future__ import annotations

from typing import Any

from configs.configs import DEFAULT_AGENT
from core.contracts import AgentSpec


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        self._agents[spec.name] = spec

    def unregister_source(self, source: str) -> None:
        for name in [n for n, spec in self._agents.items() if spec.source == source]:
            self._agents.pop(name, None)

    def get(self, name: str | None) -> AgentSpec:
        return self._agents.get(name or "") or self._agents.get(DEFAULT_AGENT) or next(iter(self._agents.values()))

    def list(self) -> list[dict[str, Any]]:
        return [spec.model_dump() for spec in self._agents.values()]

    def names(self) -> list[str]:
        return list(self._agents)
