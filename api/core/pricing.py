from __future__ import annotations

import json
import os
from typing import Any

# USD per 1M tokens: (input, cached_input, output).
# DeepSeek flash rates are derived from the provider's own billing records so
# the estimate matches the real invoice rather than a list price.
_DEFAULT_PRICES: dict[str, tuple[float, float, float]] = {
    "deepseek/deepseek-flash": (0.15, 0.003, 0.60),
}


def _load_prices() -> dict[str, tuple[float, float, float]]:
    prices = dict(_DEFAULT_PRICES)
    raw = os.getenv("HAOYUAN_PRICING", "").strip()
    if raw:
        try:
            custom = json.loads(raw)
        except (ValueError, TypeError):
            custom = {}
        if isinstance(custom, dict):
            for key, value in custom.items():
                if isinstance(value, (list, tuple)) and len(value) == 3:
                    try:
                        prices[str(key).lower()] = (float(value[0]), float(value[1]), float(value[2]))
                    except (TypeError, ValueError):
                        continue
    return prices


def price_for(provider: str, model: str) -> tuple[float, float, float] | None:
    key = f"{provider}/{model}".lower()
    prices = _load_prices()
    return prices.get(key)


def estimate_cost(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """Return estimated USD cost for one call, or 0 when the model has no price.

    ``prompt_tokens`` includes cached tokens; only the uncached remainder is
    billed at the full input rate. ``completion_tokens`` already includes any
    reasoning tokens, so reasoning is not charged twice.
    """
    price = price_for(provider, model)
    if not price:
        return 0.0
    prompt = max(0, int(prompt_tokens or 0))
    cached = min(prompt, max(0, int(cached_tokens or 0)))
    completion = max(0, int(completion_tokens or 0))
    input_price, cached_price, output_price = price
    cost = (
        (prompt - cached) * input_price / 1_000_000
        + cached * cached_price / 1_000_000
        + completion * output_price / 1_000_000
    )
    return round(cost, 8)


def describe_prices() -> dict[str, Any]:
    return {key: {"input": value[0], "cached": value[1], "output": value[2]} for key, value in _load_prices().items()}
