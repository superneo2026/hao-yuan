from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from extensions.system import discover_models


class _ModelsHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, "dict[str, str]"]] = []

    def do_GET(self):  # noqa: N802 - http.server 约定
        cls = type(self)
        cls.calls.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        if self.path.startswith("/v1/models") and "after_id" in self.path:
            payload = {
                "data": [{"id": "claude-old", "created_at": "2025-01-01T00:00:00Z"}],
                "has_more": False,
            }
        elif self.path.startswith("/v1/models"):
            payload = {
                "data": [
                    {"id": "claude-old", "created_at": "2025-01-01T00:00:00Z"},
                    {"id": "claude-new", "created_at": "2026-01-01T00:00:00Z"},
                ],
                "has_more": True,
                "last_id": "claude-new",
            }
        elif self.path.startswith("/openai/models"):
            payload = {
                "data": [
                    {"id": "gpt-4.1", "created": 100},
                    {"id": "gpt-5", "created": 300},
                    {"id": "text-embedding-3-large", "created": 200},
                ]
            }
        elif self.path.startswith("/relay/models"):
            payload = {
                "data": [
                    {
                        "id": "chat-model",
                        "supported_endpoints": ["/v1/chat/completions"],
                        "architecture": {"output_modalities": ["text"]},
                    },
                    {
                        "id": "image-only",
                        "supported_endpoints": ["/v1/images/generations"],
                        "architecture": {"output_modalities": ["image"]},
                    },
                    {
                        "id": "responses-only",
                        "supported_endpoints": ["/v1/responses"],
                        "architecture": {"output_modalities": ["text"]},
                    },
                    {
                        "id": "pixverse-v6-max",
                        "supported_endpoints": ["/v1/chat/completions"],
                    },
                    {"id": "nano-banana-2"},
                    {"id": "text-embedding-3-small"},
                ]
            }
        else:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_discover_models_closed_loop():
    _ModelsHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), _ModelsHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        anthropic = asyncio.run(
            discover_models({"base_url": f"{base}/v1", "api_key": "sk-claude", "provider": "claude"})
        )
        assert anthropic["code"] == 200
        assert anthropic["data"]["models"] == ["claude-new", "claude-old"]
        first_path, first_headers = _ModelsHandler.calls[0]
        assert "limit=1000" in first_path
        assert first_headers.get("x-api-key") == "sk-claude"
        assert "anthropic-version" in first_headers
        assert "authorization" not in first_headers

        openai = asyncio.run(
            discover_models({"base_url": f"{base}/openai", "api_key": "sk-openai", "provider": "openai"})
        )
        assert openai["code"] == 200
        assert openai["data"]["models"] == ["gpt-5", "gpt-4.1"]
        _, openai_headers = _ModelsHandler.calls[-1]
        assert openai_headers.get("authorization") == "Bearer sk-openai"
    finally:
        server.shutdown()


def test_discover_models_filters_non_chat_models():
    _ModelsHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), _ModelsHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        relay = asyncio.run(
            discover_models({"base_url": f"{base}/relay", "api_key": "sk-relay", "provider": "relay"})
        )
        assert relay["code"] == 200
        assert relay["data"]["models"] == ["chat-model"]
    finally:
        server.shutdown()
