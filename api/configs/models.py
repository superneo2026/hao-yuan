from __future__ import annotations

import os
from dataclasses import dataclass, field

from configs.secrets import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    MIMO_API_KEY,
    MIMO_BASE_URL,
    MIMO_MODEL,
    ZHIPU_API_KEY,
    ZHIPU_BASE_URL,
)


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    models: list[str]
    default_model: str
    api_key: str = ""
    thinking_models: set[str] = field(default_factory=set)
    tiers: dict[str, str] = field(default_factory=dict)
    max_output_tokens: int = 8192
    supports_thinking: bool = True


PROVIDERS: dict[str, ProviderConfig] = {
    "mock": ProviderConfig(
        name="mock",
        base_url="",
        models=["mock-deterministic"],
        default_model="mock-deterministic",
        api_key="",
        tiers={"lite": "mock-deterministic", "standard": "mock-deterministic", "pro": "mock-deterministic"},
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        base_url=DEEPSEEK_BASE_URL,
        models=[DEEPSEEK_MODEL, "deepseek-v4-pro"],
        default_model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        thinking_models={DEEPSEEK_MODEL},
        tiers={"lite": DEEPSEEK_MODEL, "standard": DEEPSEEK_MODEL, "pro": "deepseek-v4-pro"},
    ),
    "zhipu": ProviderConfig(
        name="zhipu",
        base_url=ZHIPU_BASE_URL,
        models=["glm-5.3-flash", "glm-5.3"],
        default_model="glm-5.3-flash",
        api_key=ZHIPU_API_KEY,
        tiers={"lite": "glm-5.3-flash", "standard": "glm-5.3-flash", "pro": "glm-5.3"},
    ),
    "mimo": ProviderConfig(
        name="mimo",
        base_url=MIMO_BASE_URL,
        models=[MIMO_MODEL],
        default_model=MIMO_MODEL,
        api_key=MIMO_API_KEY,
        max_output_tokens=16384,
        supports_thinking=False,
        tiers={"lite": MIMO_MODEL, "standard": MIMO_MODEL, "pro": MIMO_MODEL},
    ),
}

THINKING_OFF_PROVIDERS = {"zhipu"}

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


def price_for(provider: str, model: str | None = None) -> dict[str, float]:
    if model and model in PRICES_PER_MTOK:
        return PRICES_PER_MTOK[model]
    return PROVIDER_FALLBACK_PRICES.get(provider, {"prompt": 0.0, "completion": 0.0})


def auto_default() -> tuple[str, str]:
    if os.getenv("HAOYUAN_FORCE_MOCK", "").strip().lower() in {"1", "true", "yes"}:
        return "mock", "mock-deterministic"
    if DEEPSEEK_API_KEY:
        return "deepseek", DEEPSEEK_MODEL
    if ZHIPU_API_KEY:
        return "zhipu", "glm-5.3-flash"
    return "mock", "mock-deterministic"


def resolve(provider: str | None, model: str | None) -> tuple[str, str]:
    provider = (provider or "").strip()
    model = (model or "").strip()
    if model and model != "auto":
        for name, conf in PROVIDERS.items():
            if model in conf.models:
                return name, model
    if provider in PROVIDERS:
        conf = PROVIDERS[provider]
        if model and model in conf.models:
            return provider, model
        return provider, conf.default_model
    return auto_default()


def list_models() -> list[dict]:
    out = []
    for name, conf in PROVIDERS.items():
        if name == "mock":
            continue
        out.append(
            {
                "provider": name,
                "models": conf.models,
                "default_model": conf.default_model,
                "configured": bool(conf.api_key),
            }
        )
    return out
