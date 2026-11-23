from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

# Deliberately lightweight and dependency-free: this module only reads a prior
# project's reports/data cards and checks a generated plan for contradictions.

_SKIP_DIRS = {
    ".git", "node_modules", "env1", "__pycache__", ".venv", "venv", "dist", "build",
    ".pytest_cache", "checkpoints", "outputs", "assets", "logs", "snapshots",
}
_NAME_HINTS = (
    "readme", "model_card", "changelog", "summary", "final_eval", "eval_",
    "data_quality", "status", "target", "quality", "licenses", "license",
)
_MAX_FILE_BYTES = 300_000
_MAX_FILES = 120
_MAX_ROWS = 240

_METRIC_KEYS = {
    "params_m": "params_M",
    "trainable_m": "trainable_M",
    "total_m": "total_M",
    "steps": "steps",
    "minutes": "minutes",
    "hours": "hours",
    "cer": "CER",
    "rtf": "RTF",
    "f0": "F0",
    "f0_median": "F0_median",
    "squim": "SQUIM",
    "pesq": "PESQ",
    "stoi": "STOI",
    "utmos": "UTMOS",
    "n": "n",
    "speakers": "speakers",
    "utterances": "utterances",
    "hours_total": "hours_total",
    "vocab_size": "vocab_size",
    "sample_rate": "sample_rate",
    "n_mels": "n_mels",
    "n_fft": "n_fft",
    "hop_length": "hop_length",
    "win_length": "win_length",
    "fmin": "fmin",
    "fmax": "fmax",
    "best_val_mel": "best_val_mel",
    "val_mel": "val_mel",
    "mel_mean": "mel_mean",
    "mel_std": "mel_std",
    "license": "license",
    "commercial_use": "commercial_use",
    "voice_rights": "voice_rights",
    "gender": "gender",
    "female": "female",
    "male": "male",
}
_NESTED_PARENTS = {"duration_sec", "text_chars", "pinyin_tokens"}
_NESTED_KEYS = {"mean", "median", "min", "max", "sum"}
_SKIP_LIST_KEYS = {"items", "results", "top_speakers", "rows", "data"}

