"""Evaluate the *inference APIs* before (v1 :8001) and after (v2 :8002).

T1 unseen speakers / T2 in-domain / T3 hard cases.  Metrics: CER (SenseVoice),
CAM++ timbre similarity, F0 median & semitone span, 8k/10k high-frequency
energy ratio, duration ratio, RTF, SQUIM PESQ/STOI.  Writes
reports/v2/eval_summary.json + wav assets for the HTML report.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

V1_ROOT = Path(r"D:\Env\git\neo-tts\v1")
DATA = ROOT / "data" / "v2"
OUT = ROOT / "reports" / "v2"
AUDIO = OUT / "audio"
ASR_DIR = Path(r"D:\Env\git\ai-voice-robot\models\SenseVoiceSmall")
if not (ASR_DIR / "model.pt").exists():
    ASR_DIR = Path(r"D:\Env\git\ai-models\SenseVoiceSmall")
TAG = re.compile(r"<\|[^|]+\|>")
NON_WORD = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]+")

HARD = [
    "二零二六年十一月二十四日上午十点三十分，会议正式开始。",
    "这次活动的报名截止日期是十二月三十一日，请尽快提交材料。",
    "他说的那句话，我到现在也没有完全想明白。",
    "你能再解释一遍吗？我确实没有听清楚。",
    "太棒了！我们终于把这个问题彻底解决了！",
    "长江三峡工程是世界上规模最大的水利枢纽工程之一。",
    "请把第三项和第五项的数据重新核对一遍，然后发给我。",
    "研究人员发现，长期规律的睡眠对记忆巩固有显著帮助。",
    "如果你明天有空，我们可以一起去博物馆看看展览。",
    "价格从一千九百九十九元降到了八百八十八元。",
]


def norm(s: str) -> str:
    s = TAG.sub("", s)
    s = NON_WORD.sub("", s)
    return s.lower()


class Extras:
    def __init__(self):
        self.asr = None
        self.squim = None
        self._campplus = None

    def cer(self, ref: str, audio_path: Path) -> tuple[float, str]:
        if self.asr is None:
            from funasr import AutoModel

            self.asr = AutoModel(model=str(ASR_DIR), disable_update=True)
        r = self.asr.generate(input=str(audio_path), language="zh", use_itn=False)
        hyp = TAG.sub("", r[0].get("text", "")) if r else ""
        a, b = norm(ref), norm(hyp)
        if not a or not b:
            return 1.0, hyp
        import jiwer

        return float(jiwer.cer(a, b)), hyp

    def squim_scores(self, audio_path: Path) -> dict:
        try:
            import librosa
            import torch
            import torchaudio

            if self.squim is None:
                self.squim = torchaudio.pipelines.SQUIM_OBJECTIVE.get_model().eval()
            y, _ = librosa.load(str(audio_path), sr=16000, mono=True)
            y = y[: 16000 * 30]
            y = y / (max(1e-8, float(np.max(np.abs(y)))))
            wav = torch.from_numpy(y).float()[None, :]
            with torch.no_grad():
                est = self.squim(wav)
            return {"pesq": float(est[0]), "stoi": float(est[1]), "estoi": float(est[2])}
        except Exception:
            return {}

    def sim(self, a: Path, b: Path) -> float | None:
        try:
            from src.infer.speaker import embed_file

            x, y = embed_file(a), embed_file(b)
            return float(np.dot(x, y) / (np.linalg.norm(x) * np.linalg.norm(y) + 1e-8))
        except Exception:
            return None


def f0_stats(path: Path) -> dict:
    import librosa

    y, sr = librosa.load(str(path), sr=24000, mono=True)
    f0, _, _ = librosa.pyin(y, fmin=60, fmax=400, sr=sr, frame_length=1024)
    v = f0[~np.isnan(f0)]
    if v.size < 5:
        return {"f0_median": None, "f0_span_st": None}
    p5, p95 = np.percentile(v, 5), np.percentile(v, 95)
    return {"f0_median": float(np.median(v)), "f0_span_st": float(12 * math.log2(max(p95, 1) / max(p5, 1)))}


def hf_stats(path: Path) -> dict:
    import librosa

    y, sr = librosa.load(str(path), sr=24000, mono=True)
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=256)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=1024)
    total = float(S[freqs <= 12000].sum() + 1e-8)
    return {"hf8": float(S[(freqs >= 8000) & (freqs <= 12000)].sum() / total),
            "hf10": float(S[(freqs >= 10000) & (freqs <= 12000)].sum() / total)}


def http_json(url: str, payload: dict, timeout: int = 240) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url: str, dst: Path):
    with urllib.request.urlopen(url, timeout=120) as r:
        dst.write_bytes(r.read())


def upload_reference(api: str, path: Path) -> str | None:
    """Zero-shot setup: 5-10 s of the target speaker's real audio."""
    try:
        import requests

        with path.open("rb") as f:
            r = requests.post(f"{api}/api/tts/reference", files={"file": (path.name, f, "audio/wav")}, timeout=120)
        r.raise_for_status()
        return r.json().get("ref_id")
    except Exception as e:
        print(f"reference upload failed: {e}", flush=True)
        return None


