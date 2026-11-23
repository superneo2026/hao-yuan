"""Precompute CAM++ per-speaker mean embeddings + 16 kHz reference clips."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.infer.speaker import embed_file  # noqa: E402

V1 = Path(r"D:\Env\git\neo-tts\v1")
OUT = ROOT / "data" / "v2"


def raw_wav(utt: str, spk: str) -> Path | None:
    for split in ("train", "test"):
        p = V1 / "data" / "aishell3" / split / "wav" / spk / f"{utt}.wav"
        if p.exists():
            return p
    p = V1 / "data" / "aishell3_22k" / "wavs" / spk / f"{utt}.wav"
    return p if p.exists() else None


def main() -> int:
    import librosa
    import soundfile as sf

    speakers = json.loads((OUT / "speakers.json").read_text(encoding="utf-8"))["speakers"]
    per_spk: dict[str, list[str]] = {s: [] for s in speakers}
    for name in ("train.jsonl", "val.jsonl"):
        for line in (OUT / name).open("r", encoding="utf-8"):
            r = json.loads(line)
            per_spk.setdefault(r["speaker"], []).append(r["id"])

    refs = OUT / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    embs = []
    ref_map = {}
    for i, spk in enumerate(speakers):
        ids = per_spk.get(spk, [])
        vecs = []
        used = 0
        for utt in ids:
            wav = raw_wav(utt, spk)
            if not wav:
                continue
            try:
                vecs.append(embed_file(wav))
                used += 1
            except Exception:
                continue
            if used >= 12:
                break
        if not vecs:
            embs.append(np.zeros(192, dtype=np.float32))
            continue
        embs.append(np.mean(np.stack(vecs), axis=0).astype(np.float32))
        ref_src = raw_wav(ids[0], spk) if ids else None
        if ref_src:
            y, _ = librosa.load(str(ref_src), sr=16000, mono=True)
            y = y[: 16000 * 8]
            sf.write(str(refs / f"{spk}.wav"), y, 16000, subtype="PCM_16")
            ref_map[spk] = f"data/v2/refs/{spk}.wav"
        if (i + 1) % 20 == 0:
            print(f"{i + 1}/{len(speakers)}", flush=True)

    np.save(OUT / "spk_emb.npy", np.stack(embs))
    (OUT / "refs.json").write_text(json.dumps(ref_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"speakers": len(speakers), "emb": list(np.stack(embs).shape),
                      "refs": len(ref_map)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
