from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from adapters.providers.deepseek import DeepSeekProvider
from configs.models import ProviderConfig

SSE_BODY = (
    'data: {"choices":[{"delta":{"reasoning_content":"think"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}\n\n'
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    'data: {"usage":{"prompt_tokens":3,"completion_tokens":4}}\n\n'
    'data: [DONE]\n\n'
).encode()


class _TemperatureHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            payload = {}
        type(self).requests.append(payload)
        if "temperature" in payload:
            body = json.dumps(
                {"error": {"message": "invalid temperature: only 1 is allowed for this model"}}
            ).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(SSE_BODY)))
        self.end_headers()
        self.wfile.write(SSE_BODY)

    def log_message(self, *args):
        pass


def test_provider_retries_without_temperature():
    _TemperatureHandler.requests = []
    server = HTTPServer(("127.0.0.1", 0), _TemperatureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    conf = ProviderConfig(
        name="kimi",
        base_url=f"http://127.0.0.1:{server.server_address[1]}",
        models=["kimi-k3.1-pro"],
        default_model="kimi-k3.1-pro",
        api_key="sk-test",
        supports_thinking=False,
    )

    async def run() -> dict:
        provider = DeepSeekProvider()
        events = []
        try:
            async for event in provider.stream(
                [{"role": "user", "content": "hi"}], [], conf, "kimi-k3.1-pro", ""
            ):
                events.append(event)
        finally:
            await provider.aclose()
        return next(event for event in events if event.get("type") == "message")

    try:
        message = asyncio.run(run())
    finally:
        server.shutdown()
    assert message["message"]["content"] == "你好"
    assert message["message"]["reasoning_content"] == "think"
    assert len(_TemperatureHandler.requests) == 2
    assert "temperature" in _TemperatureHandler.requests[0]
    assert "temperature" not in _TemperatureHandler.requests[1]
