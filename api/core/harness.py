from __future__ import annotations

import asyncio
from typing import Any

from configs.configs import DB_PATH, PLUGINS_DIR, SKILLS_DIR, WORKSPACE_DIR
from core.agents import AgentRegistry
from core.context import ContextManager
from core.events import EventBus
from core.gateway import ModelGateway
from core.plugin import PluginManager
from core.policy import PolicyEngine
from core.runtime import AgentRuntime
from core.session_manager import SessionManager
from core.storage import Storage
from core.tools import ToolRegistry
from harness.skills import SkillLibrary
from tools.builtin import register_builtin_tools


class Harness:
    def __init__(self):
        self.storage = Storage(DB_PATH)
        self.events = EventBus(self.storage)
        self.skills = SkillLibrary(SKILLS_DIR)
        self.tools = ToolRegistry()
        self.agents = AgentRegistry()
        self.gateway = ModelGateway()
        self.policy = PolicyEngine(self.storage)
        self.context = ContextManager(self.storage, self.gateway)
        register_builtin_tools(self.tools, source="core")
        self.plugin_routers: list[Any] = []
        self.plugin_middlewares: list[Any] = []
        self.plugin_hooks: dict[str, list] = {}
        self.plugins = PluginManager(self, PLUGINS_DIR, DB_PATH)
        self.plugins.discover()
        self.plugins.load()
        self.runtime = AgentRuntime(self)
        self.manager = SessionManager(self.storage, self.runtime)
        self.runtime.manager = self.manager
        self._booted = False

    async def boot(self) -> None:
        if self._booted:
            return
        await self.storage.init()
        self.skills.load_all()
        self.events.start()
        await self.plugins.startup()
        try:
            await self.manager.resume_interrupted()
        except Exception as exc:
            print(f"[harness] resume scan failed: {exc}")
        self._booted = True

    async def shutdown(self) -> None:
        await self.plugins.shutdown()
        for task in list(self.manager.tasks.values()):
            task.cancel()
        await self.events.stop()

    def plugin_status(self) -> list[dict[str, Any]]:
        return self.plugins.status()

    async def set_plugin_enabled(self, name: str, enabled: bool) -> None:
        await self.storage.set_plugin_state(name, enabled)
        if name in self.plugins.enabled:
            self.plugins.enabled[name] = enabled

    async def call_hook(self, name: str, *args, **kwargs) -> list[Any]:
        results = []
        for callback in self.plugin_hooks.get(name, []):
            try:
                result = callback(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    result = await result
                results.append(result)
            except Exception:
                continue
        return results


_harness: Harness | None = None
_boot_lock = asyncio.Lock()


def harness_instance() -> Harness:
    global _harness
    if _harness is None:
        _harness = Harness()
    return _harness


async def init_harness() -> Harness:
    global _harness
    async with _boot_lock:
        harness = harness_instance()
        await harness.boot()
    return harness


async def get_harness() -> Harness:
    return harness_instance()
