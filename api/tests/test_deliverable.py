from __future__ import annotations

import os

from harness import deliverable


PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><title>t</title></head>
<body>
<div id="s1" class="sec">one</div>
<div id="s2" class="sec">two</div>
<nav><a href="#s1">1</a><a href="#s2">2</a><a href="#s3">3</a></nav>
{body}
</body></html>
"""


def _write(tmp_path, name, html):
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return str(path)


def test_html_report_finds_dead_anchors_and_visible_text(tmp_path):
    path = _write(tmp_path, "a.html", PAGE.format(body="<p>" + "正文内容 " * 600 + "</p>"))
    report = deliverable.html_report(path)
    assert report["dead_anchors"] == ["s3"]
    assert report["resolved_anchors"] == 2
    assert report["visible_chars"] > 2000
    assert report["closed"] is True
    assert report["mismatches"] == []


def test_completeness_flags_unclosed_and_thin_pages(tmp_path):
    path = _write(tmp_path, "b.html", "<html><body><div class='sec'><p>ok</p>")
    issues = deliverable.completeness_issues(path, min_visible_chars=2000)
    joined = " ".join(issues)
    assert "no closing </html>" in joined
    assert "visible characters" in joined


def test_completeness_uses_reference_floor(tmp_path):
    reference = _write(tmp_path, "ref.html", PAGE.format(body="<p>" + "内容 " * 3000 + "</p>"))
    target = _write(tmp_path, "out.html", PAGE.format(body="<p>" + "内容 " * 100 + "</p>"))
    issues = deliverable.completeness_issues(target, reference_paths=[reference], min_visible_chars=2000, min_reference_ratio=0.5)
    assert any("visible characters" in item for item in issues)


COMPLETE = """<!DOCTYPE html>
<html lang="zh-CN"><head><title>t</title></head>
<body>
<div id="s1" class="sec">one</div>
<div id="s2" class="sec">two</div>
<nav><a href="#s1">1</a><a href="#s2">2</a></nav>
{body}
</body></html>
"""


def test_html_report_flags_broken_local_links(tmp_path):
    (tmp_path / "exists.html").write_text("<html></html>", encoding="utf-8")
    path = _write(
        tmp_path,
        "page.html",
        '<html><body><a href="exists.html">ok</a><a href="missing.html">bad</a>'
        '<a href="https://example.com">web</a><a href="#s1">anchor</a></body></html>',
    )
    report = deliverable.html_report(path)
    assert report["broken_local_links"] == ["missing.html"]


def test_html_report_resolves_file_uri_links(tmp_path):
    target = tmp_path / "other.html"
    target.write_text("<html></html>", encoding="utf-8")
    path = _write(tmp_path, "page.html", f'<html><body><a href="{target.as_uri()}">ok</a></body></html>')
    report = deliverable.html_report(path)
    assert report["broken_local_links"] == []


def test_complete_page_has_no_issues(tmp_path):
    reference = _write(tmp_path, "ref.html", COMPLETE.format(body="<p>" + "内容 " * 1200 + "</p>"))
    target = _write(tmp_path, "out.html", COMPLETE.format(body="<p>" + "内容 " * 1200 + "</p>"))
    assert deliverable.completeness_issues(target, reference_paths=[reference]) == []


def test_deliverable_files_prefers_index_and_ignores_scratch(tmp_path):
    out = tmp_path / "plan"
    out.mkdir()
    (out / ".tmp_calc.py").write_text("print(1)\n", encoding="utf-8")
    (out / "notes.txt").write_text("x", encoding="utf-8")
    (out / "z.html").write_text("<html></html>", encoding="utf-8")
    (out / "index.html").write_text("<html></html>", encoding="utf-8")
    files = deliverable.deliverable_files(str(out))
    assert files[0].endswith("index.html")
    assert not any(deliverable.is_temp_file(os.path.basename(item)) for item in files)
    assert not any(item.endswith(".tmp_calc.py") for item in files)


def test_markdown_report_counts_fences_and_text(tmp_path):
    path = _write(tmp_path, "a.md", "# Title\n\n```\ncode\n")
    report = deliverable.markdown_report(path)
    assert report["closed"] is False
    assert deliverable.completeness_issues(path, min_visible_chars=10)
