from __future__ import annotations

import importlib.util
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from configs.configs import PLUGINS_DIR


def _load_plugin():
    path = PLUGINS_DIR / "user-account" / "plugin.py"
    spec = importlib.util.spec_from_file_location("hy_user_account_lock_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lockout_after_five_failures_and_reset(tmp_path, monkeypatch):
    module = _load_plugin()
    monkeypatch.setattr(module, "LOCK_SECONDS", 1)

    store = module.AuthStore(Path(tmp_path) / "user_account.json")
    store.ensure()
    store.setup("admin", "secret123")

    app = FastAPI()
    app.include_router(module.build_router(store))
    client = TestClient(app)

    def login(password: str) -> dict:
        return client.post("/api/auth/login", json={"username": "admin", "password": password}).json()

    for _ in range(5):
        assert login("wrong-password")["code"] == 401

    blocked = login("wrong-password")
    assert blocked["code"] == 429
    assert blocked["data"]["locked"] is True
    assert blocked["data"]["retry_after"] >= 1

    time.sleep(1.2)

    assert login("wrong-password")["code"] == 401
    for _ in range(4):
        assert login("wrong-password")["code"] == 401
    assert login("wrong-password")["code"] == 429
