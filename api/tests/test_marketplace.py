from __future__ import annotations

import io
import json
import stat
import zipfile

import pytest

from extensions import marketplace


def _package(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _manifest(name: str = "demo-plugin") -> str:
    return json.dumps({"name": name, "title": "Demo", "version": "1.0.0"})


def test_upload_endpoint_installs_package(client, tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    data = _package({"plugin.json": _manifest("upload-demo"), "plugin.py": "def register(ctx):\n    pass\n"})
    response = client.post(
        "/api/plugins/upload",
        files={"file": ("upload-demo.zip", data, "application/zip")},
    )
    body = response.json()
    assert body["code"] == 200, body
    assert body["data"]["name"] == "upload-demo"
    assert (tmp_path / "plugins" / "upload-demo" / "plugin.json").is_file()


def test_extract_package_installs_valid_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    data = _package({"plugin.json": _manifest(), "plugin.py": "def register(ctx):\n    pass\n"})
    result = marketplace._extract_package(data)
    assert result["name"] == "demo-plugin"
    assert (tmp_path / "plugins" / "demo-plugin" / "plugin.json").is_file()


def test_extract_package_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
    data = _package({"plugin.json": _manifest(), "../escape.txt": "bad"})
    with pytest.raises(ValueError):
        marketplace._extract_package(data)
    assert not (tmp_path / "escape.txt").exists()


def test_extract_package_rejects_symlink_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(marketplace, "PLUGINS_DIR", tmp_path / "plugins")
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
