"""Build the neo-tts v2 24 kHz feature set from AISHELL-3 + v1 alignments.

Input  (read-only): D:/Env/git/neo-tts/v1
  data/aishell3_22k_aligned/manifests/*.jsonl   syllable durations (fa alignment)
  data/aishell3/train|test/wav/<spk>/<id>.wav   raw 44.1 kHz audio
Output: D:/Env/git/neo-tts/v2/data/v2
  mel/<id>.npy       float16 log-mel [80, T] @ 24 kHz / hop 480 / fmax 12k
  train.jsonl val.jsonl eval.jsonl   manifest (composite phones + 50 fps durations)
  vocab.json mel_stats.json speakers.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V1 = Path(r"D:\Env\git\neo-tts\v1")
SRC = V1 / "data" / "aishell3_22k_aligned" / "manifests"
OUT = ROOT / "data" / "v2"
FPS22 = 22050 / 256
FPS24 = 24000 / 480


def raw_wav(utt: str, spk: str) -> Path | None:
    for split in ("train", "test"):
        p = V1 / "data" / "aishell3" / split / "wav" / spk / f"{utt}.wav"
        if p.exists():
            return p
    p = V1 / "data" / "aishell3_22k" / "wavs" / spk / f"{utt}.wav"
    return p if p.exists() else None


def scale_to_total(vals: list[int], total: int) -> list[int]:
    vals = [max(1, int(v)) for v in vals]
    cur = sum(vals)
    if cur == total:
        return vals
    if total < len(vals):
        return [1] * len(vals)
    fr = [v * total / cur for v in vals]
    out = [max(1, int(math.floor(x))) for x in fr]
    diff = total - sum(out)
    order = sorted(range(len(out)), key=lambda i: fr[i] - out[i], reverse=True)
    i = 0
    while diff > 0:
        out[order[i % len(order)]] += 1
        diff -= 1
        i += 1
    while diff < 0:
        j = order[i % len(order)]
        if out[j] > 1:
            out[j] -= 1
            diff += 1
        i += 1
    return out


def process(task: dict) -> dict | None:
    import librosa
    import soundfile as sf

    from src.audio.mel import logmel_from_wav, frames_for_samples
    from src.text.frontend import syllable_tokens

    src = Path(task["wav"])
    try:
        y, sr = sf.read(str(src), dtype="float32", always_2d=False)
        if y.ndim > 1:
            y = y.mean(axis=1)
        if sr != 24000:
            y = librosa.resample(y, orig_sr=sr, target_sr=24000, res_type="soxr_hq")
        y = np.clip(y, -1.0, 1.0)
        mel = logmel_from_wav(y)
    except Exception as e:  # pragma: no cover
        return {"id": task["id"], "error": str(e)}

    T = int(mel.shape[1])
    if T < 16:
        return {"id": task["id"], "error": "too_short"}
    syllables = task["pinyin"]
    d22 = task["durations"][1:-1]
    if len(d22) != len(syllables):
        return {"id": task["id"], "error": "bad_durations"}

    phone_durs: list[int] = []
    for d, syl in zip(d22, syllables):
        d24 = max(2, int(round(d / FPS22 * FPS24)))
        toks = syllable_tokens(syl)
        ini, fin, tone = "", "", "5"
        for t in toks:
            if not t[0].isdigit() and t[-1].isdigit() and len(t) > 1:
                fin, tone = t[:-1], t[-1]
            elif not t[0].isdigit():
                ini = t
        if ini:
            di = max(1, int(round(d24 * 0.32)))
            df = d24 - di
            if df < 1:
                df = 1
                di = max(1, d24 - 1)
            phone_durs.extend([di, df])
        else:
            phone_durs.append(d24)

    ids: list[int] = [task["bos"]]
    toks_out: list[str] = ["^"]
    for syl in syllables:
        for t in syllable_tokens(syl):
            ids.append(task["tokens"].get(t, task["tokens"]["unk"]))
            toks_out.append(t)
    ids.append(task["eos"])
    toks_out.append("$")

    phone_durs = scale_to_total(phone_durs, T - 2)
    durations = [1] + phone_durs + [1]
    assert sum(durations) == T

    mel_rel = f"data/v2/mel/{task['id']}.npy"
    dst = ROOT / mel_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    np.save(dst, mel.astype(np.float16))

    return {
        "id": task["id"], "text": task["text"], "pinyin": syllables,
        "phones": toks_out, "phoneme_ids": ids, "durations": durations,
        "n_frames": T, "duration_sec": round(T / FPS24, 3),
        "speaker": task["speaker"], "gender": task.get("gender", ""),
        "mel": mel_rel, "source": "aishell3", "license": "Apache-2.0",
        "research_use": True, "mel_stats": [float(mel.sum()), float((mel.astype(np.float64) ** 2).sum()), int(mel.size)],
    }


def build_tasks(rows: list[dict], tokens: dict) -> list[dict]:
    tasks = []
    for r in rows:
        wav = raw_wav(r["id"], r["speaker"])
        if not wav:
            continue
        tasks.append({
            "id": r["id"], "text": r.get("text", ""), "pinyin": r.get("pinyin", []),
            "durations": r.get("durations", []), "speaker": r["speaker"],
            "gender": r.get("gender", ""), "wav": str(wav),
            "tokens": tokens, "bos": tokens["^"], "eos": tokens["$"],
        })
    return tasks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from src.text.frontend import build_vocab

    OUT.mkdir(parents=True, exist_ok=True)
    splits = {}
    all_py: list[str] = []
    for name in ["pretrain_train", "pretrain_val", "eval_test"]:
        p = SRC / f"{name}.jsonl"
        rows = [json.loads(l) for l in p.open("r", encoding="utf-8") if l.strip()]
        if args.limit:
            rows = rows[: args.limit]
        splits[name] = rows
        for r in rows:
            all_py.extend(r["pinyin"])

    vocab = build_vocab(all_py)
    (OUT / "vocab.json").write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")

    speakers = sorted({r["speaker"] for rows in splits.values() for r in rows})
    spk_idx = {s: i for i, s in enumerate(speakers)}
    (OUT / "speakers.json").write_text(json.dumps({"speakers": speakers}, ensure_ascii=False, indent=2), encoding="utf-8")

    train_tasks = build_tasks(splits["pretrain_train"], vocab["tokens"])
    val_tasks = build_tasks(splits["pretrain_val"], vocab["tokens"])
    print(f"tasks train={len(train_tasks)} val={len(val_tasks)} vocab={vocab['size']}", flush=True)

    results: dict[str, list[dict]] = {}
    stat = [0.0, 0.0, 0]
    errors: Counter = Counter()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for group, tasks in (("train", train_tasks), ("val", val_tasks)):
            out_rows = []
            for r in ex.map(process, tasks, chunksize=16):
                if r is None or "error" in r:
                    errors[(r or {}).get("error", "none")] += 1
                    continue
                s, sq, n = r.pop("mel_stats")
                stat[0] += s
                stat[1] += sq
                stat[2] += n
                out_rows.append(r)
            results[group] = out_rows
            print(f"{group}: kept={len(out_rows)} errors={dict(errors)}", flush=True)

    mean = stat[0] / max(1, stat[2])
    var = stat[1] / max(1, stat[2]) - mean * mean
    stats = {"mean": round(mean, 6), "std": round(math.sqrt(max(var, 1e-9)), 6),
             "sample_rate": 24000, "n_mels": 80, "hop_length": 480,
             "n_fft": 1920, "win_length": 1920, "fmin": 0, "fmax": 12000,
             "frame_rate": 50}
    (OUT / "mel_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    for group, name in (("train", "train.jsonl"), ("val", "val.jsonl")):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for r in results[group]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    eval_rows = []
    for r in splits["eval_test"]:
        wav = raw_wav(r["id"], r["speaker"])
        if not wav:
            continue
        eval_rows.append({
            "id": r["id"], "text": r.get("text", ""), "speaker": r["speaker"],
            "gender": r.get("gender", ""), "wav": str(wav),
            "duration_sec": r.get("duration_sec", 0),
        })
    with (OUT / "eval.jsonl").open("w", encoding="utf-8") as f:
        for r in eval_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    train_spk = {r["speaker"] for r in results["train"]}
    unseen = sorted({r["speaker"] for r in eval_rows} - train_spk)
    report = {
        "vocab_size": vocab["size"], "train": len(results["train"]), "val": len(results["val"]),
        "eval": len(eval_rows), "speakers_train": len(train_spk),
        "speakers_eval": len({r["speaker"] for r in eval_rows}), "unseen_eval_speakers": unseen[:20],
        "train_hours": round(sum(r["duration_sec"] for r in results["train"]) / 3600, 2),
        "mel_stats": stats, "errors": dict(errors),
    }
    (OUT / "prep_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
