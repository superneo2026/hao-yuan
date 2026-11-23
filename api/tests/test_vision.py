from __future__ import annotations

import asyncio
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from configs.models import ProviderConfig
from harness import vision
from tools import dev

from tests.test_tools import ctx_for

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
)


def _provider(**kwargs) -> ProviderConfig:
    return ProviderConfig(
        name="fake",
        base_url="https://example.test/v1",
        models=["fake-vl"] if kwargs.get("vision") else ["fake-text"],
        default_model="fake-vl" if kwargs.get("vision") else "fake-text",
        api_key="sk-test",
        supports_vision=bool(kwargs.get("vision")),
    )


def test_vision_mode_native(monkeypatch):
    conf = _provider(vision=True)
    monkeypatch.setattr(vision, "resolve", lambda provider, model: ("fake", "fake-vl"))
    monkeypatch.setattr(vision, "PROVIDERS", {"fake": conf})
    monkeypatch.setattr(vision, "sidecar_config", lambda: None)
    assert vision.vision_mode({}) == "native"


def test_vision_mode_sidecar(monkeypatch):
    conf = _provider(vision=False)
    monkeypatch.setattr(vision, "resolve", lambda provider, model: ("fake", "fake-text"))
    monkeypatch.setattr(vision, "PROVIDERS", {"fake": conf})
    monkeypatch.setattr(vision, "sidecar_config", lambda: {"base_url": "x", "api_key": "k", "model": "qwen-vl-max"})
    assert vision.vision_mode({}) == "sidecar"


def test_vision_mode_none(monkeypatch):
    conf = _provider(vision=False)
    monkeypatch.setattr(vision, "resolve", lambda provider, model: ("fake", "fake-text"))
    monkeypatch.setattr(vision, "PROVIDERS", {"fake": conf})
    monkeypatch.setattr(vision, "sidecar_config", lambda: None)
    assert vision.vision_mode({}) == "none"


def test_native_attachment_message_builds_image_part(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(_PNG)
    result = {"mode": "native", "path": str(image), "prompt": "check layout"}
    content = vision.native_attachment_message(result, str(tmp_path))
    assert content is not None
    assert content[0]["type"] == "text"
    assert "check layout" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_native_attachment_message_rejects_outside_workspace(tmp_path):
    image = tmp_path / "shot.png"
    image.write_bytes(_PNG)
    other = tmp_path / "other"
    other.mkdir()
    result = {"mode": "native", "path": str(image), "prompt": "x"}
    assert vision.native_attachment_message(result, str(other)) is None


def test_describe_image_none_is_text_only(tmp_path, monkeypatch):
    image = tmp_path / "shot.png"
    image.write_bytes(_PNG)
    monkeypatch.setattr(vision, "vision_mode", lambda session: "none")
    result = asyncio.run(dev.describe_image(ctx_for(tmp_path), {"path": "shot.png"}))
    assert "多模态能力未配置" in result


def test_describe_image_native_returns_attachment_result(tmp_path, monkeypatch):
    image = tmp_path / "shot.png"
    image.write_bytes(_PNG)
    monkeypatch.setattr(vision, "vision_mode", lambda session: "native")
    result = asyncio.run(dev.describe_image(ctx_for(tmp_path), {"path": "shot.png"}))
    assert isinstance(result, dict)
    assert result["mode"] == "native"
    assert vision.native_attachment_message(result, str(tmp_path)) is not None


class _VLHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_POST(self):  # noqa: N802 - http.server convention
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        type(self).calls.append({"path": self.path, "payload": payload, "auth": self.headers.get("authorization")})
        response = json.dumps({"choices": [{"message": {"content": "a red button"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass


def test_sidecar_describe_calls_qwen_vl(tmp_path, monkeypatch):
    _VLHandler.calls = []
    server = HTTPServer(("127.0.0.1", 0), _VLHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    image = tmp_path / "shot.png"
    image.write_bytes(_PNG)
    monkeypatch.setattr(vision, "PROVIDERS", {})
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-vl")
    monkeypatch.setenv("HAOYUAN_VL_BASE_URL", base)
    monkeypatch.setenv("HAOYUAN_VL_MODEL", "qwen-vl-max")
    try:
        text = asyncio.run(vision.describe_via_sidecar(str(image), "what is this?"))
        assert text == "a red button"
        assert _VLHandler.calls
        call = _VLHandler.calls[-1]
        assert call["path"] == "/chat/completions"
        assert call["auth"] == "Bearer sk-vl"
        assert call["payload"]["model"] == "qwen-vl-max"
        content = call["payload"]["messages"][0]["content"]
        assert content[0]["type"] == "image_url"
        assert content[1]["type"] == "text"
    finally:
        server.shutdown()
