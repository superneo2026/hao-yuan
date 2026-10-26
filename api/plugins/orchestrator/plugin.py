from __future__ import annotations

from harness import orchestrator


async def startup(ctx) -> None:
    async def sink(session_id: str, event_type: str, payload: dict):
        await orchestrator.on_session_event(ctx.harness, session_id, event_type, payload)

    ctx.events.subscribe(sink)
