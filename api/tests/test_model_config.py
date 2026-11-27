from __future__ import annotations

import importlib
import json
import os

import pytest

from configs import models as models_mod
from configs import secrets as secrets_mod


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("HAOYUAN_CONFIG", str(cfg))
    monkeypatch.delenv("HAOYUAN_FORCE_MOCK", raising=False)
    for name in (
        "PROVIDER",
        "MODEL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "ZHIPU_API_KEY",
        "ZHIPU_BASE_URL",
        "MIMO_API_KEY",
        "MIMO_BASE_URL",
        "MIMO_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(secrets_mod)
    importlib.reload(models_mod)
    yield cfg
    monkeypatch.delenv("HAOYUAN_CONFIG", raising=False)
    importlib.reload(secrets_mod)
    importlib.reload(models_mod)


def test_custom_provider_roundtrip_and_hot_reload(isolated_config):
    cfg = isolated_config
    view = models_mod.update_config(
        [
            {
                "name": "intranet",
                "base_url": "http://llm.intranet/v1",
                "api_key": "sk-intranet",
                "models": ["qwen-max", "qwen-plus"],
                "default_model": "qwen-plus",
                "supports_thinking": False,
                "max_output_tokens": 4096,
            }
        ],
        default_provider="intranet",
        default_model="qwen-plus",
    )
    intranet = next(item for item in view["providers"] if item["name"] == "intranet")
    assert intranet["models"] == ["qwen-max", "qwen-plus"]
    assert intranet["has_key"] is True
    assert intranet["api_key"] != "sk-intranet"
    assert models_mod.resolve(None, "qwen-max") == ("intranet", "qwen-max")
    assert models_mod.auto_default() == ("intranet", "qwen-plus")

    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["providers"]["intranet"]["default_model"] == "qwen-plus"
    assert saved["PROVIDER"] == "intranet"
    assert saved["MODEL"] == "qwen-plus"

    # Editing the file directly must be picked up without a restart.
    saved["providers"]["intranet"]["models"].append("qwen-turbo")
    cfg.write_text(json.dumps(saved), encoding="utf-8")
    stat = os.stat(cfg)
    os.utime(cfg, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert "qwen-turbo" in models_mod.get_providers()["intranet"].models


def test_custom_provider_without_max_output_uses_model_default(isolated_config):
    models_mod.update_config(
        [{"name": "relay", "base_url": "http://llm.relay/v1", "api_key": "sk-relay", "models": ["m1"]}]
    )
    assert models_mod.get_providers()["relay"].max_output_tokens == 0

    models_mod.update_config(
        [{"name": "relay", "base_url": "http://llm.relay/v1", "models": ["m1"], "max_output_tokens": 4096}]
    )
    assert models_mod.get_providers()["relay"].max_output_tokens == 4096

    models_mod.update_config(
        [{"name": "relay", "base_url": "http://llm.relay/v1", "models": ["m1"], "max_output_tokens": 0}]
    )
    assert models_mod.get_providers()["relay"].max_output_tokens == 0


def test_builtin_provider_uses_flat_keys(isolated_config):
    cfg = isolated_config
    models_mod.update_config(
        [
            {
                "name": "deepseek",
                "base_url": "https://example.invalid/v1",
                "api_key": "sk-flat",
                "models": ["deepseek-flash", "deepseek-chat"],
                "default_model": "deepseek-chat",
                "supports_thinking": True,
            }
        ]
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["DEEPSEEK_API_KEY"] == "sk-flat"
    assert saved["DEEPSEEK_MODEL"] == "deepseek-chat"
    assert saved["DEEPSEEK_MODELS"] == "deepseek-flash,deepseek-chat"
    provider = models_mod.get_providers()["deepseek"]
    assert provider.api_key == "sk-flat"
    assert provider.default_model == "deepseek-chat"
    assert provider.base_url == "https://example.invalid/v1"


def test_provider_presets_include_major_vendors(isolated_config):
    presets = {item["name"]: item for item in models_mod.describe_config()["presets"]}
    assert {"deepseek", "zhipu", "mimo", "aliyun", "kimi", "bytedance", "openai", "claude", "poe"} <= set(presets)
    for name in ("aliyun", "kimi", "bytedance", "openai", "claude", "poe"):
        preset = presets[name]
        assert preset["builtin"] is False
        assert preset["base_url"].startswith("https://")
        # 预设不内置可能过期的模型名，模型列表以 /models 实时读取为准。
        assert preset["models"] == []
    assert presets["aliyun"]["label"] == "Alibaba Qwen"


def test_raw_config_masks_secrets(isolated_config):
    cfg = isolated_config
    cfg.write_text(
        json.dumps(
            {
                "DEEPSEEK_API_KEY": "sk-abcdef123456",
                "providers": {
                    "relay": {
                        "base_url": "http://llm.relay/v1",
                        "api_key": "sk-xyz987654321",
                        "models": ["m1"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    view = models_mod.raw_config_view()
    assert "sk-abcdef123456" not in view["text"]
    assert "sk-xyz987654321" not in view["text"]
    assert "DEEPSEEK_API_KEY" in view["text"]
    assert view["masked"] is True


def test_extract_model_ids_variants():
    from extensions.system import _extract_model_ids

    assert _extract_model_ids({"data": [{"id": "b"}, {"id": "a"}]}) == ["a", "b"]
    assert _extract_model_ids({"models": [{"name": "x"}]}) == ["x"]
    assert _extract_model_ids(["x", "x", "y"]) == ["x", "y"]


def test_extract_model_ids_sorts_newest_and_filters_openai():
    from extensions.system import _extract_model_ids, _is_anthropic

    payload = {
        "data": [
            {"id": "gpt-4.1", "created": 100},
            {"id": "gpt-5", "created": 300},
            {"id": "text-embedding-3-large", "created": 200},
            {"id": "gpt-5-mini", "created": 250},
        ]
    }
    assert _extract_model_ids(payload, provider="openai") == ["gpt-5", "gpt-5-mini", "gpt-4.1"]
    assert _extract_model_ids(
        {"data": [{"id": "old", "created_at": "2025-01-01T00:00:00Z"},
                  {"id": "new", "created_at": "2026-01-01T00:00:00Z"}]},
        provider="claude",
    ) == ["new", "old"]
    assert _is_anthropic("claude", "https://api.anthropic.com/v1")
    assert _is_anthropic("any", "https://api.anthropic.com/v1")
    assert not _is_anthropic("openai", "https://api.openai.com/v1")


def test_enabled_models_subset_filters_choices(isolated_config):
    cfg = isolated_config
    models_mod.update_config(
        [
            {
                "name": "relay",
                "base_url": "http://llm.relay/v1",
                "api_key": "sk-relay",
                "models": ["a", "b", "c"],
                "default_model": "a",
                "enabled_models": ["b"],
            }
        ]
    )
    provider = models_mod.get_providers()["relay"]
    assert models_mod.effective_models(provider) == ["b"]
    assert models_mod.effective_default_model(provider) == "b"
    listed = next(item for item in models_mod.list_models() if item["provider"] == "relay")
    assert listed["models"] == ["b"]
    # 已禁用的 a 会回退到当前启用的默认模型 b
    assert models_mod.resolve("relay", "a") == ("relay", "b")

    # 传空列表表示“全部启用”
    models_mod.update_config(
        [
            {
                "name": "relay",
                "base_url": "http://llm.relay/v1",
                "models": ["a", "b", "c"],
                "default_model": "b",
                "enabled_models": [],
            }
        ]
    )
    assert models_mod.effective_models(models_mod.get_providers()["relay"]) == ["a", "b", "c"]


def test_builtin_enabled_models_uses_flat_key(isolated_config):
    cfg = isolated_config
    models_mod.update_config(
        [
            {
                "name": "deepseek",
                "models": ["deepseek-flash", "deepseek-v4-pro"],
                "default_model": "deepseek-flash",
                "enabled_models": ["deepseek-v4-pro"],
            }
        ]
    )
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert saved["DEEPSEEK_ENABLED_MODELS"] == "deepseek-v4-pro"
    provider = models_mod.get_providers()["deepseek"]
    assert models_mod.effective_models(provider) == ["deepseek-v4-pro"]
    assert models_mod.effective_default_model(provider) == "deepseek-v4-pro"


def test_resolve_prefers_explicit_provider_for_same_model_name(isolated_config):
    models_mod.update_config(
        [
            {
                "name": "p1",
                "base_url": "http://p1/v1",
                "api_key": "sk-p1",
                "models": ["shared-model", "p1-only"],
                "default_model": "p1-only",
            },
            {
                "name": "p2",
                "base_url": "http://p2/v1",
                "api_key": "sk-p2",
                "models": ["shared-model", "p2-only"],
                "default_model": "p2-only",
            },
        ]
    )
    assert models_mod.resolve("p2", "shared-model") == ("p2", "shared-model")
    assert models_mod.resolve("p1", "shared-model") == ("p1", "shared-model")
    assert models_mod.resolve(None, "shared-model")[1] == "shared-model"


def test_builtin_provider_removal_and_restore(isolated_config):
    cfg = isolated_config
    view = models_mod.update_config([], removed=["zhipu"])
    names = {item["name"] for item in view["providers"]}
    assert "zhipu" not in names
    assert "mimo" in names
    assert "zhipu" in {item["name"] for item in view["presets"]}
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert "zhipu" in saved["REMOVED_PROVIDERS"]
    assert not any(key.startswith("ZHIPU_") for key in saved)

    view = models_mod.update_config(
        [{"name": "zhipu", "models": ["glm-5.3-flash", "glm-5.3"], "default_model": "glm-5.3-flash"}]
    )
    assert "zhipu" in {item["name"] for item in view["providers"]}
    saved = json.loads(cfg.read_text(encoding="utf-8"))
    assert "zhipu" not in saved["REMOVED_PROVIDERS"]

    # deepseek 始终保留
    view = models_mod.update_config([], removed=["deepseek"])
    assert "deepseek" in {item["name"] for item in view["providers"]}


def test_custom_provider_allows_chinese_name(isolated_config):
    view = models_mod.update_config(
        [
            {
                "name": "我的渠道",
                "base_url": "http://llm.intranet/v1",
                "api_key": "sk-cn",
                "models": ["qwen-max"],
                "default_model": "qwen-max",
            }
        ]
    )
    assert "我的渠道" in {item["name"] for item in view["providers"]}
    assert models_mod.resolve("我的渠道", "qwen-max") == ("我的渠道", "qwen-max")

    with pytest.raises(ValueError):
        models_mod.update_config(
            [{"name": "bad name", "base_url": "http://x/v1", "api_key": "k", "models": ["m"]}]
        )
