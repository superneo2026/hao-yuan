from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class PluginContext:
    harness: Any
    manifest: dict[str, Any]
    plugin_dir: Path
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.manifest["name"]

    @property
    def tools(self):
        return self.harness.tools

    @property
    def agents(self):
        return self.harness.agents

    @property
    def storage(self):
        return self.harness.storage

    @property
    def events(self):
        return self.harness.events

    def register_tool(self, spec, handler) -> None:
        spec.source = self.name
        self.harness.tools.register(spec, handler)

    def register_agent(self, spec) -> None:
        spec.source = self.name
        self.harness.agents.register(spec)

    def add_skill_dir(self, relative: str = "skills") -> None:
        directory = self.plugin_dir / relative
        if directory.is_dir():
            self.harness.skills.add_dir(directory, self.name)

    def add_router(self, router) -> None:
        if router is not None:
            self.harness.plugin_routers.append(router)

    def add_middleware(self, middleware, **kwargs) -> None:
        if middleware is not None:
            self.harness.plugin_middlewares.append((middleware, kwargs))

    def on(self, hook: str, callback: Callable) -> None:
        self.harness.plugin_hooks.setdefault(hook, []).append(callback)

    def log(self, message: str) -> None:
        print(f"[plugin:{self.name}] {message}")


class PluginManager:
    def __init__(self, harness: Any, plugins_dir: Path, db_path: Path, extra_dirs: tuple[Path, ...] = ()):
        self.harness = harness
        self.plugins_dir = Path(plugins_dir)
        self.plugin_dirs = (self.plugins_dir, *(Path(directory) for directory in extra_dirs))
        self.db_path = Path(db_path)
        self.manifests: dict[str, dict[str, Any]] = {}
        self.contexts: dict[str, PluginContext] = {}
        self.loaded: dict[str, bool] = {}
        self.errors: dict[str, str] = {}
        self.enabled: dict[str, bool] = {}
        self.routers: dict[str, list[Any]] = {}

    def _read_states(self) -> dict[str, dict[str, Any]]:
        if not self.db_path.exists():
            return {}
        try:
            connection = sqlite3.connect(str(self.db_path))
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT name, enabled, config FROM plugins").fetchall()
            connection.close()
            return {row["name"]: {"enabled": bool(row["enabled"]), "config": json.loads(row["config"] or "{}")} for row in rows}
        except Exception:
            return {}

    def discover(self) -> list[dict[str, Any]]:
        states = self._read_states()
        for directory in self.plugin_dirs:
            if not directory.exists():
                continue
            for manifest_path in sorted(directory.glob("*/plugin.json")):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    print(f"[plugin] invalid manifest {manifest_path}: {exc}")
                    continue
                name = str(manifest.get("name") or manifest_path.parent.name)
                if name in self.manifests:
                    continue
                manifest["name"] = name
                manifest["_dir"] = str(manifest_path.parent)
                self.manifests[name] = manifest
                state = states.get(name)
                self.enabled[name] = (
                    state["enabled"] if state is not None else bool(manifest.get("default_enabled", True))
                )
        return list(self.manifests.values())

    def _ordered(self) -> list[dict[str, Any]]:
        remaining = {name: manifest for name, manifest in self.manifests.items() if self.enabled.get(name, True)}
        ordered: list[dict[str, Any]] = []
        loaded_names: set[str] = set()
        while remaining:
            progressed = False
            for name, manifest in list(remaining.items()):
                requires = [r for r in manifest.get("requires", []) if r in self.manifests]
                if all(required in loaded_names or not self.enabled.get(required, True) for required in requires):
                    ordered.append(manifest)
                    loaded_names.add(name)
                    remaining.pop(name, None)
                    progressed = True
            if not progressed:
                for manifest in remaining.values():
                    self.errors[manifest["name"]] = "unresolved plugin dependency cycle"
                    self.loaded[manifest["name"]] = False
                break
        return ordered

    @staticmethod
    def _load_module(module_name: str, path: Path):
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _unregister_sources(self, name: str) -> None:
        self.harness.tools.unregister_source(name)
        self.harness.agents.unregister_source(name)
        remove = getattr(self.harness.skills, "remove_source", None)
        if callable(remove):
            remove(name)

    def _load_manifest(self, manifest: dict[str, Any], states: dict[str, dict[str, Any]]) -> None:
        name = manifest["name"]
        directory = Path(manifest["_dir"])
        config = (states.get(name) or {}).get("config", {}) or manifest.get("config", {})
        context = PluginContext(
            harness=self.harness,
            manifest=manifest,
            plugin_dir=directory,
            config=config,
        )
        self.contexts[name] = context
        before = len(self.harness.plugin_routers)
        try:
            backend = manifest.get("backend") or "plugin.py"
            backend_path = directory / backend
            if backend_path.is_file():
                module = self._load_module(f"haoyuan_plugin_{name}", backend_path)
                register = getattr(module, "register", None)
                if callable(register):
                    register(context)
            routes = manifest.get("routes")
            if routes:
                routes_path = directory / routes
                if routes_path.is_file():
                    module = self._load_module(f"haoyuan_plugin_{name}_routes", routes_path)
                    router = getattr(module, "router", None)
                    context.add_router(router)
            self.routers[name] = self.harness.plugin_routers[before:]
            self.loaded[name] = True
            self.errors.pop(name, None)
        except Exception as exc:
            self.contexts.pop(name, None)
            self.routers[name] = []
            self.loaded[name] = False
            self.errors[name] = f"{type(exc).__name__}: {exc}"
            self._unregister_sources(name)
            print(f"[plugin:{name}] load failed: {exc}")
            traceback.print_exc()

    def load(self) -> None:
        states = self._read_states()
        for manifest in self._ordered():
            name = manifest["name"]
            if not self.enabled.get(name, True):
                self.loaded[name] = False
                continue
            self._load_manifest(manifest, states)

    async def _run_startup(self, name: str) -> None:
        context = self.contexts.get(name)
        if context is None:
            return
        module = sys.modules.get(f"haoyuan_plugin_{name}")
        hook = getattr(module, "startup", None) if module else None
        if callable(hook):
            try:
                await hook(context)
            except Exception as exc:
                self.errors[name] = f"startup: {type(exc).__name__}: {exc}"

    async def load_one(self, name: str) -> bool:
        manifest = self.manifests.get(name)
        if manifest is None:
            return False
        if self.loaded.get(name) and name in self.contexts:
            return True
        self._load_manifest(manifest, self._read_states())
        if not self.loaded.get(name):
            return False
        await self._run_startup(name)
        return True

    async def unload_one(self, name: str) -> None:
        context = self.contexts.get(name)
        module = sys.modules.get(f"haoyuan_plugin_{name}")
        hook = getattr(module, "shutdown", None) if module else None
        if callable(hook) and context is not None:
            try:
                await hook(context)
            except Exception:
                pass
        self._unregister_sources(name)
        for module_name in (f"haoyuan_plugin_{name}", f"haoyuan_plugin_{name}_routes"):
            sys.modules.pop(module_name, None)
        self.contexts.pop(name, None)
        self.loaded[name] = False

    def routers_for(self, name: str) -> list[Any]:
        return list(self.routers.get(name, []))

    async def startup(self) -> None:
        for name, context in self.contexts.items():
            if not self.loaded.get(name):
                continue
            module = sys.modules.get(f"haoyuan_plugin_{name}")
            hook = getattr(module, "startup", None) if module else None
            if callable(hook):
                try:
                    await hook(context)
                except Exception as exc:
                    self.errors[name] = f"startup: {type(exc).__name__}: {exc}"

    async def shutdown(self) -> None:
        for name, context in self.contexts.items():
            module = sys.modules.get(f"haoyuan_plugin_{name}")
            hook = getattr(module, "shutdown", None) if module else None
            if callable(hook):
                try:
                    await hook(context)
                except Exception:
                    pass

    def status(self) -> list[dict[str, Any]]:
        out = []
        for name, manifest in sorted(self.manifests.items()):
            out.append(
                {
                    "name": name,
                    "title": manifest.get("title", name),
                    "version": manifest.get("version", "1.0.0"),
                    "description": manifest.get("description", ""),
                    "author": manifest.get("author", ""),
                    "requires": manifest.get("requires", []),
                    "default_enabled": bool(manifest.get("default_enabled", True)),
                    "enabled": self.enabled.get(name, False),
                    "loaded": self.loaded.get(name, False),
                    "error": self.errors.get(name, ""),
                    "contributes": manifest.get("contributes", {}),
                    "frontend": manifest.get("frontend", {}),
                    "config": (self.contexts.get(name).config if self.contexts.get(name) else manifest.get("config", {})),
                }
            )
        return out

    def get(self, name: str) -> dict[str, Any] | None:
        return next((item for item in self.status() if item["name"] == name), None)
