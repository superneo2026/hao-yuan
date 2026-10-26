from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "") -> dict[str, Any]:
    return {"code": 200, "data": data, "message": message}


def fail(message: str, code: int = 500, data: Any = None) -> dict[str, Any]:
    return {"code": code, "data": data, "message": message}
