from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from configs import secrets

BUILTIN_NAMES = ("deepseek", "zhipu", "mimo")

_BASE_URL_DEFAULTS = {
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/coding/paas/v4",
    "mimo": "https://token-plan-cn.xiaomimimo.com/v1",
}

_MODEL_DEFAULTS = {
    # 第三项为默认最大输出 tokens；0 表示不指定，交给模型使用自身支持的上限。
    "deepseek": ("deepseek-flash", ["deepseek-flash", "deepseek-v4-pro"], 0, True),
    "zhipu": ("glm-5.3-flash", ["glm-5.3-flash", "glm-5.3"], 0, True),
    "mimo": ("mimo-v2.6-flash", ["mimo-v2.6-flash", "mimo-v2.6-pro"], 0, True),
}

_PRESET_LABELS = {
    "deepseek": "DeepSeek",
    "zhipu": "Zhipu GLM",
    "mimo": "Xiaomi MiMo",
    "aliyun": "Alibaba Qwen",
    "kimi": "Kimi (Moonshot)",
    "bytedance": "ByteDance Doubao",
    "openai": "OpenAI",
    "claude": "Anthropic Claude",
    "poe": "Poe",
}

_PRESET_DOCS = {
    "deepseek": "https://platform.deepseek.com/api_keys",
    "zhipu": "https://open.bigmodel.cn/usercenter/apikeys",
    "mimo": "https://platform.xiaomimimo.com/",
    "aliyun": "https://bailian.console.aliyun.com/",
    "kimi": "https://platform.moonshot.cn/console/api-keys",
    "bytedance": "https://console.volcengine.com/ark",
    "openai": "https://platform.openai.com/api-keys",
    "claude": "https://console.anthropic.com/settings/keys",
    "poe": "https://poe.com/api_key",
}

# 预设只提供接入地址与能力标记，不内置模型名，避免列表随时间过期。
# 模型列表以服务商 /models 实时读取为准（需要对应 API Key）。
_EXTRA_PRESETS = {
    "aliyun": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": [],
        "supports_thinking": True,
    },
    "kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": [],
        "supports_thinking": True,
    },
    "bytedance": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": [],
        "supports_thinking": True,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": [],
        "supports_thinking": True,
    },
    "claude": {
        "base_url": "https://api.anthropic.com/v1",
        "models": [],
        "supports_thinking": True,
    },
    "poe": {
        "base_url": "https://api.poe.com/v1",
        "models": [],
        "supports_thinking": False,
    },
}


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    models: list[str]
    default_model: str
    api_key: str = ""
    enabled_models: list[str] = field(default_factory=list)  # 空 = 全部可用
    thinking_models: set[str] = field(default_factory=set)
    tiers: dict[str, str] = field(default_factory=dict)
    max_output_tokens: int = 0  # 0 = 不指定，交给模型使用默认上限
    supports_thinking: bool = True
    builtin: bool = False
    key_source: str = "default"


# 单价表：元 / 百万 tokens。键优先按具体模型，未命中时回退到 PROVIDER_FALLBACK_PRICES。
# "prompt" = 缓存未命中输入单价；"cache_hit" = 缓存命中输入单价；"completion" = 输出单价。
# 来源（2026-11 核对）：
#   智谱 BigModel 官方：GLM-5.3-Flash 0.8/2.8（命中 0.23）、GLM-5.3 8/28（命中 2）
#   小米 MiMo 官方：MiMo-V2.6-Flash 约 1.0/2.0
#   DeepSeek 官方（美元价按 1 USD≈7.1 CNY 折算，取峰值档，谷时减半，估算偏保守）：
#     deepseek-flash 0.30/0.006/1.20 → 2.13/0.04/8.52
#     deepseek-v4-pro 1.32/0.044/3.96 → 9.37/0.31/28.12
PRICES_PER_MTOK: dict[str, dict[str, float]] = {
    "glm-5.3-flash": {"prompt": 0.8, "cache_hit": 0.23, "completion": 2.8},
    "glm-5.3": {"prompt": 8.0, "cache_hit": 2.0, "completion": 28.0},
    "mimo-v2.6-flash": {"prompt": 1.0, "completion": 2.0},
    "deepseek-flash": {"prompt": 2.13, "cache_hit": 0.04, "completion": 8.52},
    "deepseek-v4-pro": {"prompt": 9.37, "cache_hit": 0.31, "completion": 28.12},
    "mock-deterministic": {"prompt": 0.0, "completion": 0.0},
}

