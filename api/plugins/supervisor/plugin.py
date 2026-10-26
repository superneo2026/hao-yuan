from __future__ import annotations

import asyncio

from harness.supervisor import watch_loop

_task: asyncio.Task | None = None


async def startup(ctx) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(watch_loop(ctx.harness))


async def shutdown(ctx) -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
        _task = None
