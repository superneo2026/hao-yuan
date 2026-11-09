from __future__ import annotations

import os
import re
from collections import Counter

_WEB_EXTS = (".html", ".htm", ".css", ".scss", ".less", ".svg", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte")
_STOP = r"\s'\"<>\)\]，。；：、！？（）"
_FILE_URI_RE = re.compile(rf"file:///([^{_STOP}]+)", re.I)
_PATH_TOKEN_RE = re.compile(
    rf"([A-Za-z]:[\\/][^{_STOP}]+|[^{_STOP}]+\.(?:html?|css|scss|less|svg|jsx?|tsx?|vue|svelte)\b)",
    re.I,
)
_OUTPUT_PREFIX_RE = re.compile(
    r"(?:输出|保存|写入|写到|生成到|生成|产出|放到|放在|结果|目标|文件)"
    r"[^，。；;\n]{0,12}(?:到|至|为|是)?\s*[:：]?\s*$"
)
_HINT_RE = re.compile(
    r"参考|参照|仿照|照着|沿用|保持.{0,6}(?:风格|样式|格式|结构)|同样(?:的)?(?:风格|样式|格式|结构)|"
    r"一致(?:的)?(?:风格|样式|格式)|参考案例|参考页面|模板|design|reference|template|style guide|mimic|port",
    re.I,
)

_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_VAR_RE = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;{}]+);")
_FONT_RE = re.compile(r"font-family\s*:\s*([^;{}]+)(?:;|\})", re.I)
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;{}]+);", re.I)
_SHADOW_RE = re.compile(r"box-shadow\s*:\s*([^;{}]+);", re.I)
_MAXW_RE = re.compile(r"max-width\s*:\s*([^;{}]+);", re.I)
_GRID_RE = re.compile(r"grid-template-columns\s*:\s*([^;{}]+);", re.I)
_MEDIA_RE = re.compile(r"@media[^{]*?(\d+)px", re.I)
_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.I | re.S)
_LINK_CSS_RE = re.compile(r"<link\b[^>]*href=[\"']([^\"']+\.css[^\"']*)[\"']", re.I)
_HEADING_RE = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.I | re.S)
_SECTION_RE = re.compile(r"<section\b([^>]*)>", re.I)
_NAV_RE = re.compile(r"<(nav|header)\b[^>]*>(.*?)</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<(header|nav|main|section|article|aside|footer|table|svg|pre|canvas)\b", re.I)
_CLASS_RE = re.compile(r"class=[\"']([^\"']+)[\"']", re.I)
_ID_RE = re.compile(r"\bid=[\"']([^\"']+)[\"']", re.I)
_SCRIPT_SRC_RE = re.compile(r"<script\b[^>]*src=[\"']([^\"']+)[\"']", re.I)
_BEHAVIOR_RE = re.compile(
    r"addEventListener|localStorage|sessionStorage|requestAnimationFrame|IntersectionObserver|"
    r"onclick|setInterval|setTimeout|fetch\(|WebSocket|matchMedia",
    re.I,
)
_ANIM_RE = re.compile(r"@keyframes\s+([A-Za-z0-9_-]+)", re.I)


def is_reference_hint(text: str) -> bool:
    return bool(_HINT_RE.search(text or ""))


def _normalize_uri(raw: str) -> str:
    value = raw.strip().strip("'\"<>()[]，。；;,")
    if value.lower().startswith("file:///"):
        value = value[8:]
        from urllib.parse import unquote

        value = unquote(value)
        if not value.startswith("/") and re.match(r"^[A-Za-z]:", value) is None:
            value = "/" + value
    return value


def _inside(base: str, target: str) -> bool:
    try:
        base_real = os.path.realpath(base)
        target_real = os.path.realpath(target)
    except OSError:
        return False
    return target_real == base_real or target_real.startswith(base_real + os.sep)


