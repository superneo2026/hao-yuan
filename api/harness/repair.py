from __future__ import annotations

import hashlib
import os
import re

from configs.configs import REPAIR_REPEAT_ESCALATE

_FAIL_RE = re.compile(r"^FAILED\s+(?P<node>[^\s]+)\s*-\s*(?P<err>.+)$", re.M)
_SECTION_RE = re.compile(r"^_{5,}\s*(?P<title>.+?)\s*_{5,}\s*$", re.M)
_LOC_RE = re.compile(
    r"(?P<file>[\w./\\-]+\.(?:py|js|ts|tsx|java|go|rs|c|cpp))[\"']?,\s*line\s+(?P<line>\d+)"
)
_SHORT_TB_RE = re.compile(
    r"^(?P<file>[\w./\\-]+\.(?:py|js|ts|tsx)):(?P<line>\d+):\s*(?P<err>\w*(?:Error|Exception)\b.*)$",
    re.M,
)
_SHORT_LOC_RE = re.compile(r"(?P<file>[\w./\\-]+\.(?:py|js|ts|tsx|java|go|rs)):(?P<line>\d+):", re.M)
_ASSERT_RE = re.compile(r"^\s*E\s+(?P<expr>.+)$", re.M)
_SUMMARY_RE = re.compile(
    r"(?P<failed>\d+)\s+failed(?:.*?(?P<passed>\d+)\s+passed)?.*?in\s+[\d.]+s", re.S
)


def parse_pytest(output: str) -> dict:
    text = output or ""
    result: dict = {"summary": {"failed": 0, "passed": 0}, "failures": [], "raw_tail": text[-1500:]}
    try:
        match = _SUMMARY_RE.search(text)
        if match:
            result["summary"]["failed"] = int(match.group("failed") or 0)
            result["summary"]["passed"] = int(match.group("passed") or 0)
        nodes: dict[str, dict] = {}
        order: list[dict] = []

        def node_info(node: str, error: str = "") -> dict:
            info = nodes.get(node)
            if info is None:
                info = {"node": node, "error": error.strip()[:240], "exc": "", "locations": [], "asserts": []}
                nodes[node] = info
                order.append(info)
            return info

        for match in _FAIL_RE.finditer(text):
            info = node_info(match.group("node"), match.group("err"))
            exc_match = re.match(r"(?P<typ>[\w.]+(?:Error|Exception|Interrupt))\s*:?\s*(?P<rest>.*)", info["error"])
            if exc_match:
                info["exc"] = exc_match.group("typ")

        parts = _SECTION_RE.split(text)
        for index in range(1, len(parts) - 1, 2):
            title, body = parts[index].strip(), parts[index + 1]
            target = None
            for info in order:
                tail = info["node"].split("::")[-1]
                if tail == title or tail.split("[")[0] == title:
                    target = info
                    break
            if target is None:
                continue
            for match in _ASSERT_RE.finditer(body):
                expr = match.group("expr").strip()
                if expr and len(expr) > 3 and len(target["asserts"]) < 4:
                    target["asserts"].append(expr[:200])
            for pattern in (_LOC_RE, _SHORT_LOC_RE):
                for match in pattern.finditer(body):
                    loc = f"{match.group('file')}:{match.group('line')}"
                    if loc not in target["locations"] and len(target["locations"]) < 3:
                        target["locations"].append(loc)

        if not order:
            for match in _SHORT_TB_RE.finditer(text):
                info = node_info(match.group("file"), match.group("err"))
                info["exc"] = re.match(r"\w+", match.group("err")).group(0)
                info["locations"] = [f"{match.group('file')}:{match.group('line')}"]

        result["failures"] = order
        return result
    except Exception:
        return result


def failure_fingerprint(failures: list[dict]) -> str:
    parts = []
    for failure in failures[:8]:
        parts.append(
            f"{failure.get('node', '')}|{failure.get('exc', '')}|{(failure.get('locations') or [''])[0]}"
        )
    raw = ";".join(parts)
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:12] if raw else ""


def repair_guidance(failures: list[dict], history: list[tuple[str, int]]) -> str:
    if not failures:
        return ""
    fingerprint = failure_fingerprint(failures)
    count = 1
    for known, attempts in history or []:
        if known == fingerprint:
            count = max(count, attempts + 1)
    lines = [f"[repair loop] {len(failures)} failing test(s) detected:"]
    for failure in failures[:5]:
        loc = f" @ {failure['locations'][0]}" if failure.get("locations") else ""
        lines.append(
            f"  - {failure['node']}{loc}  {failure.get('exc') or ''} {failure.get('error', '')[:120]}"
        )
        for assertion in (failure.get("asserts") or [])[:2]:
            lines.append(f"      assert: {assertion}")
    if count >= REPAIR_REPEAT_ESCALATE:
        lines.append(
            f"  ! This failure has repeated {count} times. Change strategy: reproduce minimally, "
            "print intermediate values, bisect the change, and re-read the failing test semantics."
        )
    else:
        lines.append("  Apply the smallest fix, then rerun the same test immediately.")
    return "\n".join(lines)


def test_snippet(workspace: str, failures: list[dict], max_chars: int = 1600) -> str:
    if not workspace or not failures:
        return ""
    try:
        node = failures[0].get("node") or ""
        filename = node.split("::")[0]
        path = os.path.join(workspace, filename)
        if not os.path.isfile(path):
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.read().splitlines()
        name = node.split("::")[-1].split("[")[0]
        start = None
        for index, line in enumerate(lines):
            if re.match(r"\s*def\s+" + re.escape(name) + r"\s*\(", line):
                start = index
                break
        if start is None:
            loc = (failures[0].get("locations") or [""])[0]
            if ":" in loc:
                try:
                    start = max(0, int(loc.rsplit(":", 1)[1]) - 1)
                except ValueError:
                    start = None
        if start is None:
            return ""
        segment = lines[start : start + 30]
        return "\n".join(f"{start + 1 + i}: {line}" for i, line in enumerate(segment))[:max_chars]
    except Exception:
        return ""


def is_test_command(command: str) -> bool:
    lowered = (command or "").lower()
    return any(
        hint in lowered
        for hint in ("pytest", "unittest", "jest", "vitest", "mocha", "go test", "cargo test", "mvn test", "dotnet test")
    )
