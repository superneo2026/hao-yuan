from __future__ import annotations

import importlib
import json

import pytest

from configs import secrets as secrets_mod


def _reload():
    return importlib.reload(secrets_mod)


@pytest.fixture(autouse=True)
def _restore_module(monkeypatch):
    yield
    monkeypatch.delenv("HAOYUAN_CONFIG", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    _reload()


def test_global_config_file_priority(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps({"DEEPSEEK_API_KEY": "sk-global-123", "DEEPSEEK_MODEL": "deepseek-flash"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("HAOYUAN_CONFIG", str(cfg_file))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mod = _reload()
    assert mod.DEEPSEEK_API_KEY == "sk-global-123"
    assert mod.secret_source("DEEPSEEK_API_KEY") == str(cfg_file)


def test_env_overrides_global_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"DEEPSEEK_API_KEY": "sk-global"}), encoding="utf-8")
    monkeypatch.setenv("HAOYUAN_CONFIG", str(cfg_file))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    mod = _reload()
    assert mod.DEEPSEEK_API_KEY == "sk-env"
    assert mod.secret_source("DEEPSEEK_API_KEY") == "env"


def test_invalid_global_config_ignored(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"DEEPSEEK_API_KEY": "sk-should-not-apply"', encoding="utf-8")
    monkeypatch.setenv("HAOYUAN_CONFIG", str(cfg_file))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mod = _reload()
    assert mod.DEEPSEEK_API_KEY != "sk-should-not-apply"
    assert mod.secret_source("DEEPSEEK_API_KEY") != str(cfg_file)


def test_local_file_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("HAOYUAN_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mod = _reload()
    assert mod.DEEPSEEK_API_KEY != "sk-from-nowhere"
    assert mod.secret_source("DEEPSEEK_API_KEY") in {"configs/secrets_local.py", "default"}


def test_auto_default_from_global_config(tmp_path, monkeypatch):
    import importlib

    from configs import models as models_mod

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"PROVIDER": "zhipu"}), encoding="utf-8")
    monkeypatch.setenv("HAOYUAN_CONFIG", str(cfg_file))
    monkeypatch.delenv("HAOYUAN_FORCE_MOCK", raising=False)
    _reload()
    models = importlib.reload(models_mod)
    assert models.auto_default() == ("zhipu", "glm-5.3-flash")

    cfg_file.write_text(json.dumps({"MODEL": "deepseek-v4-pro"}), encoding="utf-8")
    _reload()
    models = importlib.reload(models_mod)
    assert models.auto_default() == ("deepseek", "deepseek-v4-pro")

    monkeypatch.delenv("HAOYUAN_CONFIG")
    _reload()
    importlib.reload(models_mod)
