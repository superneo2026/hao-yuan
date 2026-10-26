from __future__ import annotations

import json
from typing import Any

from configs.configs import AUTO_APPROVE_HIGH_RISK
from core.contracts import PolicyDecision, ToolSpec
from core.storage import Storage


class PolicyEngine:
    def __init__(self, storage: Storage):
        self.storage = storage

    async def global_gate(self) -> tuple[str, set[str]]:
        mode = await self.storage.get_setting("gate_mode", "ask")
        if mode not in ("ask", "allow_list", "allow_all"):
            mode = "ask"
        raw = await self.storage.get_setting("gate_allow", "")
        try:
            allow = set(json.loads(raw)) if raw else set()
        except (ValueError, TypeError):
            allow = set()
        return mode, allow

    async def authorize(self, spec: ToolSpec, session: dict[str, Any]) -> PolicyDecision:
        mode = session.get("gate_mode") or ""
        raw_allow = session.get("gate_allow") or ""
        if mode:
            try:
                allow = set(json.loads(raw_allow)) if raw_allow else set()
            except (ValueError, TypeError):
                allow = set()
        else:
            mode, allow = await self.global_gate()

        if mode == "allow_all" or AUTO_APPROVE_HIGH_RISK:
            return PolicyDecision(allowed=True, reason="auto approved", risk=spec.risk)
        if spec.name in allow:
            return PolicyDecision(allowed=True, reason="whitelisted", risk=spec.risk)
        if spec.risk == "low" and not spec.confirm:
            return PolicyDecision(allowed=True, reason="low risk", risk=spec.risk)
        if spec.risk == "medium" and not spec.confirm:
            return PolicyDecision(allowed=True, reason="medium risk", risk=spec.risk)
        return PolicyDecision(
            allowed=False,
            requires_approval=True,
            reason=f"{spec.name} requires user approval",
            risk=spec.risk,
        )
