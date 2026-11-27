from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from configs.configs import PLUGINS_DIR


def _load_plugin():
    path = PLUGINS_DIR / "user-account" / "plugin.py"
    spec = importlib.util.spec_from_file_location("hy_user_account_recovery_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(module, tmp_path: Path) -> TestClient:
    store = module.AuthStore(Path(tmp_path) / "user_account.json")
    store.ensure()
    store.setup("admin", "secret123", "admin@example.com")
    app = FastAPI()
    app.include_router(module.build_router(store))
    return TestClient(app)


def _configure_mail(module, tmp_path: Path, monkeypatch) -> dict:
    for name in ("HAOYUAN_SMTP_HOST", "HAOYUAN_SMTP_PORT", "HAOYUAN_SMTP_USER",
                 "HAOYUAN_SMTP_PASSWORD", "HAOYUAN_SMTP_FROM", "HAOYUAN_SMTP_SECURITY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module, "MAIL_PATH", Path(tmp_path) / "smtp.json")
    module._write_mail_file(
        {
            "host": "smtp.example.com",
            "port": 465,
            "username": "noreply@example.com",
            "password": "smtp-secret",
            "sender": "noreply@example.com",
            "security": "ssl",
        }
    )
    sent: dict[str, str] = {}

    def fake_send(settings, to_addr, subject, body):
        sent["to"] = to_addr
        sent["subject"] = subject
        match = re.search(r"验证码：(\d{6})", body)
        sent["code"] = match.group(1) if match else ""

    monkeypatch.setattr(module, "_send_mail", fake_send)
    return sent


def test_setup_requires_valid_email(tmp_path, monkeypatch):
    module = _load_plugin()
    app = FastAPI()
    store = module.AuthStore(Path(tmp_path) / "user_account.json")
    store.ensure()
    app.include_router(module.build_router(store))
    client = TestClient(app)

    invalid = client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "secret123", "email": "not-an-email"},
    ).json()
    assert invalid["code"] == 400

    created = client.post(
        "/api/auth/setup",
        json={"username": "admin", "password": "secret123", "email": "admin@example.com"},
    ).json()
    assert created["code"] == 200
    assert created["data"]["has_recovery_email"] is True
    assert created["data"]["recovery_email"] == "a***n@example.com"


def test_recovery_request_requires_email_service(tmp_path, monkeypatch):
    module = _load_plugin()
    monkeypatch.setattr(module, "MAIL_PATH", Path(tmp_path) / "smtp.json")
    client = _client(module, tmp_path)

    status = client.get("/api/auth/status").json()["data"]
    assert status["has_recovery_email"] is True
    assert status["email_configured"] is False
    assert status["recovery_available"] is False

    result = client.post("/api/auth/recovery/request", json={"identity": "admin"}).json()
    assert result["code"] == 400
    assert result["data"]["reason"] == "email_not_configured"


def test_full_recovery_flow(tmp_path, monkeypatch):
    module = _load_plugin()
    sent = _configure_mail(module, tmp_path, monkeypatch)
    client = _client(module, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).json()
    old_token = login["data"]["token"]

    status = client.get("/api/auth/status").json()["data"]
    assert status["email_configured"] is True
    assert status["recovery_available"] is True

    mismatch = client.post("/api/auth/recovery/request", json={"identity": "nobody"}).json()
    assert mismatch["code"] == 400
    assert mismatch["data"]["reason"] == "mismatch"

    requested = client.post("/api/auth/recovery/request", json={"identity": "admin@example.com"}).json()
    assert requested["code"] == 200
    assert requested["data"]["email"] == "a***n@example.com"
    assert sent["to"] == "admin@example.com"
    code = sent["code"]
    assert re.fullmatch(r"\d{6}", code)

    too_soon = client.post("/api/auth/recovery/request", json={"identity": "admin"}).json()
    assert too_soon["code"] == 429
    assert too_soon["data"]["retry_after"] >= 1

    wrong_code = "000000" if code != "000000" else "111111"
    wrong = client.post(
        "/api/auth/recovery/reset",
        json={"code": wrong_code, "new_password": "newsecret1"},
    ).json()
    assert wrong["code"] == 401
    assert wrong["data"]["remaining_attempts"] == 4

    reset = client.post(
        "/api/auth/recovery/reset",
        json={"code": code, "new_password": "newsecret1"},
    ).json()
    assert reset["code"] == 200
    new_token = reset["data"]["token"]
    assert new_token

    client.cookies.clear()
    old_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {old_token}"}).json()
    assert old_me["code"] == 401
    new_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}).json()
    assert new_me["code"] == 200

    old_login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).json()
    assert old_login["code"] == 401
    new_login = client.post("/api/auth/login", json={"username": "admin", "password": "newsecret1"}).json()
    assert new_login["code"] == 200


def test_change_recovery_email(tmp_path, monkeypatch):
    module = _load_plugin()
    _configure_mail(module, tmp_path, monkeypatch)
    client = _client(module, tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).json()
    headers = {"Authorization": f"Bearer {login['data']['token']}"}

    changed = client.post(
        "/api/auth/change",
        headers=headers,
        json={"current_password": "secret123", "email": "owner@example.com"},
    ).json()
    assert changed["code"] == 200
    assert changed["data"]["recovery_email"] == "o***r@example.com"

    missing_password = client.post(
        "/api/auth/change",
        headers=headers,
        json={"current_password": "wrong", "email": "other@example.com"},
    ).json()
    assert missing_password["code"] == 401


def test_mail_config_endpoints_require_auth(tmp_path, monkeypatch):
    module = _load_plugin()
    monkeypatch.setattr(module, "MAIL_PATH", Path(tmp_path) / "smtp.json")
    client = _client(module, tmp_path)

    assert client.get("/api/auth/email").json()["code"] == 401

    login = client.post("/api/auth/login", json={"username": "admin", "password": "secret123"}).json()
    headers = {"Authorization": f"Bearer {login['data']['token']}"}

    saved = client.put(
        "/api/auth/email",
        headers=headers,
        json={"host": "smtp.example.com", "port": 587, "sender": "noreply@example.com", "security": "starttls"},
    ).json()
    assert saved["code"] == 200
    assert saved["data"]["configured"] is True
    assert saved["data"]["has_password"] is False
    assert saved["data"]["security"] == "starttls"

    config = client.get("/api/auth/email", headers=headers).json()
    assert config["code"] == 200
    assert config["data"]["host"] == "smtp.example.com"