def resolve_reference_paths(workspace: str, text: str, require_hint: bool = True) -> list[str]:
    if not workspace or not os.path.isdir(workspace):
        return []
    if require_hint and not is_reference_hint(text or ""):
        return []
    found: list[str] = []
    for match in list(_FILE_URI_RE.finditer(text or "")) + list(_PATH_TOKEN_RE.finditer(text or "")):
        raw = match.group(1)
        candidate = _normalize_uri(raw)
        if not candidate:
            continue
        before = (text or "")[max(0, match.start() - 12) : match.start()]
        if _OUTPUT_PREFIX_RE.search(before):
            continue
        absolute = os.path.isabs(candidate)
        path = candidate if absolute else os.path.join(workspace, candidate)
        if not os.path.isfile(path):
            continue
        if not absolute and not _inside(workspace, path):
            continue
        try:
            resolved = os.path.realpath(path)
        except OSError:
            continue
        if resolved not in found:
            found.append(resolved)
    return found


def _strip_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _top(counter: Counter, limit: int, prefix: str = "") -> str:
    items = [f"{name}{prefix}({count})" for name, count in counter.most_common(limit)]
    return ", ".join(items)


def _style_text(html: str, base_dir: str) -> str:
    blocks = [match.group(1) for match in _STYLE_BLOCK_RE.finditer(html)]
    for href in _LINK_CSS_RE.findall(html):
        if href.lower().startswith(("http://", "https://", "//", "data:")):
            continue
        target = os.path.normpath(os.path.join(base_dir, href.split("?")[0]))
        try:
            if os.path.isfile(target) and os.path.getsize(target) < 400_000:
                blocks.append(open(target, "r", encoding="utf-8", errors="replace").read())
        except OSError:
            continue
    return "\n".join(blocks)


def style_signature(text: str) -> dict:
    colors = Counter(match.lower() for match in _HEX_RE.findall(text or ""))
    vars_: dict[str, str] = {}
    for name, value in _VAR_RE.findall(text or ""):
        vars_.setdefault(name, value.strip()[:80])
    fonts = [value.strip()[:160] for value in _FONT_RE.findall(text or "")]
    radii = [value.strip()[:40] for value in _RADIUS_RE.findall(text or "")]
    shadows = [value.strip()[:80] for value in _SHADOW_RE.findall(text or "")]
    widths = [value.strip()[:30] for value in _MAXW_RE.findall(text or "")]
    grids = [re.sub(r"\s+", " ", value.strip())[:80] for value in _GRID_RE.findall(text or "")]
    media = sorted({f"{value}px" for value in _MEDIA_RE.findall(text or "")}, key=lambda item: int(item[:-2]))
    return {
        "colors": colors,
        "vars": vars_,
        "fonts": fonts,
        "radii": radii,
        "shadows": shadows,
        "widths": widths,
        "grids": grids,
        "media": media,
    }


def _signature_lines(sig: dict, limit_colors: int = 12) -> list[str]:
    lines: list[str] = []
    if sig["colors"]:
        lines.append("  colors: " + _top(sig["colors"], limit_colors))
    if sig["vars"]:
        pairs = list(sig["vars"].items())[:18]
        lines.append("  css vars: " + "; ".join(f"{name}={value}" for name, value in pairs))
    if sig["fonts"]:
        lines.append("  font-family: " + " | ".join(dict.fromkeys(sig["fonts"]))[:240])
    if sig["radii"]:
        lines.append("  border-radius: " + ", ".join(dict.fromkeys(sig["radii"]))[:200])
    if sig["shadows"]:
        lines.append("  box-shadow: " + " | ".join(dict.fromkeys(sig["shadows"]))[:240])
    if sig["widths"]:
        lines.append("  max-width: " + ", ".join(dict.fromkeys(sig["widths"]))[:200])
    if sig["grids"]:
        lines.append("  grids: " + " | ".join(dict.fromkeys(sig["grids"]))[:240])
    if sig["media"]:
        lines.append("  breakpoints: " + ", ".join(sig["media"]))
    return lines


