from __future__ import annotations

import json
import os
import socket
from pathlib import Path

from configs.configs import DATA_DIR

RUNTIME_FILE = Path(os.getenv("HAOYUAN_RUNTIME_FILE", DATA_DIR / "runtime.json")).expanduser().resolve()
DEFAULT_API_PORT = 8030
DEFAULT_WEB_PORT = 8130
PORT_MAX_TRIES = 100


def read_runtime() -> dict:
    try:
        return json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_runtime(**values) -> dict:
    data = read_runtime()
    data.update({key: value for key, value in values.items() if value is not None})
    try:
        RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data


def runtime_port(key: str, fallback: int) -> int:
    try:
        return int(read_runtime().get(key, fallback))
    except Exception:
        return fallback


def port_in_use(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host or "127.0.0.1", int(port)))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def resolve_free_port(host: str, base: int, tries: int = PORT_MAX_TRIES) -> int:
    port = int(base)
    for _ in range(max(1, tries)):
        if not port_in_use(host, port):
            return port
        port += 1
    raise RuntimeError(f"no free port found near {base} on {host}")
