from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from configs.configs import DATA_DIR, prefix
from extensions.common import fail, ok

STATE_PATH = DATA_DIR / "remote_management.json"
USER_ACCOUNT_PATH = DATA_DIR / "user_account.json"
CONNECTION_PREFIX = "HYR1-"
TOKEN_TTL = 30 * 24 * 3600
USER_TOKEN_TTL = 7 * 24 * 3600
HTTP_TIMEOUT = 6.0
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_REVOKED = "revoked"
_ACTIVE = {"value": False}


def _ensure_active() -> None:
    if not _ACTIVE["value"]:
        raise HTTPException(status_code=404, detail="remote-management plugin is disabled")


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(secret: str, raw: bytes) -> str:
    return _b64(hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest())


def _encode_code(url: str, secret: str, name: str) -> str:
    payload = {"v": 1, "url": (url or "").rstrip("/"), "k": secret, "n": name}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return CONNECTION_PREFIX + _b64(raw)


def _decode_code(code: str) -> dict[str, str]:
    text = (code or "").strip()
    if not text.startswith(CONNECTION_PREFIX):
        raise ValueError("连接密钥格式不正确")
    try:
        payload = json.loads(_unb64(text[len(CONNECTION_PREFIX) :]).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError) as exc:
        raise ValueError("连接密钥格式不正确") from exc
    url = str(payload.get("url") or "").strip().rstrip("/")
    key = str(payload.get("k") or "").strip()
    if not url or not key:
        raise ValueError("连接密钥缺少地址或密钥")
    return {"url": url, "key": key, "name": str(payload.get("n") or "").strip()}


def _cookie_value(header: str, name: str) -> str:
    for part in (header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value.strip()
    return ""


def _issue_user_account_token() -> str:
    """If 用户账号保护 is configured, mint a compatible session so a remote
    manager can operate the embedded HaoYuan without a second login."""
    path = Path(USER_ACCOUNT_PATH)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict) or not data.get("configured") or not data.get("enabled"):
        return ""
    secret = str(data.get("secret") or "")
    username = str(data.get("username") or "")
    if not secret or not username:
        return ""
    payload = {"u": username, "exp": int(time.time()) + USER_TOKEN_TTL, "n": secrets.token_hex(8)}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"{_b64(raw)}.{_sign(secret, raw)}"