def digest(path: str, max_chars: int = 9000) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"reference file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    try:
        raw = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError as exc:
        raise OSError(f"cannot read reference: {exc}") from exc
    line_count = raw.count("\n") + 1
    base_dir = os.path.dirname(path)
    head = f"[reference] {os.path.basename(path)} ({size} bytes, {line_count} lines, {ext or 'text'})"
    if ext not in _WEB_EXTS:
        body = raw[: max(500, max_chars - len(head))]
        return (head + "\n" + body)[:max_chars]

    style = _style_text(raw, base_dir) or raw
    sig = style_signature(style)
    lines = [head, "design tokens:"]
    sig_lines = _signature_lines(sig)
    lines += sig_lines or ["  (no CSS tokens detected)"]

    title_match = re.search(r"<title\b[^>]*>(.*?)</title>", raw, re.I | re.S)
    lang_match = re.search(r"<html\b[^>]*\blang=[\"']([^\"']+)", raw, re.I)
    if title_match:
        lines.append("title: " + _strip_tags(title_match.group(1))[:180])
    if lang_match:
        lines.append("lang: " + lang_match.group(1))
    # Python 3.11：f-string 表达式内不能含反斜杠，正则先行计算
    n_tables = len(re.findall(r"<table\b", raw, re.I))
    n_svg = len(re.findall(r"<svg\b", raw, re.I))
    n_code = len(re.findall(r"<pre\b", raw, re.I))
    lines.append(
        "counts: "
        + ", ".join(
            [
                f"sections={len(_SECTION_RE.findall(raw))}",
                f"headings={len(_HEADING_RE.findall(raw))}",
                f"tables={n_tables}",
                f"svg={n_svg}",
                f"code={n_code}",
                f"keyframes={len(_ANIM_RE.findall(raw))}",
                f"scripts={len(_SCRIPT_SRC_RE.findall(raw))}",
                f"classes={len(set(sum((c.split() for c in _CLASS_RE.findall(raw)), [])))}",
            ]
        )
    )

    classes = Counter(cls for group in _CLASS_RE.findall(raw) for cls in group.split())
    ids = Counter(_ID_RE.findall(raw))
    top_classes = [name for name, _ in classes.most_common(40)]
    components = [name for name in ("kpi", "cd", "card", "flow", "tl", "box", "tw", "callout", "gate", "warn", "qa", "sb", "code", "login", "nav", "topnav", "hero", "hdr") if name in classes or name in ids]
    lines.append("components: " + (", ".join(components) if components else "generic layout"))
    if top_classes:
        lines.append("top classes: " + ", ".join(top_classes[:22]))

    nav_match = _NAV_RE.search(raw)
    if nav_match:
        links = [_strip_tags(item) for item in re.findall(r"<a\b[^>]*>(.*?)</a>", nav_match.group(2), re.I | re.S)]
        links = [item for item in links if item]
        if links:
            lines.append("nav links: " + " | ".join(links[:20]))

    headings = []
    for level, body in _HEADING_RE.findall(raw):
        text = _strip_tags(body)[:90]
        if text:
            headings.append(f"h{level}:{text}")
    if headings:
        lines.append("outline: " + " > ".join(headings[:24]))

    section_ids = [value for value in re.findall(r"\bid=[\"']([^\"']+)[\"']", " ".join(_SECTION_RE.findall(raw)))]
    if section_ids:
        lines.append("section ids: " + ", ".join(dict.fromkeys(section_ids))[:240])

    behaviors = sorted({match.lower() for match in _BEHAVIOR_RE.findall(raw)})
    if behaviors:
        lines.append("behaviors: " + ", ".join(behaviors))
    script_srcs = _SCRIPT_SRC_RE.findall(raw)
    if script_srcs:
        lines.append("scripts: " + ", ".join(dict.fromkeys(script_srcs))[:180])

    tag_lines = []
    for index, line in enumerate(raw.splitlines(), 1):
        match = _TAG_RE.search(line)
        if match:
            tag_lines.append(f"  {index}: {line.strip()[:110]}")
            if len(tag_lines) >= 18:
                break
    if tag_lines:
        lines.append("structure (tag:line):")
        lines += tag_lines

    first_style = (sig_lines and _STYLE_BLOCK_RE.search(raw))
    outline_head = ""
    if first_style:
        snippet = re.sub(r"\s+", " ", first_style.group(1).strip())
        outline_head = "css sample: " + snippet[:900]
        lines.append(outline_head)

    body = "\n".join(lines)
    if len(body) > max_chars:
        body = body[: max_chars - 60] + "\n...[reference digest truncated]"
    return body


