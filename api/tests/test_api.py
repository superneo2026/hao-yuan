from __future__ import annotations

import time


def wait_status(client, session_id, statuses=("done", "error"), timeout=8.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200
        session = response.json()["data"]["session"]
        last = session
        if session["status"] in statuses:
            return session
        time.sleep(0.08)
    raise AssertionError(f"session did not reach {statuses}: {last}")


def test_health_and_plugins(client):
    health = client.get("/api/health").json()["data"]
    assert health["status"] == "ok"
    assert health["tools"] >= 24
    names = {plugin["name"]: plugin for plugin in health["plugins"]}
    assert {"coding", "plans", "video", "supervisor", "orchestrator"} <= set(names)
    assert names["coding"]["loaded"] is True
    assert names["embodied"]["enabled"] is False
    assert client.get("/api/models").json()["data"]["providers"]
    assert client.get("/api/skills").json()["data"]
    assert client.get("/api/approvals").json()["data"] == []


def test_general_chat_mock(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": "smoke"}).json()["data"]
    response = client.post(f"/api/sessions/{session['id']}/messages", json={"content": "hello"})
    assert response.status_code == 200
    final = wait_status(client, session["id"])
    assert final["status"] == "done"
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()["data"]
    assert messages[0]["role"] == "user"
    assert any(message["role"] == "assistant" for message in messages)
    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    types = {event["type"] for event in events}
    assert "session.status" in types and "done" in types and "message.saved" in types
    detail = client.get(f"/api/sessions/{session['id']}").json()["data"]["session"]
    assert detail["last_event_id"] > 0
    stream = client.get(f"/api/sessions/{session['id']}/stream", params={"after_id": 0})
    assert stream.status_code == 200
    assert '"type": "stream.end"' in stream.text
    assert '"type": "delta"' in stream.text or '"type": "message.saved"' in stream.text


def test_first_message_auto_titles_session(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": ""}).json()["data"]
    assert session["title"] == "New conversation"
    client.post(
        f"/api/sessions/{session['id']}/messages",
        json={"content": "帮我修复登录 bug", "locale": "zh-CN"},
    )
    final = wait_status(client, session["id"])
    assert final["status"] == "done"
    title = final["title"]
    for _ in range(30):
        if title not in ("New conversation", ""):
            break
        time.sleep(0.1)
        title = client.get(f"/api/sessions/{session['id']}").json()["data"]["session"]["title"]
    assert "修复登录" in title, title


def test_greeting_does_not_start_workspace_task(client, tmp_path):
    workspace = tmp_path / "greet"
    workspace.mkdir()
    session = client.post(
        "/api/sessions",
        json={"kind": "coding", "title": "greeting", "workspace": str(workspace)},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "你好吗"})
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    types = [event["type"] for event in events]
    assert "write.nudge" not in types
    assert "tool.start" not in types
    route = next(event for event in events if event["type"] == "route")
    assert route["payload"]["qa"] is True
    assert route["payload"]["casual"] is True
    assert route["payload"]["agent"] == "general"


def test_casual_chat_uses_general_agent(client, tmp_path):
    workspace = tmp_path / "casual"
    workspace.mkdir()
    session = client.post(
        "/api/sessions",
        json={"kind": "coding", "title": "casual", "workspace": str(workspace)},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "今天天气不错"})
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    types = [event["type"] for event in events]
    assert "write.nudge" not in types
    assert "tool.start" not in types
    route = next(event for event in events if event["type"] == "route")
    assert route["payload"]["agent"] == "general"
    assert route["payload"]["casual"] is True


def test_vague_message_does_not_force_write(client, tmp_path):
    workspace = tmp_path / "vague"
    workspace.mkdir()
    session = client.post(
        "/api/sessions",
        json={"kind": "coding", "title": "vague", "workspace": str(workspace)},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "???"})
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    events = client.get(f"/api/sessions/{session['id']}/events").json()["data"]
    types = [event["type"] for event in events]
    assert "write.nudge" not in types
    assert "tool.start" not in types
    route = next(event for event in events if event["type"] == "route")
    assert route["payload"]["agent"] == "general"


def test_coding_write_with_auto_gate(client, tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    response = client.post(
        "/api/sessions",
        json={
            "kind": "dev",
            "title": "write file",
            "workspace": str(workspace),
            "gate_mode": "allow_all",
        },
    )
    session = response.json()["data"]
    assert session["workspace"] == str(workspace)
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "请创建一个 hello.txt 文件"})
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    assert (workspace / "hello.txt").is_file()
    tool_events = [
        event
        for event in client.get(f"/api/sessions/{session['id']}/events").json()["data"]
        if event["type"] in ("tool.start", "tool.end")
    ]
    assert any(event["payload"].get("tool") == "write_file" for event in tool_events)
    artifacts = client.get(f"/api/sessions/{session['id']}/artifacts").json()["data"]
    assert any(item["kind"] == "change" for item in artifacts)
    tree = client.get("/api/workspace/tree", params={"workspace": str(workspace)}).json()["data"]
    assert any(item["path"] == "hello.txt" for item in tree["items"])


