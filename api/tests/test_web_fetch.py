from __future__ import annotations

import asyncio

from harness import webfetch


def test_html_to_text_strips_markup_and_scripts():
    html = (
        "<html><head><title>T</title><style>.a{color:red}</style></head>"
        "<body><script>var x = 1;</script><h1>标题</h1><p>Hello <b>world</b></p></body></html>"
    )
    text = webfetch.html_to_text(html)
    assert "标题" in text
    assert "Hello" in text and "world" in text
    assert "var x" not in text
    assert "color:red" not in text


def test_clip_keeps_head_and_tail():
    text = "a" * 1000 + "MIDDLE" + "b" * 1000
    clipped, was_clipped = webfetch._clip(text, 400)
    assert was_clipped
    assert len(clipped) < len(text)
    assert clipped.startswith("a")
    assert clipped.rstrip().endswith("b")


def test_validate_url_blocks_private_and_bad_schemes():
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1:8030/",
        "http://localhost/",
        "http://[::1]/",
    ):
        try:
            webfetch._validate_url(url)
        except ValueError:
            continue
        raise AssertionError(f"expected {url} to be rejected")


def test_fetch_returns_error_text_for_blocked_host():
    result = asyncio.run(webfetch.fetch("http://127.0.0.1:8030/"))
    assert result.startswith("[web_fetch] error:")
