from __future__ import annotations

from pathlib import Path

from configs.configs import DATA_DIR


def _state_path() -> Path:
    return DATA_DIR / "remote_management.json"


def test_remote_management_key_and_approval_flow(client):
    state = _state_path()
    try:
        created = client.post("/api/remote-management/keys", json={"label": "test-key"}).json()
        assert created["code"] == 200
        key = created["data"]
        secret = key["secret"]
        assert key["connection_code"].startswith("HYR1-")
        assert key["connection_code"] != secret

        overview = client.get("/api/remote-management/overview").json()["data"]
        assert any(item["id"] == key["id"] for item in overview["keys"])

        connect = client.post(
            "/api/remote-management/public/connect",
            headers={"X-Remote-Key": secret},
            json={"manager_name": "Office HaoYuan", "manager_url": "http://office.local:8030"},
        ).json()
        assert connect["code"] == 200
        request_id = connect["data"]["request_id"]
        assert connect["data"]["status"] == "pending"

        again = client.post(
            "/api/remote-management/public/connect",
            headers={"X-Remote-Key": secret},
            json={"manager_name": "Office HaoYuan", "manager_url": "http://office.local:8030"},
        ).json()
        assert again["data"]["request_id"] == request_id

        poll = client.get(
            f"/api/remote-management/public/requests/{request_id}",
            headers={"X-Remote-Key": secret},
        ).json()["data"]
        assert poll["status"] == "pending"
        assert poll["remote_token"] == ""

        approved = client.post(f"/api/remote-management/incoming/{request_id}/approve").json()
        assert approved["code"] == 200
        assert approved["data"]["status"] == "approved"

        poll = client.get(
            f"/api/remote-management/public/requests/{request_id}",
            headers={"X-Remote-Key": secret},
        ).json()["data"]
        assert poll["status"] == "approved"
        token = poll["remote_token"]
        assert token

        revoked = client.post(f"/api/remote-management/incoming/{request_id}/revoke").json()
        assert revoked["data"]["status"] == "revoked"
        poll = client.get(
            f"/api/remote-management/public/requests/{request_id}",
            headers={"X-Remote-Key": secret},
        ).json()["data"]
        assert poll["status"] == "revoked"
        assert poll["remote_token"] == ""

        restored = client.post(f"/api/remote-management/incoming/{request_id}/restore").json()
        assert restored["data"]["status"] == "approved"

        removed = client.delete(f"/api/remote-management/incoming/{request_id}").json()
        assert removed["code"] == 200

        deleted = client.delete(f"/api/remote-management/keys/{key['id']}").json()
        assert deleted["code"] == 200
        denied = client.get(
            f"/api/remote-management/public/requests/{request_id}",
            headers={"X-Remote-Key": secret},
        )
        assert denied.json()["code"] == 404
    finally:
        if state.exists():
            state.unlink()
