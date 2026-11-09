from __future__ import annotations

import asyncio
from typing import Any

from configs.configs import DB_PATH, GITIGNORE_PLUGINS_DIR, PLUGINS_DIR, SKILLS_DIR, WORKSPACE_DIR
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
from harness.supervisor import watch_loop as supervisor_watch_loop
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
        self.app: Any = None
        self.plugins = PluginManager(self, PLUGINS_DIR, DB_PATH, extra_dirs=(GITIGNORE_PLUGINS_DIR,))
        self.plugins.discover()
        self.plugins.load()
        self.runtime = AgentRuntime(self)
        self.manager = SessionManager(self.storage, self.runtime)
        self.runtime.manager = self.manager
        # AI supervisor is a built-in capability, not an installable plugin.
        self.supervisor_task: asyncio.Task | None = None
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
        if self.supervisor_task is None or self.supervisor_task.done():
            self.supervisor_task = asyncio.create_task(supervisor_watch_loop(self))
        self._booted = True

    async def shutdown(self) -> None:
        if self.supervisor_task:
            self.supervisor_task.cancel()
            try:
                await self.supervisor_task
            except (asyncio.CancelledError, Exception):
                pass
            self.supervisor_task = None
        await self.plugins.shutdown()
        for task in list(self.manager.tasks.values()):
            task.cancel()
        await self.events.stop()

    def plugin_status(self) -> list[dict[str, Any]]:
        return self.plugins.status()

    def attach_app(self, app: Any) -> None:
        self.app = app

    def _route_insert_index(self) -> int:
        from starlette.routing import Mount

        routes = self.app.router.routes if self.app else []
        for index, route in enumerate(routes):
            if isinstance(route, Mount):
                return index
        return len(routes)

    def mount_plugin_routers(self, routers: list[Any]) -> None:
        if self.app is None or not routers:
            return
        routes = list(self.app.router.routes)
        seen = {id(route) for route in routes}
        index = self._route_insert_index()
        added: list[Any] = []
        for router in routers:
            for route in getattr(router, "routes", []):
                if id(route) not in seen:
                    added.append(route)
                    seen.add(id(route))
        if added:
            self.app.router.routes = routes[:index] + added + routes[index:]

    def mount_all_plugin_routers(self) -> None:
        for name, manifest in self.plugins.manifests.items():
            if self.plugins.loaded.get(name):
                self.mount_plugin_routers(self.plugins.routers_for(name))

    def unmount_plugin_routers(self, routers: list[Any]) -> None:
        if self.app is None or not routers:
            return
        remove: set[int] = set()
        for router in routers:
            for route in getattr(router, "routes", []):
                remove.add(id(route))
        if remove:
            self.app.router.routes = [route for route in self.app.router.routes if id(route) not in remove]

    async def set_plugin_enabled(self, name: str, enabled: bool) -> bool:
        await self.storage.set_plugin_state(name, enabled)
        if name in self.plugins.enabled:
            self.plugins.enabled[name] = enabled
        if name == "user-account":
            # Account protection lives in a global middleware that is installed at
            # boot; its on/off switch is handled by the plugin's own state file.
            return True
        if enabled:
            loaded = await self.plugins.load_one(name)
            if loaded:
                self.mount_plugin_routers(self.plugins.routers_for(name))
            return loaded
        routers = self.plugins.routers_for(name)
        await self.plugins.unload_one(name)
        self.unmount_plugin_routers(routers)
        return True

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