class RemoteStore:
    """Remote management state is stored under api/data so it survives plugin
    upgrades and never lives inside the plugin package itself."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        instance_id = secrets.token_hex(8)
        host = socket.gethostname().strip() or "HaoYuan"
        return {
            "version": 1,
            "instance_id": instance_id,
            "instance_name": host,
            "public_url": "",
            "secret": secrets.token_hex(32),
            "keys": [],
            "incoming": [],
            "outgoing": [],
            "created_at": "",
            "updated_at": "",
        }

    def _normalize(self, data: Any) -> dict[str, Any]:
        base = self._empty()
        if isinstance(data, dict):
            base.update(data)
        base["version"] = 1
        base["instance_id"] = str(base.get("instance_id") or secrets.token_hex(8))
        base["instance_name"] = str(base.get("instance_name") or socket.gethostname() or "HaoYuan")
        base["public_url"] = str(base.get("public_url") or "").strip().rstrip("/")
        base["secret"] = str(base.get("secret") or secrets.token_hex(32))
        for name in ("keys", "incoming", "outgoing"):
            if not isinstance(base.get(name), list):
                base[name] = []
        return base

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return self._normalize({})
            try:
                return self._normalize(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return self._normalize({})

    def write(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._normalize(data)
            payload["updated_at"] = _now()
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
            return payload

    def ensure(self) -> dict[str, Any]:
        with self._lock:
            if self.path.is_file():
                return self.read()
            data = self._empty()
            data["created_at"] = _now()
            return self.write(data)

    def update(self, mutate) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            mutate(data)
            return self.write(data)

    # ---- keys -----------------------------------------------------------
    def add_key(self, label: str) -> dict[str, Any]:
        key = {
            "id": secrets.token_hex(6),
            "label": (label or "").strip()[:64] or "默认密钥",
            "secret": secrets.token_urlsafe(24),
            "created_at": _now(),
            "last_used_at": "",
        }

        def mutate(data: dict[str, Any]) -> None:
            data["keys"].insert(0, key)

        self.update(mutate)
        return key

    def delete_key(self, key_id: str) -> bool:
        found = {"ok": False}

        def mutate(data: dict[str, Any]) -> None:
            keys = [item for item in data["keys"] if item.get("id") != key_id]
            if len(keys) == len(data["keys"]):
                return
            found["ok"] = True
            data["keys"] = keys
            for item in data["incoming"]:
                if item.get("key_id") == key_id and item.get("status") != STATUS_REJECTED:
                    item["status"] = STATUS_REVOKED
                    item["decided_at"] = _now()
                    item["decided_by"] = "key-deleted"

        self.update(mutate)
        return bool(found["ok"])

    def find_key(self, secret: str) -> dict[str, Any] | None:
        if not secret:
            return None
        for key in self.read()["keys"]:
            if hmac.compare_digest(str(key.get("secret") or ""), secret):
                return key
        return None

    def touch_key(self, key_id: str) -> None:
        def mutate(data: dict[str, Any]) -> None:
            for key in data["keys"]:
                if key.get("id") == key_id:
                    key["last_used_at"] = _now()

        self.update(mutate)

    # ---- incoming (this system is managed) ------------------------------
    def create_incoming(self, key_id: str, manager_name: str, manager_url: str) -> dict[str, Any]:
        item = {
            "id": secrets.token_hex(8),
            "key_id": key_id,
            "manager_name": (manager_name or "").strip()[:64] or "远程豪源",
            "manager_url": (manager_url or "").strip()[:255],
            "status": STATUS_PENDING,
            "token": "",
            "created_at": _now(),
            "decided_at": "",
            "decided_by": "",
            "last_seen_at": "",
        }

        def mutate(data: dict[str, Any]) -> None:
            data["incoming"].insert(0, item)

        self.update(mutate)
        return item

    def get_incoming(self, request_id: str) -> dict[str, Any] | None:
        return next((item for item in self.read()["incoming"] if item.get("id") == request_id), None)

    def set_incoming_status(self, request_id: str, status: str, by: str = "local") -> dict[str, Any] | None:
        result: dict[str, Any] = {}

        def mutate(data: dict[str, Any]) -> None:
            for item in data["incoming"]:
                if item.get("id") != request_id:
                    continue
                item["status"] = status
                item["decided_at"] = _now()
                item["decided_by"] = by
                if status == STATUS_APPROVED:
                    if not item.get("token"):
                        item["token"] = self._make_token(data["secret"], request_id)
                    result.update(item)
                elif status == STATUS_REVOKED:
                    item["token"] = ""
                    result.update(item)
                else:
                    item["token"] = ""
                    result.update(item)

        self.update(mutate)
        return result or None

    def delete_incoming(self, request_id: str) -> bool:
        found = {"ok": False}

        def mutate(data: dict[str, Any]) -> None:
            items = [item for item in data["incoming"] if item.get("id") != request_id]
            if len(items) == len(data["incoming"]):
                return
            found["ok"] = True
            data["incoming"] = items

        self.update(mutate)
        return bool(found["ok"])

    @staticmethod
    def _make_token(secret: str, request_id: str) -> str:
        payload = {"v": 1, "rid": request_id, "exp": int(time.time()) + TOKEN_TTL, "n": secrets.token_hex(6)}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return f"{_b64(raw)}.{_sign(secret, raw)}"

    def verify_token(self, token: str) -> dict[str, Any] | None:
        if not token or "." not in token:
            return None
        data = self.read()
        secret = str(data.get("secret") or "")
        if not secret:
            return None
        try:
            raw_text, signature_text = token.split(".", 1)
            raw = _unb64(raw_text)
            signature = _unb64(signature_text)
            if not hmac.compare_digest(signature, hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()):
                return None
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        request_id = str(payload.get("rid") or "")
        item = next((entry for entry in data["incoming"] if entry.get("id") == request_id), None)
        if item is None or item.get("status") != STATUS_APPROVED:
            return None
        key_id = str(item.get("key_id") or "")
        if not any(key.get("id") == key_id for key in data["keys"]):
            return None
        return payload

    # ---- outgoing (this system manages others) --------------------------
    def upsert_outgoing(self, record: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}

        def mutate(data: dict[str, Any]) -> None:
            existing = next((item for item in data["outgoing"] if item.get("url") == record.get("url")), None)
            if existing:
                original_id = existing.get("id")
                existing.update(record)
                existing["id"] = original_id or record["id"]
                result.update(existing)
            else:
                data["outgoing"].insert(0, record)
                result.update(record)

        self.update(mutate)
        return result

    def get_outgoing(self, system_id: str) -> dict[str, Any] | None:
        return next((item for item in self.read()["outgoing"] if item.get("id") == system_id), None)

    def update_outgoing(self, system_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        result: dict[str, Any] = {}

        def mutate(data: dict[str, Any]) -> None:
            for item in data["outgoing"]:
                if item.get("id") == system_id:
                    item.update(patch)
                    result.update(item)

        self.update(mutate)
        return result or None

    def delete_outgoing(self, system_id: str) -> bool:
        found = {"ok": False}

        def mutate(data: dict[str, Any]) -> None:
            items = [item for item in data["outgoing"] if item.get("id") != system_id]
            if len(items) == len(data["outgoing"]):
                return
            found["ok"] = True
            data["outgoing"] = items

        self.update(mutate)
        return bool(found["ok"])


class RemoteAccessMiddleware:
    """Accept a signed remote session token (or a valid connection key during
    the handshake) and translate it into the local account session if present."""

    def __init__(self, app, state_path: str):
        self.app = app
        self.store = RemoteStore(Path(state_path))

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"} or not _ACTIVE["value"]:
            return await self.app(scope, receive, send)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        path = scope.get("path", "")
        token = (
            headers.get("x-haoyuan-remote", "").strip()
            or (query.get("hy_remote_token") or [""])[0].strip()
            or (query.get("remote_token") or [""])[0].strip()
            or _cookie_value(headers.get("cookie", ""), "hy_remote_session")
        )
        allowed = bool(token and self.store.verify_token(token))
        if not allowed and path.startswith("/api/remote-management/public/"):
            key_value = (
                headers.get("x-remote-key", "").strip()
                or (query.get("remote_key") or [""])[0].strip()
            )
            allowed = bool(self.store.find_key(key_value))
        if allowed:
            user_token = _issue_user_account_token()
            if user_token:
                kept = [(key, value) for key, value in scope.get("headers", []) if key.lower() != b"authorization"]
                kept.append((b"authorization", f"Bearer {user_token}".encode("latin-1")))
                scope = dict(scope)
                scope["headers"] = kept
        return await self.app(scope, receive, send)


class KeyBody(BaseModel):
    label: str = ""


class SettingsBody(BaseModel):
    instance_name: str = ""
    public_url: str = ""


class PublicConnectBody(BaseModel):
    key: str = ""
    manager_name: str = ""
    manager_url: str = ""


class ConnectBody(BaseModel):
    code: str = ""
    url: str = ""
    name: str = ""


def _effective_url(store: RemoteStore, request: Request) -> str:
    configured = str(store.read().get("public_url") or "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _code_for(store: RemoteStore, key: dict[str, Any], request: Request) -> str:
    data = store.read()
    return _encode_code(_effective_url(store, request), str(key.get("secret") or ""), str(data.get("instance_name") or ""))


def _public_key(row: dict[str, Any], request: Request, store: RemoteStore) -> dict[str, Any]:
    item = dict(row)
    code = _code_for(store, row, request)
    item["connection_code"] = code
    item["masked_secret"] = f"{str(row.get('secret') or '')[:6]}…{str(row.get('secret') or '')[-4:]}"
    return item


def _public_incoming(row: dict[str, Any], store: RemoteStore) -> dict[str, Any]:
    item = {key: value for key, value in row.items() if key != "token"}
    key = next((entry for entry in store.read()["keys"] if entry.get("id") == row.get("key_id")), None)
    item["key_label"] = (key or {}).get("label", "")
    item["approved"] = row.get("status") == STATUS_APPROVED
    return item


def _public_outgoing(row: dict[str, Any], with_token: bool = False) -> dict[str, Any]:
    item = {key: value for key, value in row.items() if key != "secret"}
    if not with_token:
        item.pop("remote_token", None)
    item["ready"] = bool(with_token and row.get("remote_token") and row.get("enabled", True))
    return item


def _envelope_data(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if payload.get("code") not in (None, 200):
            raise ValueError(str(payload.get("message") or "对方系统返回错误"))
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
    return {}


async def _post_public(url: str, path: str, secret: str, body: dict[str, Any]) -> dict[str, Any]:
    headers = {"X-Remote-Key": secret}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, trust_env=False) as client:
        response = await client.post(
            f"{url.rstrip('/')}{path}",
            json=body,
            headers=headers,
            params={"remote_key": secret},
        )
        response.raise_for_status()
        return _envelope_data(response.json())


async def _get_public(url: str, path: str, secret: str) -> dict[str, Any]:
    headers = {"X-Remote-Key": secret}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, trust_env=False) as client:
        response = await client.get(
            f"{url.rstrip('/')}{path}",
            headers=headers,
            params={"remote_key": secret},
        )
        response.raise_for_status()
        return _envelope_data(response.json())


def _request_key(request: Request) -> str:
    return (
        request.headers.get("x-remote-key", "").strip()
        or (request.query_params.get("remote_key") or "").strip()
    )


def build_router(store: RemoteStore) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["remote-management"], dependencies=[Depends(_ensure_active)])

    def manager_identity(store: RemoteStore, request: Request) -> dict[str, str]:
        data = store.read()
        return {
            "manager_name": str(data.get("instance_name") or "HaoYuan"),
            "manager_url": _effective_url(store, request),
        }

    async def refresh_one(system: dict[str, Any]) -> dict[str, Any]:
        if not system.get("enabled", True):
            return system
        request_id = str(system.get("request_id") or "")
        if not request_id:
            return system
        try:
            data = await _get_public(
                str(system.get("url") or ""),
                f"/api/remote-management/public/requests/{request_id}",
                str(system.get("secret") or ""),
            )
            status = str(data.get("status") or system.get("status") or STATUS_PENDING)
            patch = {
                "status": status,
                "remote_token": str(data.get("remote_token") or "") if status == STATUS_APPROVED else "",
                "target_name": str(data.get("instance_name") or system.get("target_name") or ""),
                "last_checked": _now(),
                "last_error": "",
            }
            return store.update_outgoing(str(system.get("id")), patch) or system
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {403, 404}:
                patch = {
                    "status": STATUS_REVOKED,
                    "remote_token": "",
                    "last_checked": _now(),
                    "last_error": "对方已取消或删除了管理请求",
                }
            else:
                patch = {"last_checked": _now(), "last_error": f"{type(exc).__name__}: {exc}"}
            return store.update_outgoing(str(system.get("id")), patch) or system
        except Exception as exc:
            patch = {"last_checked": _now(), "last_error": f"{type(exc).__name__}: {exc}"}
            return store.update_outgoing(str(system.get("id")), patch) or system

    # ---- overview -------------------------------------------------------
    @router.get("/remote-management/overview")
    async def overview(request: Request):
        data = store.read()
        base = _effective_url(store, request)
        return ok(
            {
                "instance": {
                    "id": data.get("instance_id"),
                    "name": data.get("instance_name"),
                    "public_url": base,
                    "configured_public_url": data.get("public_url"),
                    "local_hint": "127.0.0.1" in base or "localhost" in base,
                },
                "keys": [_public_key(item, request, store) for item in data["keys"]],
                "incoming": [_public_incoming(item, store) for item in data["incoming"]],
                "outgoing": [_public_outgoing(item) for item in data["outgoing"]],
                "limits": {"token_ttl": TOKEN_TTL},
            }
        )

    @router.put("/remote-management/settings")
    async def update_settings(body: SettingsBody):
        patch: dict[str, Any] = {}
        if body.instance_name.strip():
            patch["instance_name"] = body.instance_name.strip()[:64]
        public_url = body.public_url.strip().rstrip("/")
        if public_url and not public_url.startswith(("http://", "https://")):
            return fail("公网地址必须以 http:// 或 https:// 开头", 400)
        patch["public_url"] = public_url

        def mutate(data: dict[str, Any]) -> None:
            data.update(patch)

        store.update(mutate)
        return ok(patch, "设置已保存")

    @router.post("/remote-management/keys")
    async def create_key(body: KeyBody, request: Request):
        key = store.add_key(body.label)
        return ok(_public_key(key, request, store), "密钥已生成")

    @router.delete("/remote-management/keys/{key_id}")
    async def remove_key(key_id: str):
        if not store.delete_key(key_id):
            return fail("密钥不存在", 404)
        return ok({"id": key_id}, "密钥已删除，相关授权已取消")

    # ---- incoming approval ---------------------------------------------
    @router.get("/remote-management/incoming")
    async def list_incoming():
        return ok([_public_incoming(item, store) for item in store.read()["incoming"]])

    @router.post("/remote-management/incoming/{request_id}/approve")
    async def approve(request_id: str):
        item = store.set_incoming_status(request_id, STATUS_APPROVED)
        if item is None:
            return fail("管理请求不存在", 404)
        return ok(_public_incoming(item, store), "已授权对方管理本机")

    @router.post("/remote-management/incoming/{request_id}/reject")
    async def reject(request_id: str):
        item = store.set_incoming_status(request_id, STATUS_REJECTED)
        if item is None:
            return fail("管理请求不存在", 404)
        return ok(_public_incoming(item, store), "已拒绝管理请求")

    @router.post("/remote-management/incoming/{request_id}/revoke")
    async def revoke(request_id: str):
        item = store.set_incoming_status(request_id, STATUS_REVOKED)
        if item is None:
            return fail("管理请求不存在", 404)
        return ok(_public_incoming(item, store), "已立即取消对方的管理权限")

    @router.post("/remote-management/incoming/{request_id}/restore")
    async def restore(request_id: str):
        item = store.set_incoming_status(request_id, STATUS_APPROVED)
        if item is None:
            return fail("管理请求不存在", 404)
        return ok(_public_incoming(item, store), "已恢复对方的管理权限")

    @router.delete("/remote-management/incoming/{request_id}")
    async def remove_incoming(request_id: str):
        if not store.delete_incoming(request_id):
            return fail("管理请求不存在", 404)
        return ok({"id": request_id}, "管理请求已删除")

    # ---- outgoing systems ----------------------------------------------
    @router.post("/remote-management/systems")
    async def add_system(body: ConnectBody, request: Request):
        code = (body.code or "").strip()
        url = (body.url or "").strip().rstrip("/")
        secret = ""
        target_name = ""
        if code.startswith(CONNECTION_PREFIX):
            try:
                parsed = _decode_code(code)
            except ValueError as exc:
                return fail(str(exc), 400)
            url = parsed["url"]
            secret = parsed["key"]
            target_name = parsed["name"]
        elif code:
            secret = code
        if not secret:
            return fail("请输入对方的连接密钥", 400)
        if not url:
            return fail("请输入对方系统地址（连接密钥通常已包含地址）", 400)
        if not url.startswith(("http://", "https://")):
            return fail("对方系统地址必须以 http:// 或 https:// 开头", 400)
        identity = manager_identity(store, request)
        try:
            data = await _post_public(
                url,
                "/api/remote-management/public/connect",
                secret,
                {"manager_name": identity["manager_name"], "manager_url": identity["manager_url"]},
            )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                message = "连接密钥无效或已被删除，请在对方系统重新生成密钥"
            elif status == 401:
                message = "对方账号保护拦截了请求，请确认对方已启用「远程管理」插件并重启后端"
            elif status == 404:
                message = "对方系统未安装或未启用「远程管理」插件"
            else:
                message = f"无法连接对方系统：HTTP {status}"
            return fail(message, 502)
        except Exception as exc:
            return fail(f"无法连接对方系统：{type(exc).__name__}: {exc}", 502)
        request_id = str(data.get("request_id") or "")
        if not request_id:
            return fail("对方系统未返回管理请求编号", 502)
        record = {
            "id": secrets.token_hex(6),
            "name": (body.name or "").strip()[:64] or target_name or f"远程系统 {url}",
            "url": url,
            "secret": secret,
            "connection_code": _encode_code(url, secret, target_name),
            "request_id": request_id,
            "status": str(data.get("status") or STATUS_PENDING),
            "remote_token": "",
            "enabled": True,
            "target_name": target_name,
            "target_id": str(data.get("instance_id") or ""),
            "created_at": _now(),
            "last_checked": _now(),
            "last_error": "",
        }
        saved = store.upsert_outgoing(record)
        return ok(_public_outgoing(saved), "管理请求已发送，等待对方批准")

    @router.post("/remote-management/systems/refresh")
    async def refresh_systems():
        systems = [item for item in store.read()["outgoing"] if item.get("enabled", True)]
        if systems:
            await asyncio.gather(*(refresh_one(item) for item in systems))
        return ok([_public_outgoing(item) for item in store.read()["outgoing"]])

    @router.get("/remote-management/systems/{system_id}")
    async def system_detail(system_id: str):
        item = store.get_outgoing(system_id)
        if item is None:
            return fail("被管理系统不存在", 404)
        return ok(_public_outgoing(item, with_token=True))

    @router.post("/remote-management/systems/{system_id}/refresh")
    async def refresh_system(system_id: str):
        item = store.get_outgoing(system_id)
        if item is None:
            return fail("被管理系统不存在", 404)
        item = await refresh_one(item)
        return ok(_public_outgoing(item, with_token=True))

    @router.post("/remote-management/systems/{system_id}/pause")
    async def pause_system(system_id: str):
        item = store.update_outgoing(system_id, {"enabled": False, "paused_at": _now()})
        if item is None:
            return fail("被管理系统不存在", 404)
        return ok(_public_outgoing(item, with_token=True), "已暂停管理")

    @router.post("/remote-management/systems/{system_id}/resume")
    async def resume_system(system_id: str):
        item = store.update_outgoing(system_id, {"enabled": True})
        if item is None:
            return fail("被管理系统不存在", 404)
        item = await refresh_one(item)
        return ok(_public_outgoing(item, with_token=True), "已恢复管理")

    @router.post("/remote-management/systems/{system_id}/disconnect")
    async def disconnect_system(system_id: str):
        item = store.get_outgoing(system_id)
        if item is None:
            return fail("被管理系统不存在", 404)
        request_id = str(item.get("request_id") or "")
        if request_id:
            try:
                await _post_public(
                    str(item.get("url") or ""),
                    f"/api/remote-management/public/requests/{request_id}/disconnect",
                    str(item.get("secret") or ""),
                    {},
                )
            except Exception:
                pass
        item = store.update_outgoing(system_id, {"status": STATUS_REVOKED, "remote_token": ""})
        return ok(_public_outgoing(item or {}), "已取消管理授权")

    @router.delete("/remote-management/systems/{system_id}")
    async def remove_system(system_id: str):
        item = store.get_outgoing(system_id)
        if item is None:
            return fail("被管理系统不存在", 404)
        request_id = str(item.get("request_id") or "")
        if request_id:
            try:
                await _post_public(
                    str(item.get("url") or ""),
                    f"/api/remote-management/public/requests/{request_id}/disconnect",
                    str(item.get("secret") or ""),
                    {},
                )
            except Exception:
                pass
        store.delete_outgoing(system_id)
        return ok({"id": system_id}, "已移除被管理系统")

    # ---- public handshake (used by other systems) -----------------------
    @router.post("/remote-management/public/connect")
    async def public_connect(body: PublicConnectBody, request: Request):
        secret = _request_key(request) or body.key.strip()
        key = store.find_key(secret)
        if key is None:
            return fail("连接密钥无效或已被删除", 403)
        data = store.read()
        manager_name = (body.manager_name or "").strip()[:64] or "远程豪源"
        manager_url = (body.manager_url or "").strip()[:255]
        existing = next(
            (
                item
                for item in data["incoming"]
                if item.get("key_id") == key.get("id")
                and item.get("status") in {STATUS_PENDING, STATUS_APPROVED}
                and item.get("manager_url") == manager_url
            ),
            None,
        )
        item = existing or store.create_incoming(str(key.get("id")), manager_name, manager_url)
        store.touch_key(str(key.get("id")))
        return ok(
            {
                "request_id": item["id"],
                "status": item["status"],
                "instance_id": data.get("instance_id"),
                "instance_name": data.get("instance_name"),
            },
            "管理请求已发送",
        )

    @router.get("/remote-management/public/requests/{request_id}")
    async def public_request(request_id: str, request: Request):
        secret = _request_key(request)
        key = store.find_key(secret)
        item = store.get_incoming(request_id)
        if key is None or item is None or item.get("key_id") != key.get("id"):
            return fail("管理请求不存在", 404)
        data = store.read()
        payload = {
            "request_id": item["id"],
            "status": item.get("status"),
            "instance_id": data.get("instance_id"),
            "instance_name": data.get("instance_name"),
            "remote_token": "",
        }
        if item.get("status") == STATUS_APPROVED:
            current = item
            if not current.get("token"):
                current = store.set_incoming_status(request_id, STATUS_APPROVED) or current
            payload["remote_token"] = str(current.get("token") or "")

        def mutate(state: dict[str, Any]) -> None:
            for entry in state["incoming"]:
                if entry.get("id") == request_id:
                    entry["last_seen_at"] = _now()

        store.update(mutate)
        return ok(payload)

    @router.post("/remote-management/public/requests/{request_id}/disconnect")
    async def public_disconnect(request_id: str, request: Request):
        secret = _request_key(request)
        key = store.find_key(secret)
        item = store.get_incoming(request_id)
        if key is None or item is None or item.get("key_id") != key.get("id"):
            return fail("管理请求不存在", 404)
        store.set_incoming_status(request_id, STATUS_REVOKED, by="manager")
        return ok({"request_id": request_id, "status": STATUS_REVOKED}, "管理授权已取消")

    return router


def register(ctx) -> None:
    store = RemoteStore(STATE_PATH)
    store.ensure()
    _ACTIVE["value"] = True
    ctx.add_router(build_router(store))
    ctx.add_middleware(RemoteAccessMiddleware, state_path=str(STATE_PATH))

    def on_toggle(name: str, enabled: bool) -> None:
        if name == ctx.name:
            _ACTIVE["value"] = bool(enabled)

    ctx.on("plugin.toggled", on_toggle)
    ctx.log(f"remote management ready ({STATE_PATH})")


async def startup(ctx) -> None:
    data = RemoteStore(STATE_PATH).read()
    ctx.log(f"remote management active: {len(data.get('keys', []))} key(s), {len(data.get('incoming', []))} incoming, {len(data.get('outgoing', []))} managed")


async def shutdown(ctx) -> None:
    ctx.log("remote management stopped")
