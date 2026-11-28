from __future__ import annotations

import io
import json
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from configs.configs import (
    DATA_DIR,
    GITIGNORE_PLUGINS_DIR,
    PLUGIN_CATALOG_MAX_BYTES,
    PLUGIN_CENTER_URL,
    PLUGIN_PACKAGE_MAX_BYTES,
    PLUGIN_PACKAGE_MAX_FILES,
    PLUGIN_PACKAGE_MAX_UNCOMPRESSED_BYTES,
    PLUGINS_DIR,
    prefix,
)
from core.harness import get_harness
from core.telemetry import remember_center_url
from extensions.common import fail, ok

router = APIRouter(prefix=prefix, tags=["marketplace"])

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
CORE_PLUGINS = {"coding", "plans", "orchestrator", "supervisor"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".pytest_cache", ".mypy_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo"}
MANIFEST_MAX_BYTES = 256 * 1024
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


class InstallBody(BaseModel):
    name: str = ""
    center_url: str = ""
    download_url: str = ""


class SourceBody(BaseModel):
    source: str = ""


def _validated_url(value: str, label: str = "插件中心地址") -> str:
    text = str(value or "").strip()
    parsed = urlsplit(text)
    try:
        hostname = parsed.hostname or ""
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label}无效") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError(f"{label}无效")
    if parsed.username or parsed.password:
        raise ValueError(f"{label}不能包含认证信息")
    if hostname.lower() in BLOCKED_HOSTS:
        raise ValueError(f"{label}不可指向云元数据服务")
    return text.rstrip("/")


def _center_url(value: str = "") -> str:
    return _validated_url(value or PLUGIN_CENTER_URL)


def _same_origin(left: str, right: str) -> bool:
    a = urlsplit(left)
    b = urlsplit(right)

    def port(parsed) -> int:
        return parsed.port or (443 if parsed.scheme == "https" else 80)

    return (
        a.scheme == b.scheme
        and (a.hostname or "").lower() == (b.hostname or "").lower()
        and port(a) == port(b)
    )


async def _fetch_limited(url: str, limit: int, timeout: float, label: str) -> bytes:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                raise ValueError(f"{label}超过大小限制")
            data = bytearray()
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > limit:
                    raise ValueError(f"{label}超过大小限制")
                data.extend(chunk)
    return bytes(data)


async def _fetch_catalog(center: str) -> list[dict]:
    body = await _fetch_limited(
        f"{center}/api/plugin-center/plugins",
        PLUGIN_CATALOG_MAX_BYTES,
        6.0,
        "插件中心响应",
    )
    try:
        payload = json.loads(body)
    except ValueError as exc:
        raise ValueError("插件中心返回了无效的 JSON") from exc
    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise ValueError(payload.get("message") or "plugin center returned an error")
    data = payload.get("data") if isinstance(payload, dict) else payload
    plugins = data.get("plugins") if isinstance(data, dict) else data
    if not isinstance(plugins, list):
        return []
    return [item for item in plugins if isinstance(item, dict)]


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


