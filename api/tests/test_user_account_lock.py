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

    for expected in (4, 3, 2, 1):
        result = login("wrong-password")
        assert result["code"] == 401
        assert result["data"]["remaining_attempts"] == expected

    blocked = login("wrong-password")
    assert blocked["code"] == 429
    assert blocked["data"]["locked"] is True
    assert blocked["data"]["retry_after"] >= 1
    assert blocked["data"]["remaining_attempts"] == 0

    assert login("wrong-password")["code"] == 429

    time.sleep(1.2)

    reset = login("wrong-password")
    assert reset["code"] == 401
    assert reset["data"]["remaining_attempts"] == 4
    for expected in (3, 2, 1):
        result = login("wrong-password")
        assert result["code"] == 401
        assert result["data"]["remaining_attempts"] == expected
    assert login("wrong-password")["code"] == 429


def test_custom_max_failures_policy(tmp_path, monkeypatch):
    module = _load_plugin()
    monkeypatch.setattr(module, "LOCK_SECONDS", 1)

    store = module.AuthStore(Path(tmp_path) / "user_account.json")
    store.ensure()
    store.setup("admin", "secret123")

    app = FastAPI()
    app.include_router(module.build_router(store))
    client = TestClient(app)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).json()
    token = login["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    invalid = client.put("/api/auth/policy", headers=headers, json={"max_failures": 0}).json()
    assert invalid["code"] == 400

    saved = client.put("/api/auth/policy", headers=headers, json={"max_failures": 3}).json()
    assert saved["code"] == 200
    assert saved["data"]["max_failures"] == 3

    status = client.get("/api/auth/status").json()["data"]
    assert status["max_failures"] == 3

    def wrong() -> dict:
        return client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).json()

    assert wrong()["data"]["remaining_attempts"] == 2
    assert wrong()["data"]["remaining_attempts"] == 1
    locked = wrong()
    assert locked["code"] == 429
    assert locked["data"]["max_failures"] == 3
    assert locked["data"]["locked"] is True
