from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from core.contracts import ToolContext, ToolSpec


class EmbodiedState:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.heading = 0.0
        self.speed = 0
        self.moving = False
        self.estop = False
        self.last_command = "stop"
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.history: list[dict[str, Any]] = []

    def snapshot(self) -> dict[str, Any]:
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "heading": round(self.heading, 1),
            "speed": self.speed,
            "moving": self.moving,
            "estop": self.estop,
            "last_command": self.last_command,
            "updated_at": self.updated_at,
        }

    def record(self, command: str, payload: dict[str, Any]) -> None:
        self.last_command = command
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.history.append({"command": command, "payload": payload, "state": self.snapshot(), "at": self.updated_at})
        self.history = self.history[-100:]


STATE = EmbodiedState()


def robot_status(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "state": STATE.snapshot(), "recent": STATE.history[-5:]}


def robot_scan(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = {
        "front_cm": 42.0 if not STATE.moving else 28.0,
        "left_cm": 55.0,
        "right_cm": 61.0,
        "line_offset": 0.0,
        "estop": STATE.estop,
    }
    STATE.record("scan", result)
    return result


def robot_stop(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    STATE.speed = 0
    STATE.moving = False
    result = {"stopped": True, "state": STATE.snapshot()}
    STATE.record("stop", result)
    return result


def robot_estop(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    STATE.estop = True
    STATE.speed = 0
    STATE.moving = False
    result = {"estop": True, "state": STATE.snapshot()}
    STATE.record("estop", result)
    return result


def robot_reset_estop(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    STATE.estop = False
    result = {"estop": False, "state": STATE.snapshot()}
    STATE.record("reset_estop", result)
    return result


def robot_move(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if STATE.estop:
        raise RuntimeError("emergency stop is active; refusing movement")
    direction = str(args.get("direction") or "forward").lower()
    if direction not in ("forward", "backward", "left", "right"):
        raise ValueError("direction must be forward/backward/left/right")
    speed = max(0, min(int(args.get("speed") or 0), 60))
    duration = max(0, min(int(args.get("duration_ms") or 0), 5000))
    distance = speed / 100.0 * duration / 1000.0
    if direction == "forward":
        STATE.x += distance * math.cos(math.radians(STATE.heading))
        STATE.y += distance * math.sin(math.radians(STATE.heading))
    elif direction == "backward":
        STATE.x -= distance * math.cos(math.radians(STATE.heading))
        STATE.y -= distance * math.sin(math.radians(STATE.heading))
    elif direction == "left":
        STATE.heading = (STATE.heading - 15) % 360
    else:
        STATE.heading = (STATE.heading + 15) % 360
    STATE.speed = speed
    STATE.moving = True
    result = {
        "direction": direction,
        "speed": speed,
        "duration_ms": duration,
        "distance": round(distance, 3),
        "state": STATE.snapshot(),
    }
    STATE.record("move", result)
    return result


def robot_turn(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if STATE.estop:
        raise RuntimeError("emergency stop is active; refusing turn")
    degrees = float(args.get("degrees") or 0)
    speed = max(0, min(int(args.get("speed") or 0), 60))
    STATE.heading = (STATE.heading + degrees) % 360
    STATE.speed = speed
    result = {"degrees": degrees, "speed": speed, "heading": STATE.heading}
    STATE.record("turn", result)
    return result


def robot_goto(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    if STATE.estop:
        raise RuntimeError("emergency stop is active; refusing movement")
    STATE.x = float(args.get("x") or 0)
    STATE.y = float(args.get("y") or 0)
    result = {"target": {"x": STATE.x, "y": STATE.y}, "state": STATE.snapshot()}
    STATE.record("goto", result)
    return result


def register_embodied_tools(registry, source: str = "embodied") -> None:
    specs = [
        ToolSpec(
            name="robot_status",
            description="Read robot position, heading, speed, movement and emergency-stop state.",
            input_schema={"type": "object", "properties": {}},
            source=source,
        ),
        ToolSpec(
            name="robot_scan",
            description="Read front/left/right range sensors and line offset.",
            input_schema={"type": "object", "properties": {}},
            source=source,
        ),
        ToolSpec(
            name="robot_stop",
            description="Smoothly stop the robot.",
            input_schema={"type": "object", "properties": {}},
            source=source,
        ),
        ToolSpec(
            name="robot_estop",
            description="Trigger the highest-priority emergency stop.",
            input_schema={"type": "object", "properties": {}},
            source=source,
        ),
        ToolSpec(
            name="robot_reset_estop",
            description="Reset the emergency stop after the area is safe.",
            input_schema={"type": "object", "properties": {}},
            risk="medium",
            side_effect="write",
            confirm=True,
            readonly=False,
            source=source,
        ),
        ToolSpec(
            name="robot_move",
            description="Move with direction, speed and duration.",
            input_schema={
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["forward", "backward", "left", "right"]},
                    "speed": {"type": "integer", "minimum": 0, "maximum": 60},
                    "duration_ms": {"type": "integer", "minimum": 0, "maximum": 5000},
                },
                "required": ["direction", "speed", "duration_ms"],
            },
            risk="high",
            side_effect="irreversible",
            confirm=True,
            readonly=False,
            source=source,
        ),
        ToolSpec(
            name="robot_turn",
            description="Rotate in place by degrees.",
            input_schema={
                "type": "object",
                "properties": {"degrees": {"type": "number"}, "speed": {"type": "integer"}},
                "required": ["degrees", "speed"],
            },
            risk="high",
            side_effect="irreversible",
            confirm=True,
            readonly=False,
            source=source,
        ),
        ToolSpec(
            name="robot_goto",
            description="Move to an absolute coordinate.",
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
                "required": ["x", "y"],
            },
            risk="high",
            side_effect="irreversible",
            confirm=True,
            readonly=False,
            source=source,
        ),
    ]
    handlers = {
        "robot_status": robot_status,
        "robot_scan": robot_scan,
        "robot_stop": robot_stop,
        "robot_estop": robot_estop,
        "robot_reset_estop": robot_reset_estop,
        "robot_move": robot_move,
        "robot_turn": robot_turn,
        "robot_goto": robot_goto,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.name])
