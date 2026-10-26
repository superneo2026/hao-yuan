from __future__ import annotations

import json

from fastapi import WebSocket, WebSocketDisconnect

from core.harness import harness_instance


async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    harness = harness_instance()
    bus = harness.events
    await bus.register_client(ws)
    try:
        await ws.send_text(
            json.dumps({"event": "ws.ready", "session_id": "*", "payload": {"ok": True}})
        )
        while True:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            message_type = message.get("type")
            if message_type == "ping":
                bus.send_frame(
                    ws,
                    json.dumps({"event": "pong", "session_id": "*", "payload": message.get("payload") or {}}),
                )
            elif message_type == "approval.resolve":
                approval_id = message.get("approval_id")
                if approval_id:
                    await harness.manager.resolve_approval(
                        approval_id,
                        bool(message.get("approved")),
                        str(message.get("reason") or ""),
                        "ws",
                    )
            elif message_type == "confirm":
                session_id = message.get("session_id")
                call_id = message.get("call_id")
                if session_id and call_id:
                    await harness.manager.resolve_by_call(
                        session_id, call_id, bool(message.get("ok", True)), "ws"
                    )
            elif message_type == "replay":
                session_id = message.get("session_id")
                if session_id:
                    events = await bus.replay(session_id, int(message.get("after_id") or 0))
                    for event in events:
                        bus.send_frame(
                            ws,
                            json.dumps(
                                {
                                    "session_id": session_id,
                                    "event": event["type"],
                                    "payload": event.get("payload") or {},
                                    "time": event.get("created_at"),
                                    "id": event.get("id"),
                                    "replay": True,
                                },
                                ensure_ascii=False,
                                default=str,
                            ),
                        )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await bus.unregister_client(ws)