def raw_wav(utt: str, spk: str) -> Path | None:
    for split in ("train", "test"):
        p = V1_ROOT / "data" / "aishell3" / split / "wav" / spk / f"{utt}.wav"
        if p.exists():
            return p
    p = V1_ROOT / "data" / "aishell3_22k" / "wavs" / spk / f"{utt}.wav"
    return p if p.exists() else None


def build_prompts(limit: int) -> list[dict]:
    import soundfile as sf

    train_spk = set()
    for line in (DATA / "train.jsonl").open("r", encoding="utf-8"):
        train_spk.add(json.loads(line)["speaker"])
    prompt_sets = []

    # T1: speakers that exist in the AISHELL-3 tree but were withheld from training
    held_dirs = set()
    for split in ("train", "test"):
        d = V1_ROOT / "data" / "aishell3" / split / "wav"
        if d.exists():
            held_dirs |= {p.name for p in d.iterdir() if p.is_dir()}
    held = held_dirs - train_spk
    cjk = re.compile(r"[\u4e00-\u9fff]")
    per_spk: dict[str, list[dict]] = {}
    for line in (V1_ROOT / "data/aishell3/train/content.txt").open("r", encoding="utf-8", errors="replace"):
        parts = line.rstrip("\n").split("\t", 1)
        if len(parts) < 2:
            continue
        utt = parts[0][:-4] if parts[0].lower().endswith(".wav") else parts[0]
        spk = utt[:7]
        if spk not in held:
            continue
        text = "".join(cjk.findall(parts[1]))
        if len(text) < 6:
            continue
        wav = raw_wav(utt, spk)
        if not wav:
            continue
        per_spk.setdefault(spk, []).append({"id": utt, "text": text, "speaker": spk, "gt": str(wav)})
    t1 = []
    depth = 0
    while len(t1) < limit and depth < 4:
        for spk in sorted(per_spk):
            if len(per_spk[spk]) > depth:
                t1.append(per_spk[spk][depth])
            if len(t1) >= limit:
                break
        depth += 1
    if not t1:
        for line in (DATA / "eval.jsonl").open("r", encoding="utf-8"):
            t1.append(json.loads(line))
            if len(t1) >= limit:
                break
    for r in t1:
        prompt_sets.append({"slice": "T1 未见说话人", "id": r["id"], "text": r["text"],
                            "speaker": r["speaker"], "gt": r.get("gt") or r.get("wav")})

    t2 = []
    for line in (DATA / "val.jsonl").open("r", encoding="utf-8"):
        r = json.loads(line)
        w = raw_wav(r["id"], r["speaker"])
        if w:
            t2.append({"slice": "T2 域内", "id": r["id"], "text": r["text"], "speaker": r["speaker"], "gt": str(w)})
        if len(t2) >= limit:
            break
    prompt_sets.extend(t2)

    for i, text in enumerate(HARD[:limit]):
        prompt_sets.append({"slice": "T3 难例", "id": f"hard_{i:02d}", "text": text,
                            "speaker": None, "gt": None})
    return prompt_sets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1", default="http://127.0.0.1:8001")
    ap.add_argument("--v2", default="http://127.0.0.1:8002")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--skip-squim", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for s in ("v1", "v2", "gt"):
        (AUDIO / s).mkdir(parents=True, exist_ok=True)

    prompts = build_prompts(max(3, args.limit // 2))
    print(f"prompts={len(prompts)} slices={sorted({p['slice'] for p in prompts})}", flush=True)
    ex = Extras()
    items = []
    t_start = time.time()

    for i, p in enumerate(prompts):
        rec = {"id": p["id"], "slice": p["slice"], "text": p["text"], "speaker": p["speaker"],
               "gt_audio": None, "v1": {}, "v2": {}}
        gt_path = None
        if p.get("gt"):
            src = Path(p["gt"])
            if src.exists():
                import librosa
                import soundfile as sf

                y, _ = librosa.load(str(src), sr=24000, mono=True)
                gt_name = f"{p['id']}.wav"
                sf.write(str(AUDIO / "gt" / gt_name), y, 24000, subtype="PCM_16")
                rec["gt_audio"] = gt_name
                rec["gt_dur"] = round(len(y) / 24000, 3)
                gt_path = AUDIO / "gt" / gt_name
                rec["gt"] = {**f0_stats(gt_path), **hf_stats(gt_path)}
                rec["ref_id"] = upload_reference(args.v2, gt_path)

        for system, api in (("v1", args.v1), ("v2", args.v2)):
            try:
                t0 = time.time()
                if system == "v1":
                    r = http_json(f"{api}/api/tts", {"text": p["text"], "n_iter": 32})
                    name = f"{p['id']}_v1.wav"
                    download(f"{api}{r['audio_url']}", AUDIO / "v1" / name)
                    srec = {"latency": r.get("latency"), "rtf": r.get("rtf"), "dur": r.get("duration")}
                else:
                    payload = {"text": p["text"], "speaker": p["speaker"], "ref_id": rec.get("ref_id"),
                               "seed": 1234, "n_steps": 2, "temperature": 0.0, "tag": "eval"}
                    r = http_json(f"{api}/api/tts/synthesize", payload)
                    name = f"{p['id']}_v2.wav"
                    download(f"{api}{r['audio_url']}", AUDIO / "v2" / name)
                    srec = {"latency": r.get("latency_sec"), "rtf": r.get("rtf"), "dur": r.get("duration_sec"),
                            "ckpt_step": r.get("ckpt_step"), "checkpoint": r.get("checkpoint")}
                wav_path = AUDIO / system / name
                cer, hyp = ex.cer(p["text"], wav_path)
                srec.update({"audio": name, "asr": hyp, "cer": cer, **f0_stats(wav_path), **hf_stats(wav_path)})
                if gt_path is not None:
                    srec["dur_ratio"] = round(float(srec.get("dur") or 0) / max(1e-6, rec["gt_dur"]), 3)
                    srec["sim"] = ex.sim(gt_path, wav_path)
                if not args.skip_squim:
                    srec.update(ex.squim_scores(wav_path))
                rec[system] = srec
            except Exception as e:
                rec[system] = {"error": f"{type(e).__name__}: {e}"}
        items.append(rec)
        print(f"[{i + 1}/{len(prompts)}] {p['id']} v1_cer={rec['v1'].get('cer')} v2_cer={rec['v2'].get('cer')}", flush=True)

    def agg(rows, key):
        vals = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(float(np.mean(vals)), 4) if vals else None

    def summarize(rows) -> dict:
        v1s = [r["v1"] for r in rows]
        v2s = [r["v2"] for r in rows]
        out = {"n": len(rows)}
        for name, rows_s in (("v1", v1s), ("v2", v2s)):
            out[name] = {
                "mean_cer": agg(rows_s, "cer"), "mean_sim": agg(rows_s, "sim"),
                "mean_f0_median": agg(rows_s, "f0_median"), "mean_f0_span_st": agg(rows_s, "f0_span_st"),
                "mean_hf8": agg(rows_s, "hf8"), "mean_hf10": agg(rows_s, "hf10"),
                "mean_dur_ratio": agg(rows_s, "dur_ratio"), "mean_rtf": agg(rows_s, "rtf"),
                "mean_pesq": agg(rows_s, "pesq"), "mean_stoi": agg(rows_s, "stoi"),
                "mean_estoi": agg(rows_s, "estoi"),
                "failures": sum(1 for x in rows_s if x.get("error")),
            }
        # relative win proxies
        both = [(r["v1"], r["v2"]) for r in rows if r["v1"].get("cer") is not None and r["v2"].get("cer") is not None]
        out["cer_win_v2"] = round(sum(1 for a, b in both if b["cer"] < a["cer"]) / max(1, len(both)), 3)
        sims = [(r["v1"].get("sim"), r["v2"].get("sim")) for r in rows]
        sims = [(a, b) for a, b in sims if a is not None and b is not None]
        out["sim_win_v2"] = round(sum(1 for a, b in sims if b > a) / max(1, len(sims)), 3) if sims else None
        return out

    gt_rows = [r["gt"] for r in items if r.get("gt")]
    summary = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(items),
               "limit": args.limit, "elapsed_s": round(time.time() - t_start, 1),
               "gt": {"n": len(gt_rows), "mean_f0_median": agg(gt_rows, "f0_median"),
                      "mean_f0_span_st": agg(gt_rows, "f0_span_st"),
                      "mean_hf8": agg(gt_rows, "hf8"), "mean_hf10": agg(gt_rows, "hf10"),
                      "mean_dur": round(float(np.mean([r["gt_dur"] for r in items if r.get("gt_dur")])), 3) if gt_rows else None},
               "prompt_counts": {s: sum(1 for p in prompts if p["slice"] == s) for s in sorted({p["slice"] for p in prompts})},
               "systems": summarize(items)}
    slices = []
    for sname in sorted({p["slice"] for p in prompts}):
        rows = [r for r in items if r["slice"] == sname]
        slices.append({"name": sname, **summarize(rows)})
    summary["slices"] = slices
    summary["items"] = items
    summary["blind_pairs"] = [
        {"id": r["id"], "order": ["v1", "v2"] if i % 2 == 0 else ["v2", "v1"],
         "A": r["v1"].get("audio"), "B": r["v2"].get("audio")}
        for i, r in enumerate(items)
    ]
    (OUT / "eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("n", "elapsed_s", "systems")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
