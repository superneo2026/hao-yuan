from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
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
DEFAULT_MAX_FAILURES = 5
MAX_FAILURES_LIMIT = 20
LOCK_SECONDS = 5 * 60
STATE_PATH = DATA_DIR / "user_account.json"
CLI_SECRET_PATH = DATA_DIR / "cli-secret"
MAIL_PATH = DATA_DIR / "smtp.json"

RECOVERY_CODE_TTL = 10 * 60
RECOVERY_MAX_ATTEMPTS = 5
RECOVERY_RESEND_SECONDS = 60
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_cli_secret_value: str | None = None
_cli_secret_lock = threading.Lock()

_recovery_lock = threading.Lock()
_recovery: dict[str, Any] = {"code": "", "expires": 0, "attempts": 0, "last_sent": 0, "email": ""}


def cli_secret() -> str:
    """本机 CLI 的免登录密钥：只写入本地数据目录，由同机 `haoyuan` 读取后随请求发送。"""
    global _cli_secret_value
    if _cli_secret_value is not None:
        return _cli_secret_value
    with _cli_secret_lock:
        if _cli_secret_value is not None:
            return _cli_secret_value
        try:
            value = ""
            if CLI_SECRET_PATH.is_file():
                value = CLI_SECRET_PATH.read_text(encoding="utf-8").strip()
            if not value:
                value = secrets.token_hex(32)
                CLI_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
                temp = CLI_SECRET_PATH.with_suffix(".tmp")
                temp.write_text(value, encoding="utf-8")
                temp.replace(CLI_SECRET_PATH)
            try:
                os.chmod(CLI_SECRET_PATH, 0o600)
            except OSError:
                pass
            _cli_secret_value = value
        except OSError:
            _cli_secret_value = ""
        return _cli_secret_value


def _mask_email(value: str) -> str:
    email = (value or "").strip()
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if not local:
        return f"***@{domain}"
    if len(local) <= 2:
        masked = local[0] + "***"
    else:
        masked = local[0] + "***" + local[-1]
    return f"{masked}@{domain}"


def _clean_email(value: str) -> str:
    email = (value or "").strip()
    if not email or len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("请输入有效的邮箱地址")
    return email


def _mail_defaults() -> dict[str, Any]:
    return {
        "provider": "custom",
        "host": "",
        "port": 465,
        "username": "",
        "password": "",
        "sender": "",
        "security": "ssl",
        "updated_at": "",
    }


