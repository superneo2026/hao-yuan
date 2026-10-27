from __future__ import annotations

import socket

from configs import runtime
from configs.runtime import port_in_use, read_runtime, resolve_free_port, update_runtime


def _bind_random_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


def test_resolve_free_port_skips_occupied(monkeypatch):
    monkeypatch.setattr(runtime, "port_in_use", lambda host, port: port in {7000, 7001})
    assert resolve_free_port("127.0.0.1", 7000) == 7002
    monkeypatch.setattr(runtime, "port_in_use", lambda host, port: False)
    assert resolve_free_port("127.0.0.1", 8030) == 8030


def test_resolve_free_port_with_real_socket():
    sock = _bind_random_listener()
    try:
        occupied = sock.getsockname()[1]
        assert port_in_use("127.0.0.1", occupied)
        chosen = resolve_free_port("127.0.0.1", occupied)
        assert chosen > occupied
        assert not port_in_use("127.0.0.1", chosen)
    finally:
        sock.close()


def test_update_runtime_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "RUNTIME_FILE", tmp_path / "runtime.json")
    update_runtime(api_port=8031)
    update_runtime(web_port=8131, api_port_config=8030)
    assert read_runtime() == {"api_port": 8031, "web_port": 8131, "api_port_config": 8030}
