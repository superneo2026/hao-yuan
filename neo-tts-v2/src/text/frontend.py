"""Mandarin text front-end for neo-tts v2.

pinyin (with tone) -> initial / final+tone composite tokens.
The composite keeps tonal information on the *vowel* token so every
frame allocation is linguistically meaningful (v1 attached whole
syllable durations to a bare tone token, which destroyed alignment).
"""
from __future__ import annotations

import re
from functools import lru_cache

INITIALS = [
    "zh", "ch", "sh",
    "b", "p", "m", "f",
    "d", "t", "n", "l",
    "g", "k", "h",
    "j", "q", "x",
    "r", "z", "c", "s",
    "y", "w",
]
_SYL = re.compile(r"^([a-z]+?)([1-5])$")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_DIGIT = {str(i): f"ling2 san1 ..." for i in range(10)}  # filled below
_DIGIT_PY = ["ling2", "yi1", "er4", "san1", "si4", "wu3", "liu4", "qi1", "ba1", "jiu3"]

SPECIAL = ["_", "^", "$", "unk", " "]


def split_syllable(syllable: str) -> tuple[str, str, str]:
    """'zhong1' -> ('zh', 'ong', '1'); 'an2' -> ('', 'an', '2')."""
    s = str(syllable).strip().lower().replace("u:", "v").replace("v", "v")
    m = _SYL.match(s)
    if not m:
        return "", s, "5"
    base, tone = m.group(1), m.group(2)
    initial = ""
    for ini in INITIALS:
        if base.startswith(ini) and len(base) > len(ini):
            initial = ini
            base = base[len(ini):]
            break
    return initial, base, tone


def syllable_tokens(syllable: str) -> list[str]:
    ini, fin, tone = split_syllable(syllable)
    comp = f"{fin}{tone}"
    return [ini, comp] if ini else [comp]


def text_to_pinyin(text: str) -> list[str]:
    from pypinyin import Style, lazy_pinyin

    out: list[str] = []
    buf: list[str] = []

    def flush():
        if not buf:
            return
        chunk = "".join(buf)
        buf.clear()
        for ch in chunk:
            if ch.isdigit():
                out.append(_DIGIT_PY[int(ch)])
            elif _CJK.match(ch):
                out.append(ch)

    for ch in text:
        if _CJK.match(ch):
            flush()
            out.extend(lazy_pinyin(ch, style=Style.TONE3, neutral_tone_with_five=True))
        elif ch.isdigit():
            buf.append(ch)
        elif ch.isspace() or ch in "，。！？、；：,.!?;:":
            flush()
    flush()
    return [p for p in out if p]


def build_vocab(pinyins) -> dict:
    tokens = {t: i for i, t in enumerate(SPECIAL)}
    phones: set[str] = set()
    for py in pinyins:
        for t in syllable_tokens(py):
            phones.add(t)
    for p in sorted(phones):
        if p not in tokens:
            tokens[p] = len(tokens)
    return {
        "type": "phone_composite",
        "tokens": tokens,
        "id_to_token": {str(v): k for k, v in tokens.items()},
        "size": len(tokens),
        "phones": sorted(phones),
    }


@lru_cache(maxsize=4)
def _load_vocab(path: str):
    import json

    return json.load(open(path, "r", encoding="utf-8"))


def text_to_ids(text: str, vocab_path: str, add_boundaries: bool = True) -> tuple[list[int], list[str]]:
    v = _load_vocab(str(vocab_path))["tokens"]
    unk = v.get("unk", 3)
    ids: list[int] = []
    toks: list[str] = []
    if add_boundaries:
        ids.append(v.get("^", 1))
        toks.append("^")
    for py in text_to_pinyin(text):
        for t in syllable_tokens(py):
            ids.append(int(v.get(t, unk)))
            toks.append(t)
    if add_boundaries:
        ids.append(v.get("$", 2))
        toks.append("$")
    return ids, toks