def _read_mail_file() -> dict[str, Any]:
    if not MAIL_PATH.is_file():
        return {}
    try:
        data = json.loads(MAIL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_mail(data: dict[str, Any]) -> dict[str, Any]:
    base = _mail_defaults()
    if isinstance(data, dict):
        base.update({key: data[key] for key in base if key in data})
    try:
        base["port"] = int(base.get("port") or 465)
    except (TypeError, ValueError):
        base["port"] = 465
    security = str(base.get("security") or "ssl").lower()
    base["security"] = security if security in {"ssl", "starttls", "none"} else "ssl"
    provider = str(base.get("provider") or "custom").lower()
    base["provider"] = provider if provider in {"custom", "gmail", "qq"} else "custom"
    for key in ("host", "username", "sender"):
        base[key] = str(base.get(key) or "").strip()
    base["password"] = str(base.get("password") or "")
    base["updated_at"] = str(base.get("updated_at") or "")
    return base


def _write_mail_file(data: dict[str, Any]) -> dict[str, Any]:
    payload = _normalize_mail(data)
    payload["updated_at"] = _now()
    MAIL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = MAIL_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    temp.replace(MAIL_PATH)
    return payload


def mail_settings() -> tuple[dict[str, Any], bool]:
    base = _normalize_mail(_read_mail_file())
    env_map = {
        "host": "HAOYUAN_SMTP_HOST",
        "port": "HAOYUAN_SMTP_PORT",
        "username": "HAOYUAN_SMTP_USER",
        "password": "HAOYUAN_SMTP_PASSWORD",
        "sender": "HAOYUAN_SMTP_FROM",
        "security": "HAOYUAN_SMTP_SECURITY",
    }
    env_managed = False
    for key, env_name in env_map.items():
        value = os.getenv(env_name)
        if value is not None and value.strip() != "":
            base[key] = value
            env_managed = True
    return _normalize_mail(base), env_managed


def mail_ready(settings: dict[str, Any]) -> bool:
    return bool(settings.get("host") and (settings.get("sender") or settings.get("username")))


def _send_mail(settings: dict[str, Any], to_addr: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.get("sender") or settings.get("username")
    message["To"] = to_addr
    message.set_content(body)
    host = settings["host"]
    port = int(settings.get("port") or 465)
    timeout = 15
    if settings.get("security") == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(host, port, timeout=timeout)
        server.ehlo()
        if settings.get("security") == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
    try:
        username = settings.get("username")
        if username:
            server.login(username, settings.get("password") or "")
        server.send_message(message)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


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
            "max_failures": DEFAULT_MAX_FAILURES,
            "recovery_email": "",
            "created_at": "",
            "updated_at": "",
        }

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        base = self._empty()
        if isinstance(data, dict):
            base.update(data)
        base["enabled"] = bool(base.get("enabled", True))
        base["configured"] = bool(base.get("configured")) and bool(base.get("password_hash"))
        try:
            max_failures = int(base.get("max_failures") or DEFAULT_MAX_FAILURES)
        except (TypeError, ValueError):
            max_failures = DEFAULT_MAX_FAILURES
        base["max_failures"] = max(1, min(MAX_FAILURES_LIMIT, max_failures))
        base["recovery_email"] = str(base.get("recovery_email") or "").strip()
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
            "max_failures": int(data.get("max_failures") or DEFAULT_MAX_FAILURES),
            "lock_seconds": int(LOCK_SECONDS),
        }

    def set_policy(self, max_failures: int) -> dict[str, Any]:
        try:
            value = int(max_failures)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"最多错误次数需为 1-{MAX_FAILURES_LIMIT} 之间的整数") from exc
        if not 1 <= value <= MAX_FAILURES_LIMIT:
            raise ValueError(f"最多错误次数需为 1-{MAX_FAILURES_LIMIT} 之间的整数")
        with self._lock:
            data = self.read()
            data["max_failures"] = value
            self.write(data)
        return {"max_failures": value, "lock_seconds": int(LOCK_SECONDS)}

    def setup(self, username: str, password: str, email: str = "") -> dict[str, Any]:
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
                    "recovery_email": email,
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

    def change(self, current_password: str, username: str, new_password: str, email: str = "") -> dict[str, Any]:
        with self._lock:
            data = self.read()
            if not self.verify(str(data.get("username", "")), current_password):
                raise ValueError("current password is incorrect")
            rotate = False
            if username:
                data["username"] = username
                rotate = True
            if new_password:
                salt = secrets.token_hex(16)
                data["salt"] = salt
                data["password_hash"] = _hash_password(new_password, salt)
                data["iterations"] = PBKDF2_ITERATIONS
                rotate = True
            if email:
                data["recovery_email"] = email
            if rotate:
                data["secret"] = secrets.token_hex(32)
            self.write(data)
            return data

    def reset_password(self, new_password: str) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            if not data.get("configured"):
                raise ValueError("account not configured")
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
    if path.startswith("/api/remote-management/public/"):
        return False
    if path.startswith("/api/"):
        return True
    return path == "/ws" or path.startswith("/ws/")


class AuthGateMiddleware:
    """全局访问门禁：插件启用且已设置账密后，拦截未登录的 API / WebSocket。"""

    def __init__(self, app, state_path: str):
        self.app = app
        self.store = AuthStore(Path(state_path))
        # 启动时即生成本机 CLI 免登录密钥，避免 CLI 首个请求早于文件生成
        cli_secret()

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
        cli = headers.get("x-haoyuan-cli-secret", "").strip()
        expected = cli_secret()
        if cli and expected and hmac.compare_digest(cli, expected):
            return await self.app(scope, receive, send)
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
    email: str = ""


class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


class ChangeBody(BaseModel):
    current_password: str = ""
    username: str = ""
    new_password: str = ""
    email: str = ""


class PolicyBody(BaseModel):
    max_failures: int = DEFAULT_MAX_FAILURES


class RecoveryRequestBody(BaseModel):
    identity: str = ""


