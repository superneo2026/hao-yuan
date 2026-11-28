from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest

from core.plugin import PluginManager
from extensions import marketplace


def _package(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _manifest(name: str = "demo-plugin", default_enabled: bool = True) -> str:
    return json.dumps(
        {
            "name": name,
            "title": "Demo",
            "version": "1.0.0",
            "default_enabled": default_enabled,
        }
    )


class _FakeHarness:
    def __init__(self, plugins_dir, ignored_dir, db_path):
        self.plugins = PluginManager(self, plugins_dir, db_path, extra_dirs=(ignored_dir,))
        self.plugins.discover()

    def unmount_plugin_routers(self, routers):
        return None


def test_upload_endpoint_installs_package(client, tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest("upload-demo"), "plugin.py": "def register(ctx):\n    pass\n"})
    response = client.post(
        "/api/plugins/upload",
        files={"file": ("upload-demo.zip", data, "application/zip")},
    )
    body = response.json()
    assert body["code"] == 200, body
    assert body["data"]["name"] == "upload-demo"
    assert (tmp_path / "plugins" / "upload-demo" / "plugin.json").is_file()


def test_upload_endpoint_can_target_gitignored_directory(client, tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest("ignored-demo"), "plugin.py": "def register(ctx):\n    pass\n"})
    response = client.post(
        "/api/plugins/upload",
        files={"file": ("ignored-demo.zip", data, "application/zip")},
        data={"source": "gitignored"},
    )
    body = response.json()
    assert body["code"] == 200, body
    assert body["data"]["source"] == "gitignored"
    assert (tmp_path / "gitignore_plugins" / "ignored-demo" / "plugin.json").is_file()
    assert not (tmp_path / "plugins" / "ignored-demo").exists()


def test_upload_endpoint_rejects_unknown_source(client, tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest("bad-source"), "plugin.py": "def register(ctx):\n    pass\n"})
    response = client.post(
        "/api/plugins/upload",
        files={"file": ("bad-source.zip", data, "application/zip")},
        data={"source": "elsewhere"},
    )
    assert response.json()["code"] != 200


def test_extract_package_installs_valid_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest(), "plugin.py": "def register(ctx):\n    pass\n"})
    result = marketplace._extract_package(data)
    assert result["name"] == "demo-plugin"
    assert (tmp_path / "plugins" / "demo-plugin" / "plugin.json").is_file()


def test_move_plugin_source_between_directories(client, tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    ignored = tmp_path / "gitignore_plugins"
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", ignored)
    harness = _FakeHarness(plugins, ignored, tmp_path / "state.db")
    async def _fake_get_harness():
        return harness
    monkeypatch.setattr(marketplace, "get_harness", _fake_get_harness)
    source = plugins / "move-demo"
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(_manifest("move-demo", default_enabled=False), encoding="utf-8")

    response = client.post("/api/plugins/move-demo/source", json={"source": "gitignored"})
    body = response.json()
    assert body["code"] == 200, body
    assert body["data"]["source"] == "gitignored"
    assert not source.exists()
    assert (ignored / "move-demo" / "plugin.json").is_file()
    assert harness.plugins.status()[0]["source"] == "gitignored"

    response = client.post("/api/plugins/move-demo/source", json={"source": "tracked"})
    body = response.json()
    assert body["code"] == 200, body
    assert body["data"]["source"] == "tracked"
    assert (plugins / "move-demo" / "plugin.json").is_file()
    assert not (ignored / "move-demo").exists()


def test_move_plugin_source_requires_disabled_plugin(client, tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    ignored = tmp_path / "gitignore_plugins"
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", ignored)
    harness = _FakeHarness(plugins, ignored, tmp_path / "state.db")
    async def _fake_get_harness():
        return harness
    monkeypatch.setattr(marketplace, "get_harness", _fake_get_harness)
    source = plugins / "enabled-move-demo"
    source.mkdir(parents=True)
    (source / "plugin.json").write_text(_manifest("enabled-move-demo"), encoding="utf-8")
    harness.plugins.enabled["enabled-move-demo"] = True

    response = client.post("/api/plugins/enabled-move-demo/source", json={"source": "gitignored"})
    assert response.json()["code"] != 200
    assert source.is_dir()
    assert not (ignored / "enabled-move-demo").exists()


def test_upload_endpoint_rejects_name_already_in_other_directory(client, tmp_path, monkeypatch):
    plugins = tmp_path / "plugins"
    ignored = tmp_path / "gitignore_plugins"
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", ignored)
    (plugins / "duplicate-demo").mkdir(parents=True)
    (plugins / "duplicate-demo" / "plugin.json").write_text(_manifest("duplicate-demo"), encoding="utf-8")
    data = _package({"plugin.json": _manifest("duplicate-demo"), "plugin.py": "def register(ctx):\n    pass\n"})
    response = client.post(
        "/api/plugins/upload",
        files={"file": ("duplicate-demo.zip", data, "application/zip")},
        data={"source": "gitignored"},
    )
    body = response.json()
    assert body["code"] != 200
    assert "仓库插件目录" in body["message"]
    assert not (ignored / "duplicate-demo").exists()


def test_extract_package_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest(), "../escape.txt": "bad"})
    with pytest.raises(ValueError):
        marketplace._extract_package(data)
    assert not (tmp_path / "escape.txt").exists()


def test_extract_package_rejects_symlink_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin.json", _manifest())
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    with pytest.raises(ValueError):
        marketplace._extract_package(buffer.getvalue())


def test_extract_package_rejects_core_plugin_names(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    monkeypatch.setattr(marketplace, "GITIGNORE_PLUGINS_DIR", tmp_path / "gitignore_plugins")
    data = _package({"plugin.json": _manifest("coding"), "plugin.py": "def register(ctx):\n    pass\n"})
    with pytest.raises(ValueError):
        marketplace._extract_package(data)


def test_center_and_download_urls_are_restricted():
    with pytest.raises(ValueError):
        marketplace._validated_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        marketplace._validated_url("http://169.254.169.254/latest/meta-data")
    assert marketplace._same_origin("https://example.com", "https://example.com/a.zip")
    assert not marketplace._same_origin("https://example.com", "https://evil.example/a.zip")
    assert not marketplace._same_origin("https://example.com", "http://example.com/a.zip")
