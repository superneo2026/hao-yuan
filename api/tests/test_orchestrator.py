from __future__ import annotations

import subprocess
import time


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def test_orchestrator_end_to_end(client, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init").returncode == 0
    _git(repo, "config", "user.email", "haoyuan@example.com")
    _git(repo, "config", "user.name", "HaoYuan Test")
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    _git(repo, "add", ".")
    assert _git(repo, "commit", "-m", "initial").returncode == 0

    response = client.post(
        "/api/orchestrations",
        json={
            "goal": "Add a small feature with tests",
            "workspace": str(repo),
            "tasks": [
                {
                    "id": "t1",
                    "role": "backend",
                    "title": "Backend change",
                    "instruction": "Describe the backend plan and update README.",
                    "depends_on": [],
                },
                {
                    "id": "t2",
                    "role": "test",
                    "title": "Verify",
                    "instruction": "Verify the change.",
                    "depends_on": ["t1"],
                },
            ],
        },
    )
    body = response.json()
    assert body["code"] == 200, body
    oid = body["data"]["id"]
    deadline = time.time() + 20
    final = None
    while time.time() < deadline:
        detail = client.get(f"/api/orchestrations/{oid}").json()["data"]
        final = detail
        if detail["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert final is not None
    assert final["status"] == "done", final
    assert all(task["status"] == "done" for task in final["tasks"])
    assert final["metrics"]
