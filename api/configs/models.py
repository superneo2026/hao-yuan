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

PRICES_PER_MTOK = {
    "deepseek": {"prompt": 2.0, "completion": 8.0},
    "zhipu": {"prompt": 0.0, "completion": 0.0},
    "mimo": {"prompt": 2.0, "completion": 8.0},
    "mock": {"prompt": 0.0, "completion": 0.0},
}


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
