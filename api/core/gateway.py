from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncGenerator

from adapters.providers.deepseek import DeepSeekProvider, ProviderHTTPError
from adapters.providers.mock import MockProvider
from configs import models as models_mod
from configs.models import PROVIDERS, ProviderConfig


def strict_provider() -> bool:
    return os.getenv("HAOYUAN_STRICT_PROVIDER", "").strip().lower() in {"1", "true", "yes"}


class ModelGateway:
    def __init__(self):
        self.providers: dict[str, Any] = {"mock": MockProvider()}
        # (provider, model) -> monotonic time until which we should not retry it.
        self._cooldown: dict[tuple[str, str], float] = {}
        # The last model that actually produced output; used to short-circuit a
        # dead primary model instead of paying its retry cost on every step.
        self._last_good: tuple[str, str] | None = None

    def _handler(self, provider: str) -> Any:
        if provider == "mock":
            return self.providers["mock"]
        handler = self.providers.get(provider)
        if handler is None:
            # All supported providers speak the OpenAI-compatible protocol.
            handler = DeepSeekProvider()
            self.providers[provider] = handler
        return handler

    def _open(self, provider: str, model: str) -> bool:
        until = self._cooldown.get((provider, model), 0.0)
        return time.monotonic() < until

    def _cool_down(self, provider: str, model: str, seconds: float) -> None:
        key = (provider, model)
        self._cooldown[key] = max(self._cooldown.get(key, 0.0), time.monotonic() + seconds)

    def _succeeded(self, provider: str, model: str) -> None:
        self._cooldown.pop((provider, model), None)
        self._last_good = (provider, model)

    def candidates(self, provider: str, model: str) -> list[tuple[str, str]]:
        models_mod.get_providers()
        out: list[tuple[str, str]] = []
        conf = PROVIDERS.get(provider)
        if conf and (provider == "mock" or conf.api_key):
            for candidate in [model or conf.default_model] + conf.models:
                item = (provider, candidate)
                if item not in out:
                    out.append(item)
        if strict_provider():
            ordered = out or [("mock", "mock-deterministic")]
        else:
            for name, other in PROVIDERS.items():
                if name in (provider, "mock") or not other.api_key:
                    continue
                for candidate in other.models:
                    item = (name, candidate)
                    if item not in out:
                        out.append(item)
            if not conf or not conf.api_key:
                out.append(("mock", "mock-deterministic"))
            if not out:
                out.append(("mock", "mock-deterministic"))
            ordered = out
        # If the requested model is currently cooling down, put the recently
        # successful model first so the next step does not re-walk dead entries.
        if self._last_good and ordered and self._open(*ordered[0]):
            key = self._last_good
            if key in ordered:
                ordered = [key] + [item for item in ordered if item != key]
        return ordered

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
        candidates = self.candidates(provider, model)
        # If every candidate is cooling down, retry the first one anyway instead of
        # failing the whole run: a transient 429 must not make the session error out.
        honor_cooldown = any(not self._open(*item) for item in candidates)
        for prov, mdl in candidates:
            conf = PROVIDERS.get(prov)
            if not conf:
                continue
            if prov != "mock" and not conf.api_key:
                continue
            if honor_cooldown and self._open(prov, mdl):
                fallbacks.append(f"{prov}/{mdl}")
                continue
            handler = self._handler(prov)
            if handler is None:
                continue
            attempts = 2
            for attempt in range(attempts):
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
                    self._succeeded(prov, mdl)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = exc
                    if produced:
                        raise RuntimeError(f"model stream interrupted after partial output: {exc}") from exc
                    if isinstance(exc, ProviderHTTPError):
                        status = exc.status
                        if status == 429:
                            delay = 20.0
                            try:
                                if exc.retry_after:
                                    delay = max(5.0, min(120.0, float(exc.retry_after)))
                            except (TypeError, ValueError):
                                pass
                            self._cool_down(prov, mdl, delay)
                            break
                        if 400 <= status < 500:
                            self._cool_down(prov, mdl, 300.0)
                            break
                        self._cool_down(prov, mdl, 20.0)
                    elif isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                        self._cool_down(prov, mdl, 15.0)
                    else:
                        self._cool_down(prov, mdl, 10.0)
                    if attempt + 1 >= attempts:
                        break
                    await asyncio.sleep(0.15)
            fallbacks.append(f"{prov}/{mdl}")
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
        models_mod.get_providers()
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
                max_output_tokens=conf.max_output_tokens,
                supports_thinking=conf.supports_thinking,
                builtin=conf.builtin,
                key_source=conf.key_source,
            )
        return conf

    async def aclose(self) -> None:
        for handler in self.providers.values():
            close = getattr(handler, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass
