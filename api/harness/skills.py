from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FRONT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-z0-9_]+")


def _parse_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip("'\"") for item in value.split(",") if item.strip()]


@dataclass
class Skill:
    name: str
    title: str
    description: str = ""
    kinds: list[str] = field(default_factory=lambda: ["*"])
    triggers: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    body: str = ""
    path: str = ""
    source: str = "core"

    def to_dict(self, include_body: bool = False) -> dict[str, Any]:
        data = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "kinds": self.kinds,
            "triggers": self.triggers,
            "version": self.version,
            "source": self.source,
            "chars": len(self.body),
        }
        if include_body:
            data["body"] = self.body
        return data

    def render(self) -> str:
        return f"### Skill: {self.title} ({self.name})\n{self.body.strip()}"


def _parse(path: Path, source: str) -> Skill:
    raw = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, Any] = {}
    body = raw
    match = _FRONT_RE.match(raw)
    if match:
        for line in match.group(1).splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key in ("kinds", "triggers") or value.startswith("["):
                meta[key] = _parse_list(value)
            else:
                meta[key] = value
        body = raw[match.end() :]
    name = str(meta.get("name") or path.stem)
    kinds = meta.get("kinds") or ["*"]
    triggers = meta.get("triggers") or []
    return Skill(
        name=name,
        title=str(meta.get("title") or name),
        description=str(meta.get("description") or ""),
        kinds=list(kinds),
        triggers=list(triggers),
        version=str(meta.get("version") or "1.0.0"),
        body=body.strip(),
        path=str(path),
        source=source,
    )


class SkillLibrary:
    def __init__(self, skills_dir: Path):
        self._dirs: list[tuple[Path, str]] = [(Path(skills_dir), "core")]
        self._skills: dict[str, Skill] = {}
        self._loaded = False

    def add_dir(self, directory: str | Path, source: str) -> None:
        item = (Path(directory), source)
        if item not in self._dirs:
            self._dirs.append(item)
            self._loaded = False

    def load_all(self) -> list[Skill]:
        self._skills.clear()
        for directory, source in self._dirs:
            if not directory.exists():
                continue
            for path in sorted(directory.glob("*.md")):
                try:
                    skill = _parse(path, source)
                except OSError:
                    continue
                self._skills[skill.name] = skill
        self._loaded = True
        return list(self._skills.values())

    def _ensure(self) -> None:
        if not self._loaded:
            self.load_all()

    def list(self) -> list[dict[str, Any]]:
        self._ensure()
        return [skill.to_dict() for skill in self._skills.values()]

    def get(self, name: str) -> Skill | None:
        self._ensure()
        return self._skills.get(name)

    def save(
        self,
        name: str,
        title: str,
        description: str,
        kinds: list[str],
        triggers: list[str],
        body: str,
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not _NAME_RE.match(name):
            raise ValueError("name must be lowercase letters/numbers/-/_, starting with a letter or number")
        title = (title or "").strip() or name
        kinds = [k.strip() for k in kinds if k.strip()] or ["*"]
        triggers = [t.strip() for t in triggers if t.strip()]
        directory = self._dirs[0][0]
        directory.mkdir(parents=True, exist_ok=True)
        front = (
            "---\n"
            f"name: {name}\n"
            f"title: {title}\n"
            f"description: {description.strip()}\n"
            f"kinds: {','.join(kinds)}\n"
            f"triggers: {','.join(triggers)}\n"
            "---\n\n"
        )
        (directory / f"{name}.md").write_text(front + body.strip() + "\n", encoding="utf-8", newline="\n")
        self._loaded = False
        self._ensure()
        skill = self._skills.get(name)
        return skill.to_dict() if skill else {}

    def delete(self, name: str) -> bool:
        self._ensure()
        skill = self._skills.get(name)
        if not skill:
            return False
        if skill.source != "core":
            raise ValueError("plugin skills cannot be deleted from here")
        try:
            os.remove(skill.path)
        except OSError:
            return False
        self._loaded = False
        return True

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        text = (text or "").lower()
        tokens: list[str] = []
        used = False
        try:
            import jieba

            tokens = [word.strip() for word in jieba.cut_for_search(text) if word.strip()]
            used = True
        except Exception:
            pass
        if not used:
            for run in _CJK_RE.findall(text):
                if len(run) == 1:
                    tokens.append(run)
                else:
                    tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
            tokens.extend(_WORD_RE.findall(text))
        return tokens

    @staticmethod
    def _bm25(query: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
        n = len(docs)
        if not n or not query:
            return [0.0] * n
        avgdl = sum(len(doc) for doc in docs) / n or 1.0
        df: dict[str, int] = {}
        for doc in docs:
            for token in set(doc):
                df[token] = df.get(token, 0) + 1
        idf = {
            token: math.log(1 + (n - df.get(token, 0) + 0.5) / (df.get(token, 0) + 0.5))
            for token in set(query)
        }
        scores = []
        for doc in docs:
            dl = len(doc)
            tf: dict[str, int] = {}
            for token in doc:
                tf[token] = tf.get(token, 0) + 1
            score = 0.0
            for token in set(query):
                freq = tf.get(token, 0)
                if not freq:
                    continue
                score += idf[token] * freq * (k1 + 1) / (freq + k1 * (1 - b + b * dl / avgdl))
            scores.append(score)
        return scores

    def match(self, kind: str, text: str, selected: list[str] | None = None, limit: int = 3) -> tuple[list[Skill], str]:
        self._ensure()
        if selected:
            picked = [self._skills[name] for name in selected if name in self._skills]
            return picked, "user selected"
        skills = list(self._skills.values())
        if not skills:
            return [], "no skills"
        lowered = (text or "").lower()
        query = self._tokenize(text)
        docs = [
            self._tokenize(
                " ".join([s.name, s.title, s.description, " ".join(s.triggers), s.body])
            )
            for s in skills
        ]
        raw = self._bm25(query, docs)
        top_raw = max(raw) if raw else 0.0
        ranked = []
        for index, skill in enumerate(skills):
            normalized = raw[index] / top_raw if top_raw > 0 else 0.0
            kind_hit = "*" in skill.kinds or kind in skill.kinds
            trigger_hits = [t for t in skill.triggers if t.lower() in lowered]
            score = normalized + (0.35 if kind_hit else 0.0) + min(0.8, 0.35 * len(trigger_hits))
            ranked.append((score, skill, trigger_hits))
        ranked.sort(key=lambda item: item[0], reverse=True)
        top = ranked[0][0] if ranked else 0.0
        picked = [item for item in ranked if item[0] >= max(0.15, top * 0.4)][:limit]
        if not picked:
            return [], "no match"
        hits: list[str] = []
        for _score, _skill, trigger_hits in picked:
            hits.extend(trigger_hits)
        how = "keyword/BM25 match: " + ", ".join(dict.fromkeys(hits or [w for w in query if len(w) > 1][:4]))
        return [item[1] for item in picked], how

    @staticmethod
    def render(skills: list[Skill], how: str = "") -> str:
        if not skills:
            return ""
        body = "\n\n".join(skill.render() for skill in skills)
        return f"\n\n--- Active Skills ({how or 'matched'}) ---\n{body}"