PROVIDER_FALLBACK_PRICES: dict[str, dict[str, float]] = {
    "zhipu": PRICES_PER_MTOK["glm-5.3-flash"],
    "mimo": PRICES_PER_MTOK["mimo-v2.6-flash"],
    "deepseek": PRICES_PER_MTOK["deepseek-flash"],
    "mock": {"prompt": 0.0, "completion": 0.0},
}

THINKING_OFF_PROVIDERS = {"zhipu"}

_LOCK = threading.RLock()
PROVIDERS: dict[str, ProviderConfig] = {}
_STAMP: tuple[int, int] | None = secrets.config_stamp()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(item).strip() for item in value.keys() if str(item).strip()]
    return [item.strip() for item in re.split(r"[,;\n]", str(value)) if item.strip()]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def effective_models(conf: ProviderConfig) -> list[str]:
    """用于聊天/新建任务/回退的模型子集；enabled_models 为空表示全部。"""
    if not conf.enabled_models:
        return list(conf.models)
    allowed = {model for model in conf.enabled_models if model in conf.models}
    selected = [model for model in conf.models if model in allowed]
    return selected or list(conf.models)


def effective_default_model(conf: ProviderConfig) -> str:
    models = effective_models(conf)
    if conf.default_model in models:
        return conf.default_model
    return models[0] if models else conf.default_model