def _is_unsafe_info(info: zipfile.ZipInfo) -> bool:
    if info.flag_bits & 0x1:
        return True
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _extract_package(data: bytes, target_dir: Path | None = None) -> dict:
    destination_root = Path(target_dir) if target_dir is not None else PLUGINS_DIR
    if not data:
        raise ValueError("插件包为空")
    if len(data) > PLUGIN_PACKAGE_MAX_BYTES:
        raise ValueError("插件包超过大小限制")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("无法识别插件包，请使用 zip 文件") from exc

    infos = archive.infolist()
    if len(infos) > PLUGIN_PACKAGE_MAX_FILES:
        raise ValueError("插件包文件数量超过限制")
    if sum(max(0, info.file_size) for info in infos) > PLUGIN_PACKAGE_MAX_UNCOMPRESSED_BYTES:
        raise ValueError("插件包解压后超过大小限制")

    names = [info.filename.replace("\\", "/") for info in infos if not info.is_dir()]
    prefix = _zip_prefix(names)
    destination_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(tempfile.mkdtemp(prefix=".haoyuan-plugin-", dir=str(destination_root.parent)))
    try:
        written_files = 0
        written_bytes = 0
        for info in infos:
            raw = info.filename.replace("\\", "/")
            if info.is_dir() or not raw.startswith(prefix):
                continue
            relative = raw[len(prefix) :]
            if not relative:
                continue
            if _is_unsafe_info(info):
                raise ValueError("插件包包含不安全的符号链接或加密文件")
            target = Path(relative)
            if target.is_absolute() or ".." in target.parts or any(":" in part for part in target.parts):
                raise ValueError("插件包包含不安全的路径")
            if any(part in SKIP_DIRS for part in target.parts):
                continue
            if target.suffix.lower() in SKIP_SUFFIXES:
                continue
            destination = staging_root / target
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as handle:
                while True:
                    chunk = source.read(64 * 1024)
                    if not chunk:
                        break
                    written_bytes += len(chunk)
                    if written_bytes > PLUGIN_PACKAGE_MAX_UNCOMPRESSED_BYTES:
                        raise ValueError("插件包解压后超过大小限制")
                    handle.write(chunk)
            written_files += 1
            if written_files > PLUGIN_PACKAGE_MAX_FILES:
                raise ValueError("插件包文件数量超过限制")

        manifest_path = staging_root / "plugin.json"
        if not manifest_path.is_file():
            raise ValueError("插件包中缺少 plugin.json")
        if manifest_path.stat().st_size > MANIFEST_MAX_BYTES:
            raise ValueError("plugin.json 超过大小限制")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("plugin.json 格式不正确") from exc
        if not isinstance(manifest, dict):
            raise ValueError("plugin.json 格式不正确")
        name = str(manifest.get("name") or "").strip()
        if not NAME_RE.match(name):
            raise ValueError("plugin.json 中的 name 不合法")
        if name in CORE_PLUGINS:
            raise ValueError("核心插件名称不可覆盖")
        for key, limit in (("title", 200), ("version", 64)):
            value = manifest.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"plugin.json 缺少或包含不合法的字段: {key}")

        destination_root.mkdir(parents=True, exist_ok=True)
        target = destination_root / name
        if target.resolve().parent != destination_root.resolve():
            raise ValueError("插件名称不合法")
        for directory in _plugin_dirs():
            candidate = directory / name
            if not candidate.is_dir():
                continue
            if candidate.resolve() == target.resolve():
                raise FileExistsError(f"插件 {name} 已安装")
            location = "仓库插件目录（api/plugins）" if directory.resolve() == PLUGINS_DIR.resolve() else "本地插件目录（api/gitignore_plugins）"
            raise FileExistsError(f"插件 {name} 已存在于{location}，请先删除旧版本后再上传")
        shutil.move(str(staging_root), str(target))
        staging_root = None
        return {
            "name": name,
            "title": manifest.get("title", name),
            "version": manifest.get("version", "1.0.0"),
            "already_installed": False,
        }
    finally:
        if staging_root is not None and staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)


def _plugin_dirs() -> tuple[Path, ...]:
    return (PLUGINS_DIR, GITIGNORE_PLUGINS_DIR)


async def _hot_activate(harness, name: str) -> dict:
    if not name or name not in harness.plugins.manifests:
        return {"enabled": False, "loaded": False}
    if not harness.plugins.enabled.get(name, True):
        return {"enabled": False, "loaded": bool(harness.plugins.loaded.get(name, False))}
    loaded = await harness.set_plugin_enabled(name, True)
    return {"enabled": True, "loaded": bool(loaded)}


def _installed_map() -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for directory in _plugin_dirs():
        if not directory.is_dir():
            continue
        for manifest_path in directory.glob("*/plugin.json"):
            if manifest_path.is_symlink():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(manifest, dict):
                continue
            name = str(manifest.get("name") or manifest_path.parent.name)
            mapping.setdefault(name, manifest)
    return mapping


