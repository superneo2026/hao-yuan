"""Read-only HTTP GET used by the ``web_fetch`` tool.

Research/plan tasks used to have no way to verify external facts (licenses,
model specs, dataset sizes); the agent either guessed or wrote "unverified".
This module fetches a *public* URL and returns readable text. Private and
loopback addresses are refused so the tool cannot be pointed at local services.
"""
from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any

import httpx

from configs.configs import WEB_FETCH_MAX_BYTES, WEB_FETCH_MAX_CHARS, WEB_FETCH_TIMEOUT

_SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "nav", "pre", "blockquote", "hr",
    }
)
_TEXT_TYPES = ("text/html", "application/xhtml", "text/plain", "application/json", "text/markdown",
               "application/xml", "text/xml", "text/csv")
_MAX_REDIRECTS = 4


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Extractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if match:
        parser.title = re.sub(r"\s+", " ", match.group(1)).strip()
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clip(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return text[:head] + "\n...[middle omitted]...\n" + text[-tail:], True


def _host_is_public(host: str) -> bool:
    if not host:
        return False
    if host.lower() in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    if not addresses:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%")[0])
        except ValueError:
            return False
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            return False
    return True


def _validate_url(url: str) -> tuple[str, str]:
    match = re.match(r"^(https?)://([^/\s?#]+)([^\s]*)$", url.strip(), re.I)
    if not match:
        raise ValueError("only absolute http:// and https:// URLs are supported")
    scheme = match.group(1).lower()
    host = match.group(2)
    # strip credentials / port
    host = host.rsplit("@", 1)[-1].split(":", 1)[0].strip("[]")
    if not _host_is_public(host):
        raise ValueError("refusing to fetch a private, loopback or unresolvable host")
    return scheme, host


async def fetch(url: str, max_chars: int | None = None, timeout: float | None = None) -> str:
    """Fetch a public URL and return readable text clipped to ``max_chars``.

    Errors are returned as text (prefixed with ``[web_fetch]``) instead of
    raising so the model sees an actionable message and can label the fact
    as unverified.
    """
    max_chars = int(max_chars or WEB_FETCH_MAX_CHARS)
    timeout = float(timeout or WEB_FETCH_TIMEOUT)
    try:
        _validate_url(url)
    except ValueError as exc:
        return f"[web_fetch] error: {exc}"
    current = url.strip()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0 (compatible; HaoYuan/1.0; +web_fetch)"},
        ) as client:
            status = 0
            content_type = ""
            body = b""
            for _hop in range(_MAX_REDIRECTS + 1):
                try:
                    _validate_url(current)
                except ValueError as exc:
                    return f"[web_fetch] error: redirect to a blocked host ({exc})"
                async with client.stream("GET", current) as response:
                    status = response.status_code
                    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if status in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            break
                        current = str(httpx.URL(current).join(location))
                        continue
                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > WEB_FETCH_MAX_BYTES:
                            break
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    break
    except (httpx.HTTPError, asyncio.TimeoutError, OSError) as exc:
        return f"[web_fetch] error: request failed ({type(exc).__name__}: {exc})"
    if status >= 400:
        return f"[web_fetch] error: HTTP {status} from {current}"
    if not content_type.startswith(_TEXT_TYPES):
        return f"[web_fetch] {current} returned binary content ({content_type or 'unknown'}); not extracted"
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        decoded = body.decode("utf-8", errors="replace")
    if content_type.startswith("text/html") or content_type.startswith("application/xhtml"):
        text = html_to_text(decoded)
    else:
        text = decoded
    text, clipped = _clip(text, max_chars)
    note = f", clipped to {max_chars} chars" if clipped else ""
    return f"[web_fetch] {current} (HTTP {status}, {content_type}{note})\n\n{text}"