def compare(reference_path: str, target_path: str) -> str:
    if not os.path.isfile(reference_path):
        return f"[reference_compare] reference not found: {reference_path}"
    if not os.path.isfile(target_path):
        return f"[reference_compare] target not found: {target_path}"
    ref = open(reference_path, "r", encoding="utf-8", errors="replace").read()
    tgt = open(target_path, "r", encoding="utf-8", errors="replace").read()
    ref_style = _style_text(ref, os.path.dirname(reference_path)) or ref
    tgt_style = _style_text(tgt, os.path.dirname(target_path)) or tgt
    ref_sig = style_signature(ref_style)
    tgt_sig = style_signature(tgt_style)

    def overlap(left: Counter, right: Counter) -> float:
        if not left or not right:
            return 0.0
        left_set, right_set = set(left), set(right)
        return len(left_set & right_set) / len(left_set)

    color_overlap = overlap(ref_sig["colors"], tgt_sig["colors"])
    font_overlap = 1.0 if (ref_sig["fonts"] and tgt_sig["fonts"] and ref_sig["fonts"][0] == tgt_sig["fonts"][0]) else 0.0
    ref_media, tgt_media = set(ref_sig["media"]), set(tgt_sig["media"])
    media_overlap = len(ref_media & tgt_media) / len(ref_media) if ref_media else 1.0
    dark_ref = _theme_mode(ref_style, ref_sig) == "dark"
    dark_tgt = _theme_mode(tgt_style, tgt_sig) == "dark"
    mode_match = dark_ref == dark_tgt

    issues = []
    if color_overlap < 0.4:
        issues.append(f"palette drift: only {int(color_overlap * 100)}% of reference colors reused")
    if font_overlap < 1.0:
        issues.append("font stack differs from the reference")
    if not mode_match:
        issues.append(f"theme mode mismatch: reference is {'dark' if dark_ref else 'light'}, target is {'dark' if dark_tgt else 'light'}")
    if media_overlap < 0.5:
        issues.append("breakpoints differ from the reference")
    ref_components = {name for name in ("topnav", "nav", "kpi", "box", "cd", "flow", "tl", "code", "callout", "gate", "warn", "qa", "sb") if name in ref}
    tgt_components = {name for name in ref_components if name in tgt}
    missing = sorted(ref_components - tgt_components)
    if missing:
        issues.append("missing reference components: " + ", ".join(missing))

    score = int(round(100 * (0.5 * color_overlap + 0.2 * font_overlap + 0.15 * media_overlap + 0.15 * (1.0 if mode_match else 0.0))))
    lines = [
        f"[reference_compare] {os.path.basename(target_path)} vs {os.path.basename(reference_path)}",
        f"style fidelity: {score}/100",
        f"reference mode: {'dark' if dark_ref else 'light'} / target mode: {'dark' if dark_tgt else 'light'}",
        f"reused colors: {int(color_overlap * 100)}% / breakpoints: {int(media_overlap * 100)}%",
    ]
    if issues:
        lines.append("drift:")
        lines += ["  - " + item for item in issues]
    else:
        lines.append("the target follows the reference design system.")
    return "\n".join(lines)


def _luminance(value: str) -> float | None:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return None
    try:
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return None
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _theme_mode(style: str, sig: dict) -> str:
    backgrounds = re.findall(r"background(?:-color)?\s*:\s*([^;{}]+);", style or "", re.I)
    for raw in backgrounds:
        if any(token in raw.lower() for token in ("gradient", "url(", "transparent")):
            continue
        match = _HEX_RE.search(raw)
        if not match:
            continue
        value = _luminance(match.group(0))
        if value is None:
            continue
        if value < 80:
            return "dark"
        if value > 150:
            return "light"
    votes = 0
    for color, count in sig["colors"].items():
        value = _luminance(color)
        if value is None:
            continue
        votes += count if value < 80 else (-count if value > 150 else 0)
    return "dark" if votes > 0 else "light"