_METRIC_LINE_RE = re.compile(
    r"(CER|PESQ|STOI|F0|params?|参数|steps|minutes|小时|speakers?|说话人|hours?|"
    r"license|许可|gender|性别|val[ _]mel|SQUIM|UTMOS|V0\.|AISHELL|THCHS|MagicData)",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_DIGIT_RE = re.compile(r"\d")


def _strip_tags(value: str) -> str:
    text = _TAG_RE.sub(" ", value or "")
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return _WS_RE.sub(" ", text)


def _candidate_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in names:
            lower = name.lower()
            if not lower.endswith((".json", ".md")):
                continue
            if not any(hint in lower for hint in _NAME_HINTS):
                continue
            path = Path(current) / name
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            found.append(path)
            if len(found) >= _MAX_FILES:
                return sorted(found)
    return sorted(found)


def _walk_json(obj: Any, rel: str, prefix: str, parent: str, depth: int, rows: list[tuple[str, str, Any]]) -> None:
    if depth > 4:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            lower = str(key).lower()
            if lower in _METRIC_KEYS and not isinstance(value, (dict, list)):
                rows.append((rel, f"{prefix}{_METRIC_KEYS[lower]}", value))
                continue
            qualified = f"{prefix}{key}"
            if parent in _NESTED_PARENTS and lower in _NESTED_KEYS and not isinstance(value, (dict, list)):
                rows.append((rel, qualified, value))
            elif isinstance(value, (dict, list)) and lower not in _SKIP_LIST_KEYS:
                if isinstance(value, list):
                    if value and isinstance(value[0], (dict, list)):
                        _walk_json(value[0], rel, f"{qualified}[0].", lower, depth + 1, rows)
                else:
                    _walk_json(value, rel, f"{qualified}.", lower, depth + 1, rows)


def _json_rows(path: Path, rel: str) -> list[tuple[str, str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    rows: list[tuple[str, str, Any]] = []
    _walk_json(data, rel, "", "", 0, rows)
    return rows


def _markdown_rows(path: Path, rel: str) -> list[tuple[str, str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows: list[tuple[str, str, Any]] = []
    limit = 8 if "license" in rel.lower() else 30
    for index, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or len(stripped) > 260:
            continue
        if not _METRIC_LINE_RE.search(stripped):
            continue
        # JSON registries carry license facts more reliably; in Markdown keep
        # only lines that actually contain a number (metrics, hours, counts).
        if not _DIGIT_RE.search(stripped):
            continue
        rows.append((rel, f"line {index}", stripped[:240]))
        if len(rows) >= limit:
            break
    return rows


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        return json.dumps(value[:6], ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)[:160]
    return str(value)[:200]


def _row_rank(row: tuple[str, str, Any]) -> tuple[int, int, str, str]:
    rel, key, _value = row
    source = rel.lower().replace("\\", "/")
    leaf = key.split(".")[-1]
    if "reports/" in source and any(hint in source for hint in ("summary", "final_eval", "data_quality")):
        source_rank = 0
    elif "data_quality" in source:
        source_rank = 1
    elif source.endswith(("readme.md", "model_card.md", "changelog.md")):
        source_rank = 2
    elif "licenses" in source or source.endswith("license"):
        source_rank = 4
    else:
        source_rank = 3
    fact_rank = 0 if leaf in {
        "params_M", "trainable_M", "total_M", "steps", "minutes", "CER", "PESQ",
        "F0_median", "speakers", "utterances", "hours", "vocab_size", "sample_rate",
    } else 1
    return (source_rank, fact_rank, rel, key)


def _collect(root: Path) -> tuple[list[tuple[str, str, Any]], list[str], list[str]]:
    rows: list[tuple[str, str, Any]] = []
    scanned: list[str] = []
    skipped: list[str] = []
    for path in _candidate_files(root):
        try:
            rel = os.path.relpath(str(path), str(root)) if root.is_dir() else path.name
        except ValueError:
            rel = path.name
        if path.suffix.lower() == ".json":
            found = _json_rows(path, rel)
        else:
            found = _markdown_rows(path, rel)
        if found:
            scanned.append(rel)
            rows.extend(found)
        else:
            skipped.append(rel)
    # Stable, useful order: high-value report facts first, licenses last.
    unique: dict[tuple[str, str, str], tuple[str, str, Any]] = {}
    for rel, key, value in rows:
        unique[(rel, key, _fmt(value))] = (rel, key, value)
    return sorted(unique.values(), key=_row_rank), scanned, skipped


def baseline_audit(path: str, max_chars: int = 12000) -> str:
    root = Path(path).expanduser()
    if not root.exists():
        return f"[baseline_audit] not found: {path}"
    all_rows, scanned, skipped = _collect(root)
    rows = all_rows[:_MAX_ROWS]
    lines = [f"[baseline_audit] {root}", f"scanned: {len(scanned)} files; facts: {len(all_rows)}"]
    if not all_rows:
        lines.append("no baseline facts found. Check that README/MODEL_CARD/reports/*/summary.json or data cards exist.")
        return "\n".join(lines)
    # Surface the metrics that most often get mixed up across branches before
    # the (possibly truncated) table, so they are never lost to the cap.
    highlights: dict[str, list[str]] = {}
    for _rel, key, value in all_rows:
        leaf = key.split(".")[-1]
        if leaf in {"params_M", "trainable_M", "total_M", "CER", "PESQ", "F0_median", "speakers", "hours", "license"}:
            highlights.setdefault(leaf, [])
            rendered = _fmt(value)
            if rendered not in highlights[leaf]:
                highlights[leaf].append(rendered)
    if highlights:
        lines.append("highlights (verify branch/release before citing):")
        for key, values in highlights.items():
            lines.append(f"- {key}: " + ", ".join(values[:8]))
    lines.append("")
    lines.append("| source | fact | value |")
    lines.append("|---|---|---|")
    for rel, key, value in rows:
        lines.append(f"| {rel} | {key} | {_fmt(value)} |")
    lines.append("")
    lines.append("coverage:")
    lines.append("- read: " + ", ".join(scanned[:40]))
    if skipped:
        lines.append("- skipped/no facts: " + ", ".join(skipped[:20]))
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max_chars - 80] + "\n... [baseline_audit truncated; narrow the path or raise max_chars]"
    return text


def _baseline_facts(rows: list[tuple[str, str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for _rel, key, value in rows:
        leaf = key.split(".")[-1]
        if leaf == "speakers" and "selected.speakers" in key:
            facts["speakers"] = value
        elif leaf == "utterances" and "selected.utterances" in key:
            facts["utterances"] = value
        elif leaf == "hours" and "selected.hours" in key:
            facts["hours"] = value
        elif leaf in {"female", "male"}:
            facts[leaf] = value
        elif leaf in {"params_M", "CER", "PESQ", "F0_median"}:
            values = facts.setdefault(leaf, [])
            if value not in values:
                values.append(value)
    return facts


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def doc_consistency(path: str, baseline_dir: str = "") -> str:
    plan = Path(path).expanduser()
    if not plan.is_file():
        return f"[doc_consistency] not found: {path}"
    try:
        html = plan.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[doc_consistency] cannot read {path}: {exc}"
    text = _strip_tags(html)
    issues: list[str] = []
    notes: list[str] = []

    all_female = bool(re.search(r"全女声|all[-\s]?female|female[-\s]?only", text, re.I))
    gender_splits = re.findall(r"女\s*(\d+)\s*[/／]\s*男\s*(\d+)", text)
    male_counts = [int(male) for _female, male in gender_splits]
    if re.search(r"AISHELL-3", text, re.I) and all_female and any(male > 0 for male in male_counts):
        issues.append(
            "AISHELL-3 is described as both 全女声 and 女/男拆分 "
            + ", ".join(f"女{f}/男{m}" for f, m in gender_splits)
            + "; pick one and cite the data card."
        )
    if re.search(r"全女声", text) and re.search(r"男\s*\d+", text):
        issues.append('The document says "全女声" but also contains a male speaker count.')
    speaker_counts = re.findall(r"AISHELL-3[^。\n]{0,180}?(\d+)\s*(?:人|speakers?|spk)", text, re.I)
    if len(set(speaker_counts)) > 1:
        notes.append("AISHELL-3 speaker counts vary: " + ", ".join(sorted(set(speaker_counts))) + " (confirm subset vs full corpus).")
    sample_rates = sorted(set(re.findall(r"(\d+(?:\.\d+)?)\s*kHz", text, re.I)))
    if "22.05" in sample_rates and "24" in sample_rates and not re.search(r"v1|V1|v2|V2|级联|直通", text):
        notes.append("Both 22.05 kHz and 24 kHz appear; label which one is v1 and which one is v2.")
    pesq_values: list[str] = []
    for raw in re.findall(r"PESQ(?:-WB)?[^\d\n]{0,8}(\d+(?:\.\d+)?)", text, re.I):
        number = _as_float(raw)
        if number is not None and 0 < number <= 5:
            pesq_values.append(raw)
    pesq = sorted(set(pesq_values), key=float)
    if "0.95" in pesq and any(value.startswith("3") for value in pesq) and not re.search(r"SQUIM|非标准", text, re.I):
        notes.append("PESQ 0.95 and a >=3 target both appear; confirm the v1 value is SQUIM/non-standard before comparing.")

    baseline_facts: dict[str, Any] = {}
    if baseline_dir:
        root = Path(baseline_dir).expanduser()
        if root.exists():
            rows, _scanned, _skipped = _collect(root)
            baseline_facts = _baseline_facts(rows)
            if baseline_facts:
                baseline_female = baseline_facts.get("female")
                baseline_male = baseline_facts.get("male")
                if baseline_female and not baseline_male and any(male > 0 for male in male_counts):
                    issues.append(
                        f"Baseline data card reports {baseline_female} female and no male samples, "
                        "but the plan contains a male speaker count."
                    )
                baseline_speakers = baseline_facts.get("speakers")
                if baseline_speakers and speaker_counts and str(baseline_speakers) not in speaker_counts:
                    issues.append(
                        f"Baseline selected.speakers={baseline_speakers}, but the plan cites "
                        + ", ".join(sorted(set(speaker_counts)))
                        + "."
                    )
                params = list(dict.fromkeys(baseline_facts.get("params_M") or []))
                plan_numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
                uncited = []
                for value in params:
                    number = _as_float(value)
                    if number is None:
                        if str(value) not in text:
                            uncited.append(value)
                    elif not any(abs(candidate - number) <= max(abs(number) * 0.02, 1e-6) for candidate in plan_numbers):
                        uncited.append(value)
                if uncited:
                    notes.append(
                        "Baseline params_M=" + ", ".join(_fmt(v) for v in params)
                        + "; not cited: " + ", ".join(_fmt(v) for v in uncited)
                        + ". If the plan uses another value, label it (V0.01 vs commercial chain)."
                    )
        else:
            notes.append(f"baseline not found: {baseline_dir}")

    lines = [f"[doc_consistency] {plan.name}"]
    lines.append("detected:")
    lines.append(f"- all_female={all_female}")
    lines.append(f"- gender_split={gender_splits or 'none'}")
    lines.append(f"- speaker_counts={sorted(set(speaker_counts)) or 'none'}")
    lines.append(f"- sample_rates={sample_rates or 'none'}")
    lines.append(f"- pesq={pesq or 'none'}")
    if baseline_facts:
        lines.append("baseline facts: " + json.dumps(baseline_facts, ensure_ascii=False, default=str)[:800])
    if issues:
        lines.append("must fix:")
        lines.extend(f"- {item}" for item in issues)
    else:
        lines.append("no cross-section contradictions detected by heuristic checks.")
    if notes:
        lines.append("notes:")
        lines.extend(f"- {item}" for item in notes)
    return "\n".join(lines)