def test_approval_flow_and_resolution(client, tmp_path):
    workspace = tmp_path / "approval"
    workspace.mkdir()
    session = client.post(
        "/api/sessions",
        json={"kind": "dev", "title": "needs approval", "workspace": str(workspace), "gate_mode": "ask"},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "请创建一个 approved.txt 文件"})
    deadline = time.time() + 8
    approval = None
    while time.time() < deadline:
        pending = client.get("/api/approvals", params={"status": "pending", "session_id": session["id"]}).json()["data"]
        if pending:
            approval = pending[0]
            break
        time.sleep(0.08)
    assert approval is not None
    assert approval["tool"] == "write_file"
    assert "hello" in approval["preview"] or "approved.txt" in approval["preview"] or approval["preview"]
    resolved = client.post(f"/api/approvals/{approval['id']}/resolve", json={"approved": True, "reason": "test"})
    assert resolved.status_code == 200
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    assert (workspace / "approved.txt").is_file()


def test_session_lifecycle_and_events(client):
    session = client.post("/api/sessions", json={"kind": "general", "title": "lifecycle"}).json()["data"]
    renamed = client.patch(f"/api/sessions/{session['id']}", json={"title": "renamed"}).json()["data"]
    assert renamed["title"] == "renamed"
    hidden = client.delete(f"/api/sessions/{session['id']}").json()["data"]
    assert hidden["hidden"] == session["id"]
    unhidden = client.post(f"/api/sessions/{session['id']}/unhide").json()["data"]
    assert unhidden["hidden"] == 0
    cleared = client.post(f"/api/sessions/{session['id']}/clear")
    assert cleared.status_code == 200
    purged = client.delete(f"/api/sessions/{session['id']}/purge")
    assert purged.status_code == 200
    missing = client.get(f"/api/sessions/{session['id']}").json()
    assert missing["code"] == 404


def test_settings_and_usage(client):
    current = client.get("/api/settings").json()["data"]
    assert "gate" in current
    assert current["theme"] == "light"
    saved = client.put("/api/settings/gate", json={"mode": "allow_list", "allow": ["write_file"]}).json()["data"]
    assert saved["mode"] == "allow_list"
    target = client.put("/api/settings/workspace", json={"workspace": ""}).json()["data"]
    assert target["workspace"] == ""
    today = client.get("/api/usage/today").json()["data"]
    assert "prompt_tokens" in today
    assert client.get("/api/usage/export.csv").status_code == 200


def test_plugin_toggle_persists(client):
    result = client.post("/api/plugins/embodied/toggle", json={"enabled": True}).json()["data"]
    assert result["enabled"] is True
    assert result["restart_required"] is True
    plugins = client.get("/api/plugins").json()["data"]
    embodied = next(item for item in plugins if item["name"] == "embodied")
    assert embodied["enabled"] is True


def test_ask_user_pauses_and_resumes_same_task(client, tmp_path):
    workspace = tmp_path / "ask-user"
    workspace.mkdir()
    session = client.post(
        "/api/sessions",
        json={"kind": "dev", "title": "interactive question", "workspace": str(workspace), "gate_mode": "ask"},
    ).json()["data"]
    client.post(f"/api/sessions/{session['id']}/messages", json={"content": "请先确认是否继续执行，只做分析"})
    deadline = time.time() + 8
    pending = None
    while time.time() < deadline:
        detail = client.get(f"/api/sessions/{session['id']}").json()["data"]["session"]
        if detail.get("pending"):
            pending = detail["pending"]
            break
        time.sleep(0.08)
    assert pending and pending.get("tool") == "ask_user", pending
    assert pending["args"]["options"] == ["继续", "停止"]
    assert client.get(f"/api/sessions/{session['id']}").json()["data"]["session"]["status"] == "waiting_input"
    resolved = client.post(
        f"/api/approvals/{pending['approval_id']}/resolve", json={"approved": True, "reason": "继续"}
    )
    assert resolved.status_code == 200
    final = wait_status(client, session["id"])
    assert final["status"] == "done", final.get("error")
    messages = client.get(f"/api/sessions/{session['id']}/messages").json()["data"]
    tool_messages = [message for message in messages if message["role"] == "tool"]
    assert any("继续" in (message.get("content") or "") for message in tool_messages)


def test_orchestrator_requires_git(client, tmp_path):
    workspace = tmp_path / "not-git"
    workspace.mkdir()
    response = client.post("/api/orchestrations", json={"goal": "build something", "workspace": str(workspace)})
    body = response.json()
    assert body["code"] == 500
    assert "git" in body["message"].lower()
