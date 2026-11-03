from __future__ import annotations

from pathlib import Path

from configs.configs import DATA_DIR


def _state_path() -> Path:
    return DATA_DIR / "user_account.json"


def test_user_account_protection_flow(client):
    state = _state_path()
    try:
        client.cookies.clear()
        status = client.get("/api/auth/status").json()["data"]
        assert status["enabled"] is True
        assert status["configured"] is False
        assert status["active"] is False

        plugins = client.get("/api/plugins").json()["data"]
        assert any(item["name"] == "user-account" for item in plugins)

        setup = client.post("/api/auth/setup", json={"username": "tester", "password": "secret123"}).json()
        assert setup["code"] == 200
        token = setup["data"]["token"]
        assert token

        client.cookies.clear()
        blocked = client.get("/api/sessions")
        assert blocked.status_code == 401
        assert blocked.json()["code"] == 401

        headers = {"Authorization": f"Bearer {token}"}
        allowed = client.get("/api/sessions", headers=headers)
        assert allowed.status_code == 200

        changed = client.post(
            "/api/auth/change",
            headers=headers,
            json={"current_password": "secret123", "new_password": "secret456"},
        ).json()
        assert changed["code"] == 200
        new_token = changed["data"]["token"]
        assert new_token != token
        client.cookies.clear()
        assert client.get("/api/sessions", headers=headers).status_code == 401
        assert client.get("/api/sessions", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200

        client.cookies.clear()
        login = client.post("/api/auth/login", json={"username": "tester", "password": "secret456"}).json()
        assert login["code"] == 200
        bad = client.post("/api/auth/login", json={"username": "tester", "password": "wrong"})
        assert bad.json()["code"] == 401
    finally:
        client.cookies.clear()
        if state.exists():
            state.unlink()
