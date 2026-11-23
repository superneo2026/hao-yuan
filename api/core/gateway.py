from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncGenerator

from adapters.providers.deepseek import DeepSeekProvider, ProviderHTTPError
from adapters.providers.mock import MockProvider
from configs import models as models_mod
from configs.models import PROVIDERS, ProviderConfig, effective_default_model, effective_models


def strict_provider() -> bool:
    return os.getenv("HAOYUAN_STRICT_PROVIDER", "").strip().lower() in {"1", "true", "yes"}


def describe_provider_error(exc: Exception) -> str:
    """Turn raw provider failures into actionable messages for the UI."""
    if isinstance(exc, ProviderHTTPError):
        status = exc.status
        body = (exc.body or "").lower()
        if status in (401, 403):
            return f"API Key 无效或无权限（HTTP {status}）"
        if status == 404:
            return "模型不存在或当前账号未开通（HTTP 404）"
        if status == 429:
            return "请求被限流（HTTP 429），请稍后重试"
        if status == 400:
            if "thinking" in body or "reasoning" in body:
                return "模型不支持当前 thinking/reasoning 参数（HTTP 400）"
            if "tool" in body or "function" in body:
                return "模型不支持当前 tools/tool_choice 参数（HTTP 400）"
            if "image" in body or "vision" in body:
                return "模型不支持图片输入（HTTP 400）"
            return "模型拒绝了请求参数（HTTP 400）"
        if 500 <= status < 600:
            return f"模型服务端错误（HTTP {status}）"
        return f"模型调用失败（HTTP {status}）"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "模型请求超时"
    return f"模型调用失败：{type(exc).__name__}"


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

    def candidates(self, provider: str, model: str, strict: bool | None = None) -> list[tuple[str, str]]:
        models_mod.get_providers()
        strict = strict_provider() if strict is None else strict
        out: list[tuple[str, str]] = []
        conf = PROVIDERS.get(provider)
        if conf and (provider == "mock" or conf.api_key):
            for candidate in [model or effective_default_model(conf)] + effective_models(conf):
                item = (provider, candidate)
                if item not in out:
                    out.append(item)
        if strict:
            # Strict routing means: use exactly the requested provider, never
            # another provider and never mock. An empty list makes stream()
            # raise a clear error instead of silently answering from elsewhere.
            return out
        for name, other in PROVIDERS.items():
            if name in (provider, "mock") or not other.api_key:
                continue
            for candidate in effective_models(other):
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
        strict: bool | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        last_error: Exception | None = None
        fallbacks: list[str] = []
        candidates = self.candidates(provider, model, strict)
        if not candidates:
            if provider == "strict":
                raise RuntimeError(
                    "strict route: no configured provider is available. Configure a provider in Settings, "
                    "or turn off strict routing."
                )
            raise RuntimeError(
                f"strict route: provider '{provider}/{model}' is not configured or has no API key. "
                "Configure it in Settings, or turn off strict routing."
            )
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
            provider_tools = (tools or []) if conf.supports_tools else []
            attempts = 2
            for attempt in range(attempts):
                produced = False
                try:
                    async for event in handler.stream(messages, provider_tools, conf, mdl, thinking):
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
            detail = str(last_error)[:240]
            raise RuntimeError(
                f"{describe_provider_error(last_error)}（已尝试：{', '.join(fallbacks) or '无'}；{detail}）"
            ) from last_error
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
                supports_tools=conf.supports_tools,
                supports_vision=conf.supports_vision,
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
