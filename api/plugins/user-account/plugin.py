from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from configs.configs import DATA_DIR, prefix
from extensions.common import fail, ok

COOKIE_NAME = "haoyuan_session"
TOKEN_TTL = 7 * 24 * 3600
PBKDF2_ITERATIONS = 210_000
MAX_FAILURES = 5
LOCK_SECONDS = 5 * 60
STATE_PATH = DATA_DIR / "user_account.json"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _hash_password(password: str, salt: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()


class AuthStore:
    """基于本地 JSON 的账号存储，避免把密码或配置写进插件目录。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "configured": False,
            "username": "",
            "salt": "",
            "password_hash": "",
            "iterations": PBKDF2_ITERATIONS,
            "secret": secrets.token_hex(32),
            "created_at": "",
            "updated_at": "",
        }

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        base = self._empty()
        if isinstance(data, dict):
            base.update(data)
        base["enabled"] = bool(base.get("enabled", True))
        base["configured"] = bool(base.get("configured")) and bool(base.get("password_hash"))
        return base

    def read(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.is_file():
                return self._empty()
            try:
                return self._normalize(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return self._empty()

    def write(self, data: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._normalize(data)
            payload["updated_at"] = _now()
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def ensure(self) -> dict[str, Any]:
        with self._lock:
            if self.path.is_file():
                return self.read()
            data = self._empty()
            data["created_at"] = _now()
            self.write(data)
            return data

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            data = self.read()
            data["enabled"] = bool(enabled)
            self.write(data)

    def gate(self) -> dict[str, Any]:
        data = self.read()
        configured = bool(data.get("configured"))
        enabled = bool(data.get("enabled"))
        return {
            "enabled": enabled,
            "configured": configured,
            "locked": enabled and configured,
            "username": data.get("username", ""),
        }

    def setup(self, username: str, password: str) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            if data.get("configured"):
                raise ValueError("account already configured")
            salt = secrets.token_hex(16)
            data.update(
                {
                    "enabled": True,
                    "configured": True,
                    "username": username,
                    "salt": salt,
                    "password_hash": _hash_password(password, salt),
                    "iterations": PBKDF2_ITERATIONS,
                    "secret": data.get("secret") or secrets.token_hex(32),
                    "created_at": _now(),
                }
            )
            self.write(data)
            return data

    def verify(self, username: str, password: str) -> bool:
        data = self.read()
        if not data.get("configured"):
            return False
        if not hmac.compare_digest(str(data.get("username", "")), username):
            return False
        expected = _hash_password(password, str(data.get("salt", "")), int(data.get("iterations") or PBKDF2_ITERATIONS))
        return hmac.compare_digest(str(data.get("password_hash", "")), expected)

    def change(self, current_password: str, username: str, new_password: str) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            if not self.verify(str(data.get("username", "")), current_password):
                raise ValueError("current password is incorrect")
            if username:
                data["username"] = username
            if new_password:
                salt = secrets.token_hex(16)
                data["salt"] = salt
                data["password_hash"] = _hash_password(new_password, salt)
                data["iterations"] = PBKDF2_ITERATIONS
            data["secret"] = secrets.token_hex(32)
            self.write(data)
            return data

    def issue_token(self, username: str) -> str:
        data = self.read()
        secret = str(data.get("secret") or "")
        if not secret:
            secret = secrets.token_hex(32)
            data["secret"] = secret
            self.write(data)
        payload = {"u": username, "exp": int(time.time()) + TOKEN_TTL, "n": secrets.token_hex(8)}
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        return f"{_b64(raw)}.{_b64(signature)}"

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
            expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        if str(payload.get("u") or "") != str(data.get("username") or ""):
            return None
        return payload


def _cookie_token(header_value: str) -> str:
    if not header_value:
        return ""
    for part in header_value.split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE_NAME:
            return value.strip()
    return ""


def _token_from_headers(headers: dict[str, str], query: dict[str, list[str]]) -> str:
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    token = headers.get("x-haoyuan-token", "").strip()
    if token:
        return token
    cookie = _cookie_token(headers.get("cookie", ""))
    if cookie:
        return cookie
    values = query.get("token") or []
    return values[0].strip() if values else ""


def _is_gated(path: str) -> bool:
    if path in {"/api", "/api/", "/api/health", "/api/health/"}:
        return False
    if path == "/api/auth" or path.startswith("/api/auth/"):
        return False
    if path.startswith("/api/"):
        return True
    return path == "/ws" or path.startswith("/ws/")


class AuthGateMiddleware:
    """全局访问门禁：插件启用且已设置账密后，拦截未登录的 API / WebSocket。"""

    def __init__(self, app, state_path: str):
        self.app = app
        self.store = AuthStore(Path(state_path))

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not _is_gated(path):
            return await self.app(scope, receive, send)
        gate = self.store.gate()
        if not gate["locked"]:
            return await self.app(scope, receive, send)
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = _token_from_headers(headers, query)
        if token and self.store.verify_token(token):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401})
            return
        body = json.dumps(
            {
                "code": 401,
                "data": {"authenticated": False, "enabled": True, "configured": True},
                "message": "Authentication required",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class SetupBody(BaseModel):
    username: str = ""
    password: str = ""


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


class ChangeBody(BaseModel):
    current_password: str = ""
    username: str = ""
    new_password: str = ""


def _clean_username(value: str) -> str:
    username = (value or "").strip()
    if not 2 <= len(username) <= 32:
        raise ValueError("用户名长度需为 2-32 个字符")
    if any(char.isspace() for char in username):
        raise ValueError("用户名不能包含空格")
    return username


def _clean_password(value: str) -> str:
    password = value or ""
    if not 6 <= len(password) <= 128:
        raise ValueError("密码长度需为 6-128 个字符")
    return password


def _format_wait(seconds: float) -> str:
    total = max(1, int(seconds + 0.999))
    minutes, rest = divmod(total, 60)
    if minutes and rest:
        return f"{minutes} 分 {rest} 秒"
    if minutes:
        return f"{minutes} 分钟"
    return f"{rest} 秒"


def build_router(store: AuthStore) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["user-account"])
    failures: dict[str, dict[str, float]] = {}

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "local"

    def check_lock(key: str) -> float:
        entry = failures.get(key)
        if not entry:
            return 0
        until = float(entry.get("until") or 0)
        if until > time.time():
            return until - time.time()
        if until:
            failures.pop(key, None)
        return 0

    def record_failure(key: str) -> None:
        entry = failures.setdefault(key, {"count": 0, "until": 0})
        entry["count"] = float(entry.get("count", 0)) + 1
        if entry["count"] >= MAX_FAILURES:
            entry["until"] = time.time() + LOCK_SECONDS
            entry["count"] = 0

    def token_from_request(request: Request) -> str:
        return _token_from_headers(
            {key.lower(): value for key, value in request.headers.items()},
            parse_qs(request.url.query or ""),
        )

    def set_session(response: Response, token: str) -> None:
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=TOKEN_TTL,
            httponly=True,
            samesite="lax",
            path="/",
        )

    def status_payload(request: Request) -> dict[str, Any]:
        gate = store.gate()
        payload = store.verify_token(token_from_request(request))
        return {
            **gate,
            "active": gate["locked"],
            "authenticated": bool(payload) if gate["locked"] else False,
            "username": (payload or {}).get("u", "") if payload else "",
        }

    @router.get("/auth/status")
    async def auth_status(request: Request):
        return ok(status_payload(request))

    @router.post("/auth/setup")
    async def auth_setup(body: SetupBody, request: Request, response: Response):
        gate = store.gate()
        if gate["configured"]:
            return fail("账号已设置，请直接登录", 409)
        try:
            username = _clean_username(body.username)
            password = _clean_password(body.password)
        except ValueError as exc:
            return fail(str(exc), 400)
        data = store.setup(username, password)
        token = store.issue_token(str(data["username"]))
        set_session(response, token)
        return ok({**status_payload(request), "token": token, "authenticated": True}, "账号保护已开启")

    @router.post("/auth/login")
    async def auth_login(body: LoginBody, request: Request, response: Response):
        gate = store.gate()
        if not gate["configured"]:
            return fail("尚未设置账号，请先完成初始化", 400)
        key = client_key(request)
        remaining = check_lock(key)
        if remaining > 0:
            wait = _format_wait(remaining)
            return fail(
                f"连续登录失败 {MAX_FAILURES} 次，账号已锁定，请 {wait}后重试",
                429,
                {"locked": True, "retry_after": max(1, int(remaining + 0.999))},
            )
        username = (body.username or "").strip()
        if not store.verify(username, body.password or ""):
            record_failure(key)
            return fail("用户名或密码不正确", 401)
        failures.pop(key, None)
        token = store.issue_token(str(store.read().get("username", username)))
        set_session(response, token)
        return ok({**status_payload(request), "token": token, "authenticated": True}, "登录成功")

    @router.post("/auth/logout")
    async def auth_logout(response: Response):
        response.delete_cookie(COOKIE_NAME, path="/")
        return ok({"authenticated": False}, "已退出登录")

    @router.get("/auth/me")
    async def auth_me(request: Request):
        payload = store.verify_token(token_from_request(request))
        if not payload:
            return fail("需要登录", 401)
        return ok({"authenticated": True, "username": payload.get("u", "")})

    @router.post("/auth/change")
    async def auth_change(body: ChangeBody, request: Request, response: Response):
        payload = store.verify_token(token_from_request(request))
        if not payload:
            return fail("需要登录", 401)
        try:
            username = _clean_username(body.username) if (body.username or "").strip() else ""
            new_password = _clean_password(body.new_password) if body.new_password else ""
        except ValueError as exc:
            return fail(str(exc), 400)
        if not username and not new_password:
            return fail("请至少修改用户名或密码", 400)
        try:
            data = store.change(body.current_password or "", username, new_password)
        except ValueError as exc:
            return fail(str(exc), 401)
        token = store.issue_token(str(data["username"]))
        set_session(response, token)
        return ok(
            {
                **status_payload(request),
                "username": data["username"],
                "token": token,
                "authenticated": True,
            },
            "账号信息已更新",
        )

    return router


def register(ctx) -> None:
    store = AuthStore(STATE_PATH)
    store.ensure()
    ctx.add_router(build_router(store))
    ctx.add_middleware(AuthGateMiddleware, state_path=str(STATE_PATH))

    def on_toggle(name: str, enabled: bool) -> None:
        if name == ctx.name:
            store.set_enabled(bool(enabled))

    ctx.on("plugin.toggled", on_toggle)
    ctx.log(f"user account gate ready ({STATE_PATH})")


async def startup(ctx) -> None:
    ctx.log("user account protection active" if AuthStore(STATE_PATH).gate()["locked"] else "waiting for account setup")


async def shutdown(ctx) -> None:
    ctx.log("user account protection stopped")
