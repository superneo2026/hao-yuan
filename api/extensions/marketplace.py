from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin

import httpx
from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from configs.configs import GITIGNORE_PLUGINS_DIR, PLUGIN_CENTER_URL, PLUGIN_PACKAGE_MAX_BYTES, PLUGINS_DIR, prefix
from core.harness import get_harness
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["marketplace"])

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CORE_PLUGINS = {"coding", "plans", "video", "supervisor", "orchestrator", "embodied"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


class InstallBody(BaseModel):
    name: str = ""
    center_url: str = ""
    download_url: str = ""


def _center_url(value: str = "") -> str:
    return (value or PLUGIN_CENTER_URL).strip().rstrip("/")


async def _fetch_catalog(center: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, trust_env=False) as client:
        response = await client.get(f"{center}/api/plugin-center/plugins")
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise ValueError(payload.get("message") or "plugin center returned an error")
    data = payload.get("data") if isinstance(payload, dict) else payload
    plugins = data.get("plugins") if isinstance(data, dict) else data
    return plugins if isinstance(plugins, list) else []


def _catalog_candidates(center: str) -> list[str]:
    values = [center]
    if "127.0.0.1" in center:
        values.append(center.replace("127.0.0.1", "localhost"))
    if "localhost" in center:
        values.append(center.replace("localhost", "127.0.0.1"))
    return list(dict.fromkeys(value for value in values if value))


async def _resolve_catalog(center: str) -> tuple[str, list[dict]]:
    last_error: Exception | None = None
    for candidate in _catalog_candidates(center):
        try:
            return candidate, await _fetch_catalog(candidate)
        except Exception as exc:
            last_error = exc
    raise last_error or RuntimeError("plugin center is unavailable")


def _zip_prefix(names: list[str]) -> str:
    candidates = [name for name in names if name.rstrip("/").endswith("plugin.json")]
    if not candidates:
        raise ValueError("插件包中缺少 plugin.json")
    candidates.sort(key=lambda name: name.count("/"))
    chosen = candidates[0]
    if chosen.count("/") > 1:
        raise ValueError("plugin.json 必须位于压缩包根目录或唯一的一级目录中")
    return chosen[: -len("plugin.json")]


def _extract_package(data: bytes, overwrite: bool) -> dict:
    if len(data) > PLUGIN_PACKAGE_MAX_BYTES:
        raise ValueError("插件包超过大小限制")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("无法识别插件包，请上传 zip 文件") from exc

    names = [info.filename.replace("\\", "/") for info in archive.infolist()]
    prefix = _zip_prefix(names)
    staging_root = Path(tempfile.mkdtemp(prefix=".haoyuan-plugin-", dir=str(PLUGINS_DIR.parent)))
    try:
        for info in archive.infolist():
            raw = info.filename.replace("\\", "/")
            if info.is_dir() or not raw.startswith(prefix):
                continue
            relative = raw[len(prefix) :]
            if not relative:
                continue
            target = Path(relative)
            if target.is_absolute() or ".." in target.parts:
                raise ValueError("插件包包含不安全的路径")
            if any(part in SKIP_DIRS for part in target.parts):
                continue
            if target.suffix.lower() in SKIP_SUFFIXES:
                continue
            destination = staging_root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)

        manifest_path = staging_root / "plugin.json"
        if not manifest_path.is_file():
            raise ValueError("插件包中缺少 plugin.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("plugin.json 格式不正确") from exc
        name = str(manifest.get("name") or "").strip()
        if not NAME_RE.match(name):
            raise ValueError("plugin.json 中的 name 不合法")
        for key in ("title", "version"):
            if not manifest.get(key):
                raise ValueError(f"plugin.json 缺少字段: {key}")

        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        target = PLUGINS_DIR / name
        parents = target.resolve().parent
        if parents != PLUGINS_DIR.resolve():
            raise ValueError("插件名称不合法")
        already = target.is_dir()
        if already and not overwrite:
            raise FileExistsError("插件已安装")
        if already:
            shutil.rmtree(target)
        shutil.move(str(staging_root), str(target))
        staging_root = None
        return {"name": name, "title": manifest.get("title", name), "version": manifest.get("version", "1.0.0"), "already_installed": already}
    finally:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


def _plugin_dirs() -> tuple[Path, ...]:
    return (PLUGINS_DIR, GITIGNORE_PLUGINS_DIR)


def _installed_map() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for directory in _plugin_dirs():
        if not directory.is_dir():
            continue
        for manifest_path in directory.glob("*/plugin.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            name = str(manifest.get("name") or manifest_path.parent.name)
            mapping.setdefault(name, manifest)
    return mapping


@router.get("/marketplace/plugins")
async def marketplace_plugins(center: str = ""):
    url = _center_url(center)
    installed = _installed_map()
    try:
        url, catalog = await _resolve_catalog(url)
    except Exception as exc:
        return ok(
            {
                "center_url": url,
                "online": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "请确认插件中心已启动（默认 http://127.0.0.1:8180），并重启豪源后端以加载最新 API。",
                "plugins": [],
            }
        )
    plugins = []
    for item in catalog:
        name = str(item.get("name") or "")
        if not name:
            continue
        manifest = installed.get(name, {})
        plugins.append(
            {
                **item,
                "installed": bool(manifest),
                "installed_version": manifest.get("version", ""),
                "download_url": item.get("download_url") or f"/api/plugin-center/plugins/{name}/download",
            }
        )
    return ok({"center_url": url, "online": True, "plugins": plugins, "installed": sorted(installed.keys())})


@router.post("/marketplace/install")
async def install_plugin(body: InstallBody):
    url = _center_url(body.center_url)
    download_url = (body.download_url or "").strip()
    title = body.name
    try:
        if not download_url:
            if not NAME_RE.match(body.name or ""):
                return fail("插件名称不合法", 400)
            url, catalog = await _resolve_catalog(url)
            match = next((item for item in catalog if item.get("name") == body.name), None)
            if match is None:
                return fail("插件中心中未找到该插件", 404)
            download_url = match.get("download_url") or f"/api/plugin-center/plugins/{body.name}/download"
            title = match.get("title") or body.name
        download_url = urljoin(f"{url}/", download_url)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, trust_env=False) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            content = response.content
        result = _extract_package(content, overwrite=False)
        harness = await get_harness()
        harness.plugins.discover()
        return ok(
            {
                **result,
                "restart_required": True,
                "message": "插件已安装。启用后重启后端即可加载插件路由。",
            },
            "插件安装成功",
        )
    except FileExistsError:
        return ok({"name": body.name, "title": title, "installed": True, "already_installed": True, "restart_required": False}, "插件已安装")
    except (ValueError, httpx.HTTPError, OSError) as exc:
        return fail(f"安装失败: {exc}", 400)


@router.post("/plugins/upload")
async def upload_plugin(file: UploadFile = File(...)):
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        return fail("请上传 .zip 格式的插件包", 400)
    data = await file.read()
    if not data:
        return fail("上传文件为空", 400)
    try:
        result = _extract_package(data, overwrite=True)
    except (ValueError, OSError) as exc:
        return fail(f"上传失败: {exc}", 400)
    harness = await get_harness()
    harness.plugins.discover()
    return ok(
        {
            **result,
            "restart_required": True,
            "message": "插件已上传到 api/plugins。启用后重启后端即可加载。",
        },
        "插件上传成功",
    )


@router.delete("/plugins/{name}")
async def uninstall_plugin(name: str):
    if not NAME_RE.match(name or ""):
        return fail("插件名称不合法", 400)
    if name in CORE_PLUGINS:
        return fail("核心插件不可卸载", 400)
    target = None
    for directory in _plugin_dirs():
        candidate = (directory / name).resolve()
        if candidate.parent == directory.resolve() and candidate.is_dir():
            target = candidate
            break
    if target is None:
        return fail("插件未安装", 404)
    shutil.rmtree(target, ignore_errors=True)
    harness = await get_harness()
    harness.plugins.manifests.pop(name, None)
    harness.plugins.enabled.pop(name, None)
    harness.plugins.loaded.pop(name, None)
    harness.plugins.contexts.pop(name, None)
    await harness.call_hook("plugin.toggled", name, False)
    return ok({"name": name, "installed": False, "restart_required": True}, "插件已卸载")