class RecoveryResetBody(BaseModel):
    code: str = ""
    new_password: str = ""


class MailConfigBody(BaseModel):
    provider: str = "custom"
    host: str = ""
    port: int = 465
    username: str = ""
    password: str = ""
    sender: str = ""
    security: str = "ssl"


class MailTestBody(BaseModel):
    provider: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    sender: str = ""
    security: str = ""
    to: str = ""


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

    def record_failure(key: str, max_failures: int) -> dict[str, Any]:
        entry = failures.setdefault(key, {"count": 0, "until": 0})
        entry["count"] = float(entry.get("count", 0)) + 1
        attempts = int(entry["count"])
        if attempts >= max_failures:
            entry["until"] = time.time() + LOCK_SECONDS
            entry["count"] = 0
            return {
                "locked": True,
                "remaining_attempts": 0,
                "retry_after": int(LOCK_SECONDS),
                "max_failures": max_failures,
            }
        return {
            "locked": False,
            "remaining_attempts": max_failures - attempts,
            "retry_after": 0,
            "max_failures": max_failures,
        }

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
        data = store.read()
        recovery_email = str(data.get("recovery_email") or "")
        settings, _ = mail_settings()
        email_ready = mail_ready(settings)
        return {
            **gate,
            "active": gate["locked"],
            "authenticated": bool(payload) if gate["locked"] else False,
            "username": (payload or {}).get("u", "") if payload else "",
            "has_recovery_email": bool(recovery_email),
            "recovery_email": _mask_email(recovery_email),
            "email_configured": email_ready,
            "recovery_available": bool(gate["configured"] and recovery_email and email_ready),
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
            email = _clean_email(body.email) if (body.email or "").strip() else ""
        except ValueError as exc:
            return fail(str(exc), 400)
        data = store.setup(username, password, email)
        token = store.issue_token(str(data["username"]))
        set_session(response, token)
        return ok({**status_payload(request), "token": token, "authenticated": True}, "账号保护已开启")

    @router.post("/auth/login")
    async def auth_login(body: LoginBody, request: Request, response: Response):
        gate = store.gate()
        if not gate["configured"]:
            return fail("尚未设置账号，请先完成初始化", 400)
        key = client_key(request)
        max_failures = int(gate.get("max_failures") or DEFAULT_MAX_FAILURES)
        remaining = check_lock(key)
        if remaining > 0:
            wait = _format_wait(remaining)
            return fail(
                f"连续登录失败 {max_failures} 次，账号已锁定，请 {wait}后重试",
                429,
                {
                    "locked": True,
                    "retry_after": max(1, int(remaining + 0.999)),
                    "max_failures": max_failures,
                },
            )
        username = (body.username or "").strip()
        if not store.verify(username, body.password or ""):
            result = record_failure(key, max_failures)
            if result["locked"]:
                return fail(
                    f"连续登录失败 {max_failures} 次，账号已锁定，请 {_format_wait(result['retry_after'])}后重试",
                    429,
                    result,
                )
            return fail(
                f"用户名或密码不正确，还可尝试 {result['remaining_attempts']} 次",
                401,
                result,
            )
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

    @router.put("/auth/policy")
    async def auth_policy(body: PolicyBody, request: Request):
        payload = store.verify_token(token_from_request(request))
        if not payload:
            return fail("需要登录", 401)
        try:
            policy = store.set_policy(body.max_failures)
        except ValueError as exc:
            return fail(str(exc), 400)
        failures.clear()
        return ok(
            {**status_payload(request), **policy, "authenticated": True},
            "安全策略已更新",
        )

    @router.post("/auth/change")
    async def auth_change(body: ChangeBody, request: Request, response: Response):
        payload = store.verify_token(token_from_request(request))
        if not payload:
            return fail("需要登录", 401)
        try:
            username = _clean_username(body.username) if (body.username or "").strip() else ""
            new_password = _clean_password(body.new_password) if body.new_password else ""
            email = _clean_email(body.email) if (body.email or "").strip() else ""
        except ValueError as exc:
            return fail(str(exc), 400)
        if not username and not new_password and not email:
            return fail("请至少修改用户名、密码或找回邮箱", 400)
        try:
            data = store.change(body.current_password or "", username, new_password, email)
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

    def authed(request: Request) -> bool:
        return bool(store.verify_token(token_from_request(request)))

    def mail_public(settings: dict[str, Any], env_managed: bool) -> dict[str, Any]:
        return {
            "provider": settings.get("provider") or "custom",
            "host": settings.get("host") or "",
            "port": int(settings.get("port") or 465),
            "username": settings.get("username") or "",
            "sender": settings.get("sender") or "",
            "security": settings.get("security") or "ssl",
            "has_password": bool(settings.get("password")),
            "configured": mail_ready(settings),
            "env_managed": env_managed,
            "updated_at": settings.get("updated_at") or "",
        }

    @router.get("/auth/email")
    async def auth_email_get(request: Request):
        if not authed(request):
            return fail("需要登录", 401)
        settings, env_managed = mail_settings()
        return ok(mail_public(settings, env_managed))

    @router.put("/auth/email")
    async def auth_email_put(body: MailConfigBody, request: Request):
        if not authed(request):
            return fail("需要登录", 401)
        provider = (body.provider or "custom").strip().lower()
        username = (body.username or "").strip()
        sender = (body.sender or "").strip()
        if provider in {"qq", "gmail"} and username and "@" not in username:
            return fail("QQ/Gmail 的 SMTP 用户名需填写完整邮箱地址", 400)
        if sender and "@" not in sender:
            return fail("发件人邮箱需填写完整邮箱地址", 400)
        if provider in {"qq", "gmail"} and not sender:
            return fail("请填写发件人邮箱", 400)
        current = _normalize_mail(_read_mail_file())
        current.update(
            {
                "provider": provider,
                "host": (body.host or "").strip(),
                "port": body.port or 465,
                "username": username,
                "sender": sender,
                "security": (body.security or "ssl").strip().lower(),
            }
        )
        if body.password:
            current["password"] = body.password
        _write_mail_file(current)
        settings, env_managed = mail_settings()
        return ok(mail_public(settings, env_managed), "邮件设置已保存")

    @router.post("/auth/email/test")
    async def auth_email_test(body: MailTestBody, request: Request):
        if not authed(request):
            return fail("需要登录", 401)
        saved, _ = mail_settings()
        # 优先使用前端传来的“当前表单值”测试；未传字段时回退到已保存配置。
        provided = any(
            [
                (body.host or "").strip(),
                (body.sender or "").strip(),
                (body.username or "").strip(),
                (body.provider or "").strip(),
                (body.security or "").strip(),
                body.port,
            ]
        )
        if provided:
            settings = {
                "provider": (body.provider or saved.get("provider") or "custom").strip().lower(),
                "host": (body.host or "").strip(),
                "port": body.port or int(saved.get("port") or 465),
                "username": (body.username or "").strip(),
                "sender": (body.sender or "").strip(),
                "security": (body.security or saved.get("security") or "ssl").strip().lower(),
                "password": saved.get("password") or "",
                "updated_at": saved.get("updated_at") or "",
            }
            if body.password and body.password != "********":
                settings["password"] = body.password
        else:
            settings = saved
        if not mail_ready(settings):
            return fail("请先填写 SMTP 服务器、用户名和发件人邮箱", 400)
        recovery_email = str(store.read().get("recovery_email") or "")
        to_addr = (body.to or "").strip() or recovery_email or settings.get("sender") or settings.get("username") or ""
        try:
            to_addr = _clean_email(to_addr)
        except ValueError as exc:
            return fail(str(exc), 400)
        try:
            await asyncio.to_thread(
                _send_mail,
                settings,
                to_addr,
                "豪源邮件服务测试",
                "这是一封来自豪源的测试邮件，说明邮件发送服务配置成功。",
            )
        except Exception:
            return fail("测试邮件发送失败，请检查 SMTP 配置", 502)
        return ok({"to": _mask_email(to_addr)}, "测试邮件已发送")

    @router.post("/auth/recovery/request")
    async def auth_recovery_request(body: RecoveryRequestBody):
        data = store.read()
        if not data.get("configured"):
            return fail("尚未设置账号", 400)
        settings, _ = mail_settings()
        if not mail_ready(settings):
            return fail(
                "邮件服务尚未配置，请登录后在「账号与安全」中设置 SMTP",
                400,
                {"reason": "email_not_configured"},
            )
        recovery_email = str(data.get("recovery_email") or "")
        if not recovery_email:
            return fail(
                "该账号尚未预留找回密码邮箱，请先登录设置",
                400,
                {"reason": "no_recovery_email"},
            )
        identity = (body.identity or "").strip()
        if not identity:
            return fail("请输入用户名或邮箱", 400)
        matched = identity == str(data.get("username") or "") or identity.lower() == recovery_email.lower()
        if not matched:
            return fail("用户名与预留邮箱不匹配", 400, {"reason": "mismatch"})
        now = time.time()
        with _recovery_lock:
            last_sent = float(_recovery.get("last_sent") or 0)
            if last_sent and now - last_sent < RECOVERY_RESEND_SECONDS:
                wait = int(RECOVERY_RESEND_SECONDS - (now - last_sent)) + 1
                return fail(f"请 {wait} 秒后再试", 429, {"retry_after": wait})
            code = _generate_code()
            _recovery.update(
                {
                    "code": code,
                    "expires": now + RECOVERY_CODE_TTL,
                    "attempts": 0,
                    "last_sent": now,
                    "email": recovery_email,
                }
            )
        text = (
            "你正在找回豪源账号的登录密码。\n\n"
            f"验证码：{code}\n"
            f"有效期：{RECOVERY_CODE_TTL // 60} 分钟。\n\n"
            "如非本人操作，请忽略本邮件，并尽快修改密码。"
        )
        try:
            await asyncio.to_thread(_send_mail, settings, recovery_email, "豪源账号找回密码验证码", text)
        except Exception:
            with _recovery_lock:
                _recovery.update({"code": "", "expires": 0, "attempts": 0, "last_sent": 0})
            return fail("验证码邮件发送失败，请检查邮件服务配置", 502)
        return ok(
            {
                "email": _mask_email(recovery_email),
                "expires_in": RECOVERY_CODE_TTL,
                "resend_after": RECOVERY_RESEND_SECONDS,
            },
            "验证码已发送",
        )

    @router.post("/auth/recovery/reset")
    async def auth_recovery_reset(body: RecoveryResetBody, request: Request, response: Response):
        try:
            new_password = _clean_password(body.new_password)
        except ValueError as exc:
            return fail(str(exc), 400)
        code = (body.code or "").strip()
        if not code:
            return fail("请输入验证码", 400)
        now = time.time()
        with _recovery_lock:
            if not _recovery.get("code") or not _recovery.get("expires"):
                return fail("请先获取验证码", 400, {"reason": "expired"})
            if now > float(_recovery.get("expires") or 0):
                _recovery.update({"code": "", "expires": 0, "attempts": 0})
                return fail("验证码已失效，请重新获取", 400, {"reason": "expired"})
            if int(_recovery.get("attempts") or 0) >= RECOVERY_MAX_ATTEMPTS:
                return fail("验证码错误次数过多，请重新获取", 429, {"reason": "too_many"})
            if not hmac.compare_digest(str(_recovery.get("code") or ""), code):
                _recovery["attempts"] = int(_recovery.get("attempts") or 0) + 1
                remaining = max(0, RECOVERY_MAX_ATTEMPTS - int(_recovery["attempts"]))
                if remaining == 0:
                    _recovery.update({"code": "", "expires": 0, "attempts": 0})
                    return fail("验证码错误次数过多，请重新获取", 429, {"reason": "too_many"})
                return fail(f"验证码不正确，还可尝试 {remaining} 次", 401, {"remaining_attempts": remaining})
            _recovery.update({"code": "", "expires": 0, "attempts": 0, "last_sent": 0})
        try:
            data = store.reset_password(new_password)
        except ValueError as exc:
            return fail(str(exc), 400)
        failures.pop(client_key(request), None)
        token = store.issue_token(str(data["username"]))
        set_session(response, token)
        return ok(
            {**status_payload(request), "token": token, "authenticated": True},
            "密码已重置，请使用新密码登录",
        )

    return router


def register(ctx) -> None:
    store = AuthStore(STATE_PATH)
    store.ensure()
    cli_secret()
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