@router.get("/marketplace/plugins")
async def marketplace_plugins(center: str = ""):
    target = (center or PLUGIN_CENTER_URL).strip().rstrip("/")
    installed = _installed_map()
    try:
        url = _center_url(center)
        url, catalog = await _resolve_catalog(url)
        if center:
            remember_center_url(url)
    except Exception as exc:
        return ok(
            {
                "center_url": target,
                "online": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "请确认插件中心已启动（默认 https://hao-yuan.conductorer.com），并重启豪源后端以加载最新 API。",
                "plugins": [],
            }
        )
    plugins = []
    for item in catalog:
        name = str(item.get("name") or "")
        if not NAME_RE.match(name):
            continue
        manifest = installed.get(name, {})
        download_url = item.get("download_url")
        if not isinstance(download_url, str) or not download_url.strip():
            download_url = f"/api/plugin-center/plugins/{name}/download"
        plugins.append(
            {
                **item,
                "name": name,
                "installed": bool(manifest),
                "installed_version": manifest.get("version", ""),
                "download_url": download_url,
            }
        )
    return ok({"center_url": url, "online": True, "plugins": plugins, "installed": sorted(installed.keys())})


@router.post("/marketplace/install")
async def install_plugin(body: InstallBody):
    download_url = (body.download_url or "").strip()
    title = body.name
    try:
        url = _center_url(body.center_url)
        if body.center_url:
            remember_center_url(url)
        if not download_url:
            if not NAME_RE.match(body.name or ""):
                return fail("插件名称不合法", 400)
            url, catalog = await _resolve_catalog(url)
            match = next((item for item in catalog if item.get("name") == body.name), None)
            if match is None:
                return fail("插件中心中未找到该插件", 404)
            candidate = match.get("download_url")
            if not isinstance(candidate, str) or not candidate.strip():
                candidate = f"/api/plugin-center/plugins/{body.name}/download"
            download_url = candidate
            title = match.get("title") or body.name
        download_url = urljoin(f"{url}/", download_url)
        if not _same_origin(url, download_url):
            raise ValueError("插件下载地址必须与插件中心同源")
        download_url = _validated_url(download_url, "插件下载地址")
        content = await _fetch_limited(
            download_url,
            PLUGIN_PACKAGE_MAX_BYTES,
            30.0,
            "插件包",
        )
        result = _extract_package(content)
        harness = await get_harness()
        harness.plugins.discover()
        state = await _hot_activate(harness, result.get("name", ""))
        return ok(
            {
                **result,
                **state,
                "restart_required": False,
                "message": "插件已安装并即时生效。" if state["loaded"] else "插件已安装。",
            },
            "插件安装成功",
        )
    except FileExistsError:
        return ok({"name": body.name, "title": title, "installed": True, "already_installed": True, "restart_required": False}, "插件已安装")
    except (ValueError, httpx.HTTPError, OSError) as exc:
        return fail(f"安装失败: {exc}", 400)


def _upload_target_dir(source: str) -> Path | None:
    if source == "gitignored":
        return GITIGNORE_PLUGINS_DIR
    if source == "tracked":
        return PLUGINS_DIR
    return None


@router.post("/plugins/upload")
async def upload_plugin(file: UploadFile = File(...), source: str = Form("tracked")):
    target_dir = _upload_target_dir(source)
    if target_dir is None:
        return fail("插件保存位置不合法", 400)
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        return fail("请上传 .zip 格式的插件包", 400)
    data = await file.read(PLUGIN_PACKAGE_MAX_BYTES + 1)
    if not data:
        return fail("上传文件为空", 400)
    if len(data) > PLUGIN_PACKAGE_MAX_BYTES:
        return fail("插件包超过大小限制", 400)
    try:
        result = _extract_package(data, target_dir)
    except FileExistsError as exc:
        return fail(str(exc) or "插件已安装，请先关闭并删除旧版本后再上传", 400)
    except (ValueError, OSError) as exc:
        return fail(f"上传失败: {exc}", 400)
    harness = await get_harness()
    harness.plugins.discover()
    state = await _hot_activate(harness, result.get("name", ""))
    return ok(
        {
            **result,
            "source": source,
            **state,
            "restart_required": False,
            "message": "插件已上传并即时生效。" if state["loaded"] else "插件已上传。",
        },
        "插件上传成功",
    )


