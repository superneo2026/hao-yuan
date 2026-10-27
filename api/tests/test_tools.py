from __future__ import annotations

import asyncio
import json
import os

import pytest

from core.contracts import ToolCall, ToolContext
from core.harness import harness_instance
from harness import repair, repoindex
from harness.sandbox import SafeWorkspace, WorkspaceError
from tools import dev
from tools import plan as plan_tools


def ctx_for(workspace, session=None):
    harness = harness_instance()
    session = session or {"id": "test_session", "workspace": str(workspace)}
    return ToolContext(runtime=harness.runtime, session=session, workspace=str(workspace))


def test_sandbox_blocks_traversal(tmp_path):
    workspace = SafeWorkspace(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    assert workspace.read_text("a.txt") == "hello"
    with pytest.raises(WorkspaceError):
        workspace.resolve("../outside.txt")
    with pytest.raises(WorkspaceError):
        workspace.resolve(str(tmp_path.parent / "absolute.txt"))


def test_read_write_edit_patch_multi(tmp_path):
    context = ctx_for(tmp_path)
    assert "created" in dev.write_file(context, {"path": "src/app.py", "content": "def add(a, b):\n    return a + b\n"})
    assert "return a + b" in dev.read_file(context, {"path": "src/app.py"})
    dev.edit_file(context, {"path": "src/app.py", "old": "a + b", "new": "a + b + 1"})
    assert "a + b + 1" in (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    patch = """@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b + 1
+    return a + b + 42
"""
    dev.apply_patch(context, {"path": "src/app.py", "patch": patch})
    assert "a + b + 42" in (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    dev.multi_edit(
        context,
        {
            "edits": [
                {"path": "src/app.py", "old": "def add", "new": "def sum2"},
                {"path": "other.txt", "old": "x", "new": "y"},
            ]
        },
    )
    assert "def sum2" in (tmp_path / "src" / "app.py").read_text(encoding="utf-8")
    assert (tmp_path / "other.txt").read_text(encoding="utf-8") == "y"


def test_glob_grep_symbols_and_scan(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "core.py").write_text(
        "import os\n\nclass Engine:\n    def run(self, value):\n        return value * 2\n\ndef helper(x):\n    return x + 1\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
    context = ctx_for(tmp_path)
    assert "pkg/core.py" in dev.glob_files(context, {"pattern": "**/*.py"})
    assert "Engine" in dev.grep_search(context, {"pattern": "class Engine", "content": True})
    assert "Engine.run" in dev.search_symbol(context, {"name": "run"})
    scan = dev.project_scan(context, {})
    assert "Node" in scan and "npm run test" in scan
    listing = dev.list_dir(context, {"path": "pkg"})
    assert "core.py" in listing


def test_run_shell_blocks_catastrophic_commands(tmp_path):
    with pytest.raises(ValueError, match="blocked"):
        dev.run_shell(ctx_for(tmp_path), {"command": "rm -rf /"})


def test_run_shell_and_delete_move(tmp_path):
    context = ctx_for(tmp_path)
    result = dev.run_shell(context, {"command": "echo haoyuan"})
    assert "haoyuan" in result and "[exit 0]" in result
    (tmp_path / "to_delete.txt").write_text("x", encoding="utf-8")
    assert "deleted" in dev.delete_path(context, {"path": "to_delete.txt"})
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    dev.move_path(context, {"src": "a.txt", "dst": "b/c.txt"})
    assert (tmp_path / "b" / "c.txt").is_file()


def test_windows_shell_adapter_for_unix_pipes():
    if os.name != "nt":
        pytest.skip("Windows-only adapter")
    adapted = dev.normalize_shell_command("python -m pytest -q 2>&1 | tail -40")
    assert "Select-Object -Last 40" in adapted
    assert "Select-Object -First 5" in dev.normalize_shell_command("dir | head -n 5")
    assert dev.normalize_shell_command("cat README.md") == "type README.md"
    assert dev.normalize_shell_command("python -m pytest -q") == "python -m pytest -q"


def test_windows_shell_adapter_executes_tail_pipe(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows-only adapter")
    context = ctx_for(tmp_path)
    result = dev.run_shell(
        context,
        {"command": 'python -c "print(chr(10).join(map(str, range(50))))" | tail -3'},
    )
    assert "[windows shell adapter]" in result
    assert "[exit 0]" in result
    assert "49" in result


def test_repoindex_and_repair():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "sample.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("class A:\n    def method(self):\n        pass\n\ndef top():\n    pass\n")
        index = repoindex.get_index(directory, fresh=True)
        names = {symbol["name"] for symbol in index["symbols"]}
        assert "A" in names and "A.method" in names and "top" in names
        assert "sample.py:1" in repoindex.repo_map(directory)

    output = """
FAILED test_bank.py::test_withdraw - AssertionError: assert 100 == 150
________________________ test_withdraw ________________________
E   assert 100 == 150
bank.py:12: AssertionError
1 failed, 2 passed in 0.12s
"""
    parsed = repair.parse_pytest(output)
    assert parsed["summary"]["failed"] == 1
    assert parsed["failures"][0]["node"].endswith("test_withdraw")
    assert repair.failure_fingerprint(parsed["failures"])
    guidance = repair.repair_guidance(parsed["failures"], [])
    assert "test_withdraw" in guidance


def test_plan_and_storyboard_documents(client, tmp_path):
    harness = harness_instance()
    session = asyncio.run(
        harness.manager.create_session(
            kind="plan",
            title="plan test",
            provider="mock",
            model="mock-deterministic",
            workspace="",
        )
    )
    context = ToolContext(runtime=harness.runtime, session=session, workspace="")
    result = asyncio.run(
        plan_tools.plan_task(
            context,
            {"title": "Go to market", "steps": ["Research", "Design", "Launch"]},
        )
    )
    assert "3 steps" in result
    result = asyncio.run(
        plan_tools.update_plan(context, {"index": 2, "status": "done", "note": "finished"})
    )
    assert "2 -> done" in result
    document = asyncio.run(
        plan_tools.make_plan(
            context,
            {
                "title": "Market plan",
                "summary": "A concise plan",
                "kpis": [{"value": "10k", "label": "users"}],
                "sections": [{"title": "Strategy", "html": "<p>Focus on developers.</p>"}],
            },
        )
    )
    info = json.loads(document)
    assert os.path.isfile(info["path"])
    assert "<!doctype html>" in open(info["path"], encoding="utf-8").read().lower()
    story = asyncio.run(
        plan_tools.make_storyboard(
            context,
            {"title": "Launch", "theme": "developer tool", "shots": [{"scene": "Hook", "duration": "3s"}]},
        )
    )
    story_info = json.loads(story)
    assert os.path.isfile(story_info["path"])

def test_repo_map_ranks_query_files(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "pricing.py").write_text("def stack_discounts(items):\n    return items\n", encoding="utf-8")
    (tmp_path / "pkg" / "unrelated.py").write_text("def ping():\n    return 1\n", encoding="utf-8")
    text = repoindex.repo_map(str(tmp_path), query="fix stack_discounts pricing")
    assert "most relevant" in text.lower()
    assert "pkg/pricing.py" in text


def test_mimo_provider_is_wired():
    from configs.models import PROVIDERS, resolve

    assert "mimo" in PROVIDERS
    assert resolve("mimo", "mimo-v2.6-flash") == ("mimo", "mimo-v2.6-flash")
    assert PROVIDERS["mimo"].supports_thinking is False
