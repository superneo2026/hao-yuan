from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

from adapters.providers.deepseek import DeepSeekProvider
from adapters.providers.mock import MockProvider
from configs.models import PROVIDERS, ProviderConfig


class ModelGateway:
    def __init__(self):
        self.providers = {
            "mock": MockProvider(),
            "deepseek": DeepSeekProvider(),
            "zhipu": DeepSeekProvider(),
        }

    def candidates(self, provider: str, model: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        conf = PROVIDERS.get(provider)
        if conf:
            out.append((provider, model or conf.default_model))
            for candidate in conf.models:
                item = (provider, candidate)
                if item not in out:
                    out.append(item)
        for name, other in PROVIDERS.items():
            if name == provider:
                continue
            if name == "mock":
                continue
            if other.api_key:
                item = (name, other.default_model)
                if item not in out:
                    out.append(item)
        if provider != "mock":
            out.append(("mock", "mock-deterministic"))
        if not out:
            out.append(("mock", "mock-deterministic"))
        return out

    async def stream(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: str = "",
    ) -> AsyncGenerator[dict[str, Any], None]:
        last_error: Exception | None = None
        fallbacks: list[str] = []
        for prov, mdl in self.candidates(provider, model):
            conf = PROVIDERS.get(prov)
            if not conf:
                continue
            handler = self.providers.get(prov)
            if handler is None:
                continue
            produced = False
            try:
                async for event in handler.stream(messages, tools or [], conf, mdl, thinking):
                    if event.get("type") in ("delta", "reasoning") and event.get("text"):
                        produced = True
                    if event.get("type") == "message":
                        event["fallbacks"] = fallbacks
                        event["provider"] = prov
                        event["model"] = mdl
                    yield event
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                if produced:
                    raise RuntimeError(f"model stream interrupted after partial output: {exc}") from exc
                fallbacks.append(f"{prov}/{mdl}")
                await asyncio.sleep(0.2)
                continue
        if last_error:
            raise RuntimeError(f"model call failed after fallbacks: {last_error}") from last_error
        raise RuntimeError("model call failed: no available provider")

    async def complete_text(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, Any]],
        thinking: str = "off",
    ) -> str:
        parts: list[str] = []
        async for event in self.stream(provider, model, messages, tools=None, thinking=thinking):
            if event.get("type") == "delta":
                parts.append(str(event.get("text") or ""))
            elif event.get("type") == "message" and not parts:
                content = event.get("message", {}).get("content") or ""
                if content:
                    parts.append(str(content))
        return "".join(parts).strip()

    @staticmethod
    def profile(provider: str, model: str) -> ProviderConfig:
        conf = PROVIDERS.get(provider) or PROVIDERS["mock"]
        if model:
            return ProviderConfig(
                name=conf.name,
                base_url=conf.base_url,
                models=conf.models,
                default_model=model,
                api_key=conf.api_key,
                thinking_models=conf.thinking_models,
                tiers=conf.tiers,
            )
        return conf
