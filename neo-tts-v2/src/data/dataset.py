from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from src.audio import mel as mel24

ROOT = Path(__file__).resolve().parents[2]


class MelDataset(Dataset):
    def __init__(self, manifest: str | Path, spk_emb_path: str | Path, max_frames: int = 1200,
                 min_frames: int = 16):
        self.root = ROOT
        self.rows: list[dict] = []
        for line in Path(manifest).open("r", encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                n = int(r.get("n_frames", 0))
                if min_frames <= n <= max_frames:
                    self.rows.append(r)
        self.spk = np.load(spk_emb_path).astype(np.float32)
        names = json.loads(Path(spk_emb_path).with_name("speakers.json").read_text(encoding="utf-8"))["speakers"]
        self.spk_index = {s: i for i, s in enumerate(names)}
        self.stats = mel24.load_stats()

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, idx: int):
        r = self.rows[idx]
        m = np.load(self.root / r["mel"]).astype(np.float32)
        m = (m - self.stats[0]) / self.stats[1]
        spk = self.spk[self.spk_index[r["speaker"]]]
        ids = torch.tensor(r["phoneme_ids"], dtype=torch.long)
        dur = torch.tensor(r["durations"], dtype=torch.float32)
        n = min(m.shape[1], int(dur.sum().item()))
        return {
            "ids": ids, "durations": dur, "mel": torch.from_numpy(m[:, :n]),
            "spk": torch.from_numpy(spk), "id": r["id"],
        }


def collate(batch: list[dict]) -> dict:
    b = len(batch)
    max_ph = max(x["ids"].numel() for x in batch)
    max_mel = max(x["mel"].shape[1] for x in batch)
    ids = torch.zeros(b, max_ph, dtype=torch.long)
    dur = torch.zeros(b, max_ph, dtype=torch.float32)
    mel = torch.zeros(b, 80, max_mel, dtype=torch.float32)
    lens = torch.ones(b, dtype=torch.long)
    for i, x in enumerate(batch):
        t = x["ids"].numel()
        ids[i, :t] = x["ids"]
        dur[i, :t] = x["durations"]
        lens[i] = t
        mel[i, :, : x["mel"].shape[1]] = x["mel"]
    return {
        "ids": ids, "lengths": lens, "durations": dur, "mel": mel,
        "spk": torch.stack([x["spk"] for x in batch]), "ids_str": [x["id"] for x in batch],
    }
