from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

from configs.configs import EVENT_FLUSH_INTERVAL, WS_SEND_QUEUE_MAX, WS_SEND_TIMEOUT
from core.storage import Storage, now

TOKEN_EVENTS = ("delta", "reasoning")


class EventBus:
    def __init__(self, storage: Storage):
        self.storage = storage
        self._clients: dict[Any, tuple[asyncio.Queue, asyncio.Task]] = {}
        self._sinks: list[Callable[[str, str, dict], Awaitable[None]]] = []
        self._pending: list[dict[str, Any]] = []
        self._merge_index: dict[tuple, int] = {}
        self._flush_task: asyncio.Task | None = None
        self._live_seq = 0
        self._lock = asyncio.Lock()

    def subscribe(self, sink: Callable[[str, str, dict], Awaitable[None]]) -> None:
        if sink not in self._sinks:
            self._sinks.append(sink)

    async def register_client(self, ws: Any) -> None:
        if ws in self._clients:
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=WS_SEND_QUEUE_MAX)
        task = asyncio.create_task(self._sender(ws, queue))
        self._clients[ws] = (queue, task)

    async def unregister_client(self, ws: Any) -> None:
        entry = self._clients.pop(ws, None)
        if entry:
            entry[1].cancel()

    def send_frame(self, ws: Any, frame: str) -> bool:
        entry = self._clients.get(ws)
        if not entry:
            return False
        try:
            entry[0].put_nowait(frame)
            return True
        except asyncio.QueueFull:
            self._drop(ws)
            return False

    async def _sender(self, ws: Any, queue: asyncio.Queue) -> None:
        try:
            while True:
                frame = await queue.get()
                try:
                    await asyncio.wait_for(ws.send_text(frame), timeout=WS_SEND_TIMEOUT)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    break
        except asyncio.CancelledError:
            raise
        finally:
            self._clients.pop(ws, None)

    def _drop(self, ws: Any) -> None:
        entry = self._clients.pop(ws, None)
        if entry:
            entry[1].cancel()

    def _broadcast(self, frame: str) -> None:
        dead = []
        for ws, (queue, _task) in list(self._clients.items()):
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                dead.append(ws)
        for ws in dead:
            self._drop(ws)

    def start(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            try:
                self._flush_task = asyncio.get_running_loop().create_task(self._flush_loop())
            except RuntimeError:
                self._flush_task = None

    async def stop(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except (asyncio.CancelledError, Exception):
                pass
            self._flush_task = None
        await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(EVENT_FLUSH_INTERVAL)
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def flush(self) -> int:
        async with self._lock:
            if not self._pending:
                return 0
            batch, self._pending, self._merge_index = self._pending, [], {}
        try:
            await self.storage.append_events_batch(batch)
        except Exception:
            return 0
        return len(batch)

    async def emit(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> None:
        payload = payload or {}
        ts = now()
        self._live_seq += 1
        frame = json.dumps(
            {
                "session_id": session_id,
                "event": event_type,
                "payload": payload,
                "time": ts,
                "live_seq": self._live_seq,
            },
            ensure_ascii=False,
            default=str,
        )
        self._broadcast(frame)
        self.start()
        key = None
        if event_type in TOKEN_EVENTS:
            key = (session_id, event_type, payload.get("msg_id") or "", run_id)
        if key is not None and key in self._merge_index:
            self._pending[self._merge_index[key]]["payload"]["text"] = (
                self._pending[self._merge_index[key]]["payload"].get("text", "")
                + str(payload.get("text") or "")
            )
        elif len(self._pending) < 5000:
            item = {
                "session_id": session_id,
                "run_id": run_id,
                "type": event_type,
                "payload": dict(payload),
                "created_at": ts,
            }
            self._pending.append(item)
            if key is not None:
                self._merge_index[key] = len(self._pending) - 1
        for sink in list(self._sinks):
            try:
                asyncio.get_running_loop().create_task(self._safe_sink(sink, session_id, event_type, payload))
            except RuntimeError:
                pass

    async def _safe_sink(self, sink, session_id: str, event_type: str, payload: dict) -> None:
        try:
            await sink(session_id, event_type, payload)
        except Exception:
            pass

    async def replay(
        self,
        session_id: str,
        after_id: int = 0,
        limit: int = 2000,
        run_id: str = "",
        tail: bool = False,
    ) -> list[dict[str, Any]]:
        await self.flush()
        return await self.storage.list_events(
            session_id, after_id=after_id, limit=limit, run_id=run_id, tail=tail
        )


_bus: EventBus | None = None


def get_bus(storage: Storage | None = None) -> EventBus:
    global _bus
    if _bus is None:
        if storage is None:
            raise RuntimeError("event bus not initialized")
        _bus = EventBus(storage)
    return _bus