@router.post("/plugins/{name}/source")
async def move_plugin_source(name: str, body: SourceBody):
    if not NAME_RE.match(name or ""):
        return fail("插件名称不合法", 400)
    target_source = body.source
    target_dir = _upload_target_dir(target_source)
    if target_dir is None:
        return fail("目标保存位置不合法", 400)
    current_dir = None
    for directory in _plugin_dirs():
        candidate = directory / name
        if candidate.is_dir():
            current_dir = candidate
            break
    if current_dir is None:
        return fail("插件未安装", 404)
    target = target_dir / name
    if current_dir.resolve() == target.resolve():
        return ok(
            {
                "name": name,
                "source": target_source,
                "changed": False,
                "restart_required": False,
            },
            "插件已在该位置",
        )
    if target.exists():
        return fail("目标位置已存在同名插件", 409)
    harness = await get_harness()
    manifest = harness.plugins.manifests.get(name) or {}
    if manifest.get("always_load"):
        return fail("常驻插件暂不支持转换来源", 400)
    if harness.plugins.enabled.get(name, False):
        return fail("请先关闭插件后再转换来源", 400)
    routers = harness.plugins.routers_for(name)
    if harness.plugins.loaded.get(name) or name in harness.plugins.contexts:
        await harness.plugins.unload_one(name)
        harness.unmount_plugin_routers(routers)
        harness.plugins.routers.pop(name, None)
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(current_dir), str(target))
    except OSError as exc:
        return fail(f"转换来源失败: {exc}", 500)
    loaded_manifest = harness.plugins.manifests.get(name)
    if loaded_manifest is None:
        harness.plugins.discover()
    else:
        loaded_manifest["_dir"] = str(target)
        loaded_manifest["_source"] = target_source
    harness.plugins.sources[name] = target_source
    return ok(
        {
            "name": name,
            "source": target_source,
            "changed": True,
            "enabled": bool(harness.plugins.enabled.get(name, False)),
            "loaded": bool(harness.plugins.loaded.get(name, False)),
            "deleted_path": str(current_dir),
            "target_path": str(target),
            "restart_required": False,
        },
        "插件来源已转换",
    )


@router.delete("/plugins/{name}")
async def uninstall_plugin(name: str, purge_data: bool = False):
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
    harness = await get_harness()
    if harness.plugins.enabled.get(name, False):
        return fail("请先关闭插件后再删除", 400)
    manifest: dict = {}
    manifest_path = target / "plugin.json"
    if manifest_path.is_file():
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded_manifest, dict):
                manifest = loaded_manifest
        except (OSError, ValueError):
            manifest = {}
    routers = harness.plugins.routers_for(name)
    await harness.plugins.unload_one(name)
    harness.unmount_plugin_routers(routers)
    harness.plugins.routers.pop(name, None)
    try:
        shutil.rmtree(target)
    except OSError as exc:
        return fail(f"删除插件源码失败: {exc}", 500)
    await harness.storage.delete_plugin_state(name)
    harness.plugins.manifests.pop(name, None)
    harness.plugins.enabled.pop(name, None)
    harness.plugins.loaded.pop(name, None)
    harness.plugins.contexts.pop(name, None)
    await harness.call_hook("plugin.toggled", name, False)
    purged: list[str] = []
    if purge_data:
        data_root = DATA_DIR.resolve()
        for item in manifest.get("data_files") or []:
            if not isinstance(item, str):
                continue
            filename = item.strip()
            if not filename or "/" in filename or "\\" in filename or filename in {".", ".."}:
                continue
            path = (data_root / filename).resolve()
            if path.parent != data_root or not path.is_file():
                continue
            try:
                path.unlink()
                purged.append(filename)
            except OSError:
                continue
    return ok(
        {
            "name": name,
            "installed": False,
            "deleted_path": str(target),
            "purged_data": purged,
            "restart_required": False,
        },
        "插件及其源码已删除" + ("，配置已清除" if purged else ""),
    )