def _truthy(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _builtin(name: str) -> ProviderConfig:
    env = name.upper()
    default_model, default_models, default_max, default_thinking = _MODEL_DEFAULTS[name]
    default_model = secrets.get_secret(f"{env}_MODEL", default_model)
    configured_models = _as_list(secrets.get_secret(f"{env}_MODELS", ""))
    base_models = configured_models or default_models
    models = _unique([default_model] + base_models)
    enabled = [model for model in _as_list(secrets.get_secret(f"{env}_ENABLED_MODELS", "")) if model in models]
    thinking = set(_as_list(secrets.get_secret(f"{env}_THINKING_MODELS", "")))
    if not thinking:
        thinking = {default_model} if name in ("deepseek", "mimo") else set()
    try:
        max_output = int(secrets.get_secret(f"{env}_MAX_OUTPUT", str(default_max)) or default_max)
    except ValueError:
        max_output = default_max
    api_key = secrets.get_secret(f"{env}_API_KEY", "")
    return ProviderConfig(
        name=name,
        base_url=secrets.get_secret(f"{env}_BASE_URL", _BASE_URL_DEFAULTS[name]).rstrip("/"),
        models=models,
        default_model=default_model,
        api_key=api_key,
        enabled_models=enabled,
        thinking_models=thinking,
        tiers={tier: default_model for tier in ("lite", "standard", "pro")} | {tier: models[-1] for tier in ("pro",)},
        max_output_tokens=max_output,
        supports_thinking=_truthy(secrets.get_secret(f"{env}_SUPPORTS_THINKING", ""), default_thinking),
        builtin=True,
        key_source=secrets.secret_source(f"{env}_API_KEY") if api_key else "default",
    )


def _apply_nested(conf: ProviderConfig, raw: dict[str, Any]) -> ProviderConfig:
    nested_key = str(raw.get("api_key") or raw.get("apiKey") or "").strip()
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    base_url = raw.get("base_url") or raw.get("baseURL") or raw.get("baseUrl") or options.get("baseURL")
    if base_url:
        conf.base_url = str(base_url).strip().rstrip("/")
    if nested_key:
        conf.api_key = nested_key
        conf.key_source = str(secrets.config_path())
    models = _as_list(raw.get("models"))
    if models:
        conf.models = models
    default_model = str(raw.get("default_model") or raw.get("defaultModel") or raw.get("model") or "").strip()
    if default_model:
        conf.default_model = default_model
    if conf.default_model and conf.default_model not in conf.models:
        conf.models = _unique([conf.default_model] + conf.models)
    if not conf.models:
        conf.models = [conf.default_model or conf.name]
        conf.default_model = conf.default_model or conf.models[0]
    if not conf.default_model:
        conf.default_model = conf.models[0]
    if "enabled_models" in raw or "enabledModels" in raw:
        enabled = _as_list(raw.get("enabled_models", raw.get("enabledModels")))
        conf.enabled_models = [model for model in enabled if model in conf.models]
    thinking = _as_list(raw.get("thinking_models") or raw.get("thinkingModels"))
    if thinking:
        conf.thinking_models = set(thinking)
    if "supports_thinking" in raw or "supportsThinking" in raw:
        conf.supports_thinking = _truthy(
            raw.get("supports_thinking", raw.get("supportsThinking")), conf.supports_thinking
        )
    if "max_output_tokens" in raw or "maxOutputTokens" in raw:
        max_output = raw.get("max_output_tokens", raw.get("maxOutputTokens"))
        if max_output not in (None, ""):
            try:
                conf.max_output_tokens = max(0, int(max_output))
            except (TypeError, ValueError):
                pass
    tiers = raw.get("tiers")
    if isinstance(tiers, dict) and tiers:
        conf.tiers = {str(key): str(value) for key, value in tiers.items()}
    return conf


def _build() -> dict[str, ProviderConfig]:
    providers: dict[str, ProviderConfig] = {
        "mock": ProviderConfig(
            name="mock",
            base_url="",
            models=["mock-deterministic"],
            default_model="mock-deterministic",
            api_key="",
            tiers={"lite": "mock-deterministic", "standard": "mock-deterministic", "pro": "mock-deterministic"},
            builtin=True,
            key_source="builtin",
        )
    }
    for name in BUILTIN_NAMES:
        providers[name] = _builtin(name)

    nested = secrets.global_config_snapshot().get("providers")
    if isinstance(nested, dict):
        for raw_name, raw in nested.items():
            name = str(raw_name).strip()
            if not name or name == "mock" or not isinstance(raw, dict):
                continue
            if name in providers:
                providers[name] = _apply_nested(providers[name], raw)
                continue
            conf = ProviderConfig(
                name=name,
                base_url="",
                models=[],
                default_model="",
                api_key="",
                builtin=False,
                key_source="default",
                tiers={},
            )
            providers[name] = _apply_nested(conf, raw)
            if not providers[name].tiers:
                default = providers[name].default_model
                providers[name].tiers = {tier: default for tier in ("lite", "standard", "pro")}
    return providers


def reload_providers() -> dict[str, ProviderConfig]:
    """原地更新 PROVIDERS，保证其它模块已导入的引用同步生效。"""
    global _STAMP
    with _LOCK:
        fresh = _build()
        PROVIDERS.clear()
        PROVIDERS.update(fresh)
        _STAMP = secrets.config_stamp()
    return PROVIDERS


def _ensure_fresh() -> None:
    global _STAMP
    stamp = secrets.config_stamp()
    if stamp != _STAMP:
        reload_providers()


def get_providers() -> dict[str, ProviderConfig]:
    _ensure_fresh()
    return PROVIDERS


def configured_providers() -> list[str]:
    return [name for name, conf in get_providers().items() if name != "mock" and conf.api_key]


def price_for(provider: str, model: str | None = None) -> dict[str, float]:
    if model and model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    return PROVIDER_FALLBACK_PRICES.get(provider, {"prompt": 0.0, "completion": 0.0})


def _split_model(model: str) -> tuple[str, str]:
    text = (model or "").strip()
    if "/" in text:
        provider, rest = text.split("/", 1)
        if provider.strip() in get_providers() and rest.strip():
            return provider.strip(), rest.strip()
    return "", text


def auto_default() -> tuple[str, str]:
    if os.getenv("HAOYUAN_FORCE_MOCK", "").strip().lower() in {"1", "true", "yes"}:
        return "mock", "mock-deterministic"
    providers = get_providers()
    gp = secrets.global_config("PROVIDER").strip()
    gm = secrets.global_config("MODEL").strip()
    split_provider, split_model = _split_model(gm)
    if split_provider:
        gp, gm = split_provider, split_model

    if gp and gp != "auto" and gp in providers:
        conf = providers[gp]
        models = effective_models(conf)
        if gm and gm != "auto" and gm in models:
            return gp, gm
        return gp, effective_default_model(conf)
    if gm and gm != "auto":
        for name, conf in providers.items():
            if gm in effective_models(conf):
                return name, gm
    # 自动选择只依据用户真正配置过密钥的渠道，不再硬编码内置模型厂商。
    for name, conf in providers.items():
        if name != "mock" and conf.api_key:
            return name, effective_default_model(conf)
    return "mock", "mock-deterministic"


def resolve(provider: str | None, model: str | None) -> tuple[str, str]:
    providers = get_providers()
    provider = (provider or "").strip()
    model = (model or "").strip()
    split_provider, split_model = _split_model(model)
    if split_provider:
        provider, model = split_provider, split_model
    # 显式渠道优先：同一模型名可能同时存在于多个平台（如多个渠道都部署了同一开源模型）。
    if provider in providers:
        conf = providers[provider]
        if model and model in effective_models(conf):
            return provider, model
        return provider, effective_default_model(conf)
    if model and model != "auto":
        for name, conf in providers.items():
            if model in effective_models(conf):
                return name, model
    return auto_default()


def list_models() -> list[dict]:
    out = []
    for name, conf in get_providers().items():
        if name == "mock":
            continue
        out.append(
            {
                "provider": name,
                "models": effective_models(conf),
                "default_model": effective_default_model(conf),
                "configured": bool(conf.api_key),
                "base_url": conf.base_url,
                "builtin": conf.builtin,
                "key_source": conf.key_source,
                "supports_thinking": conf.supports_thinking,
            }
        )
    return out


def provider_presets() -> list[dict]:
    """返回新增渠道时可选的起始模板目录。"""
    out: list[dict] = []
    for name in BUILTIN_NAMES:
        default_model, models, _, supports_thinking = _MODEL_DEFAULTS[name]
        out.append(
            {
                "name": name,
                "label": _PRESET_LABELS.get(name, name),
                "base_url": _BASE_URL_DEFAULTS[name],
                "models": list(models),
                "default_model": default_model,
                "supports_thinking": supports_thinking,
                "builtin": True,
                "docs": _PRESET_DOCS.get(name, ""),
            }
        )
    for name, spec in _EXTRA_PRESETS.items():
        models = list(spec["models"])
        out.append(
            {
                "name": name,
                "label": _PRESET_LABELS.get(name, name),
                "base_url": spec["base_url"],
                "models": models,
                "default_model": models[0] if models else "",
                "supports_thinking": bool(spec.get("supports_thinking", True)),
                "builtin": False,
                "docs": _PRESET_DOCS.get(name, ""),
            }
        )
    return out


_RAW_SECRET_RE = re.compile(r"(API_?KEY|SECRET|TOKEN)$", re.IGNORECASE)


def _mask_nested_secrets(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {item_key: _mask_nested_secrets(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_mask_nested_secrets(item, key) for item in value]
    if isinstance(value, str) and value and _RAW_SECRET_RE.search(key):
        return secrets.mask_secret(value)
    return value


def raw_config_view() -> dict:
    """展示配置原文（密钥脱敏），方便用户直接在网页查看或编辑文件。"""
    data = secrets.global_config_snapshot()
    masked = _mask_nested_secrets(data)
    return {
        "path": str(secrets.config_path()),
        "text": json.dumps(masked, ensure_ascii=False, indent=2) + "\n",
        "masked": True,
    }


def describe_config() -> dict:
    providers = get_providers()
    project_default = auto_default()
    items = []
    for name, conf in providers.items():
        if name == "mock":
            continue
        items.append(
            {
                "name": name,
                "builtin": conf.builtin,
                "base_url": conf.base_url,
                "models": conf.models,
                "enabled_models": effective_models(conf),
                "default_model": conf.default_model,
                "has_key": bool(conf.api_key),
                "api_key": secrets.mask_secret(conf.api_key),
                "key_source": conf.key_source,
                "supports_thinking": conf.supports_thinking,
                "thinking_models": sorted(conf.thinking_models),
                "max_output_tokens": conf.max_output_tokens,
                "tiers": conf.tiers,
            }
        )
    return {
        "path": str(secrets.config_path()),
        "default_provider": project_default[0],
        "default_model": project_default[1],
        "providers": items,
        "presets": provider_presets(),
    }


def _normalize_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(item.get("name") or item.get("id") or "").strip(),
        "base_url": str(item.get("base_url") or item.get("baseURL") or "").strip().rstrip("/"),
        "api_key": str(item.get("api_key") or item.get("apiKey") or "").strip(),
        "clear_key": bool(item.get("clear_key") or item.get("clearKey")),
        "models": _as_list(item.get("models")),
        "enabled_models": (
            _as_list(item.get("enabled_models", item.get("enabledModels")))
            if item.get("enabled_models") is not None or item.get("enabledModels") is not None
            else None
        ),
        "default_model": str(item.get("default_model") or item.get("defaultModel") or "").strip(),
        "supports_thinking": _truthy(
            item.get("supports_thinking", item.get("supportsThinking")), True
        ),
        "thinking_models": _as_list(item.get("thinking_models") or item.get("thinkingModels")),
        "max_output_tokens": item.get("max_output_tokens", item.get("maxOutputTokens")),
        "tiers": item.get("tiers") if isinstance(item.get("tiers"), dict) else {},
    }


def update_config(
    providers_payload: list[dict[str, Any]],
    removed: list[str] | None = None,
    default_provider: str | None = None,
    default_model: str | None = None,
) -> dict:
    """把网页设置写回 ~/.config/haoyuan/config.json，并保留未知字段。

    内置渠道使用扁平字段（DEEPSEEK_* / ZHIPU_* / MIMO_*），自定义渠道写入 providers 对象。
    """
    data = secrets.global_config_snapshot()
    nested = data.get("providers")
    nested = dict(nested) if isinstance(nested, dict) else {}
    known = set(BUILTIN_NAMES) | set(nested.keys())

    for name in removed or []:
        clean = str(name).strip()
        if not clean or clean in BUILTIN_NAMES:
            continue
        nested.pop(clean, None)
        known.discard(clean)

    for raw in providers_payload or []:
        item = _normalize_payload(raw)
        name = item["name"]
        if not name or name == "mock":
            continue
        if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
            raise ValueError(f"invalid provider name: {name}")
        models = _unique(item["models"])
        default_model_name = item["default_model"] or (models[0] if models else "")
        if default_model_name and default_model_name not in models:
            models.insert(0, default_model_name)
        if not models and name in _MODEL_DEFAULTS:
            models = list(_MODEL_DEFAULTS[name][1])
            default_model_name = default_model_name or _MODEL_DEFAULTS[name][0]
        if not models:
            raise ValueError(f"provider {name} needs at least one model")
        default_model_name = default_model_name or models[0]
        enabled_models = None
        if item["enabled_models"] is not None:
            raw_enabled = _unique(item["enabled_models"])
            enabled_models = [model for model in raw_enabled if model in models]
            if raw_enabled and not enabled_models:
                enabled_models = [default_model_name]
            if enabled_models and default_model_name not in enabled_models:
                default_model_name = enabled_models[0]
        if name not in BUILTIN_NAMES and not item["base_url"]:
            raise ValueError(f"provider {name} needs a base_url")

        if name in BUILTIN_NAMES:
            env = name.upper()
            if item["base_url"]:
                data[f"{env}_BASE_URL"] = item["base_url"]
            if item["clear_key"]:
                data[f"{env}_API_KEY"] = ""
            elif item["api_key"]:
                data[f"{env}_API_KEY"] = item["api_key"]
            data[f"{env}_MODEL"] = default_model_name
            data[f"{env}_MODELS"] = ",".join(models)
            if enabled_models is not None:
                data[f"{env}_ENABLED_MODELS"] = ",".join(enabled_models)
            data[f"{env}_SUPPORTS_THINKING"] = "1" if item["supports_thinking"] else "0"
            data[f"{env}_THINKING_MODELS"] = ",".join(item["thinking_models"])
            if item["max_output_tokens"] is not None:
                try:
                    data[f"{env}_MAX_OUTPUT"] = str(max(0, int(item["max_output_tokens"])))
                except (TypeError, ValueError):
                    pass
            # 内置渠道以扁平字段为准，移除可能残留的嵌套覆盖，避免两份配置不一致。
            nested.pop(name, None)
            continue

        entry = dict(nested.get(name) or {})
        if item["base_url"]:
            entry["base_url"] = item["base_url"]
        if item["clear_key"]:
            entry["api_key"] = ""
        elif item["api_key"]:
            entry["api_key"] = item["api_key"]
        entry["models"] = models
        if enabled_models is not None:
            entry["enabled_models"] = enabled_models
        entry["default_model"] = default_model_name
        entry["supports_thinking"] = item["supports_thinking"]
        entry["thinking_models"] = item["thinking_models"]
        if item["max_output_tokens"] is not None:
            try:
                entry["max_output_tokens"] = max(0, int(item["max_output_tokens"]))
            except (TypeError, ValueError):
                pass
        if item["tiers"]:
            entry["tiers"] = item["tiers"]
        nested[name] = entry
        known.add(name)

    data["providers"] = nested
    if default_provider is not None:
        data["PROVIDER"] = str(default_provider).strip()
    if default_model is not None:
        data["MODEL"] = str(default_model).strip()

    secrets.save_global_config(data)
    reload_providers()
    return describe_config()


reload_providers()
