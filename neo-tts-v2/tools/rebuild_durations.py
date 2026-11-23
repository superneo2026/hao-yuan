"""Rebuild v2 phoneme durations with leading/trailing silence preserved.

The first v2 build forced bos/eos to 1 frame and stretched speech across the
whole clip, which shifted every phone against the mel.  The v1 forced
alignment already contains the real leading/trailing silence in durations[0]
and durations[-1]; keep them (converted to 50 fps) and scale the full token
sequence to the mel length.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_v2_data import scale_to_total  # noqa: E402
from src.text.frontend import syllable_tokens  # noqa: E402

V1 = Path(r"D:\Env\git\neo-tts\v1")
SRC = V1 / "data" / "aishell3_22k_aligned" / "manifests"
DATA = ROOT / "data" / "v2"
FPS22 = 22050 / 256
FPS24 = 24000 / 480


def main() -> int:
    aligned = {}
    for name in ("pretrain_train", "pretrain_val"):
        for line in (SRC / f"{name}.jsonl").open("r", encoding="utf-8"):
            r = json.loads(line)
            aligned[r["id"]] = r

    report = {"fixed": 0, "missing": 0, "bos_frames": [], "eos_frames": []}
    for split in ("train", "val"):
        p = DATA / f"{split}.jsonl"
        rows = [json.loads(l) for l in p.open("r", encoding="utf-8") if l.strip()]
        out = []
        for row in rows:
            src = aligned.get(row["id"])
            if not src or len(src.get("durations", [])) < 3:
                report["missing"] += 1
                out.append(row)
                continue
            T = int(row["n_frames"])
            d24 = [max(0, int(round(x / FPS22 * FPS24))) for x in src["durations"]]
            phone_durs = []
            for d, syl in zip(d24[1:-1], src["pinyin"]):
                toks = syllable_tokens(syl)
                has_initial = len(toks) == 2
                d = max(2, d)
                if has_initial:
                    di = max(1, int(round(d * 0.32)))
                    df = max(1, d - di)
                    phone_durs.extend([di, df])
                else:
                    phone_durs.append(d)
            seq = [max(1, d24[0])] + phone_durs + [max(1, d24[-1])]
            durations = scale_to_total(seq, T)
            row["durations"] = durations
            row["bos_frames"] = durations[0]
            row["eos_frames"] = durations[-1]
            report["fixed"] += 1
            report["bos_frames"].append(durations[0])
            report["eos_frames"].append(durations[-1])
            out.append(row)
        with p.open("w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(split, len(out), flush=True)

    import statistics

    report["bos_median"] = statistics.median(report["bos_frames"]) if report["bos_frames"] else 0
    report["eos_median"] = statistics.median(report["eos_frames"]) if report["eos_frames"] else 0
    report.pop("bos_frames")
    report.pop("eos_frames")
    (DATA / "duration_fix_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
