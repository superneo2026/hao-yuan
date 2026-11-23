"""Inference engine for neo-tts v2 (CFM acoustic model + HiFT vocoder)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch

from src.audio import mel as mel24
from src.infer import speaker as spk_mod
from src.models.cfm import CFMTTS
from src.serve_vocoder import get_hift, vocode
from src.text.frontend import text_to_ids

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "v2"


class V2Engine:
    def __init__(self, ckpt: str | Path | None = None, device: str | None = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ck = self._pick_ckpt(ckpt)
        blob = None
        last_err = None
        for cand in [ck, ROOT / "checkpoints/cfm/best.pt", ROOT / "checkpoints/cfm/last.pt", ROOT / "checkpoints/cfm/ema.pt"]:
            try:
                if Path(cand).exists():
                    blob = torch.load(cand, map_location="cpu", weights_only=False)
                    ck = cand
                    break
            except Exception as e:  # partially written checkpoint — try the next
                last_err = e
        if blob is None:
            raise RuntimeError(f"no readable v2 checkpoint ({last_err})")
        self.ckpt_path = str(ck)
        cfg = {k: v for k, v in blob["cfg"].items() if k in {
            "vocab_size", "n_mels", "d_model", "text_layers", "text_heads", "spk_dim",
            "decoder_channels", "n_speakers"}}
        self.model = CFMTTS(**cfg).to(self.device).eval()
        state = blob.get("ema") or blob.get("model")
        missing = self.model.load_state_dict(state, strict=False)
        self.load_info = {"missing": len(missing.missing_keys), "unexpected": len(missing.unexpected_keys)}
        self.step = blob.get("step", 0)
        self.vocoder = get_hift(self.device)
        self.vocab_path = DATA / "vocab.json"
        self.spk_emb = np.load(DATA / "spk_emb.npy")
        self.speakers = json.loads((DATA / "speakers.json").read_text(encoding="utf-8"))["speakers"]
        self.refs = json.loads((DATA / "refs.json").read_text(encoding="utf-8")) if (DATA / "refs.json").exists() else {}
        self.sr = mel24.SAMPLE_RATE

    def _pick_ckpt(self, ckpt):
        if ckpt:
            p = Path(ckpt)
            if not p.is_absolute():
                p = ROOT / p
            if p.exists():
                return p
        for name in ("ema.pt", "best.pt", "last.pt"):
            p = ROOT / "checkpoints" / "cfm" / name
            if p.exists():
                return p
        raise FileNotFoundError("no v2 checkpoint found")

    def speaker_embedding(self, name: str | None = None) -> tuple[torch.Tensor, str]:
        name = name or self.speakers[0]
        if name in self.speakers:
            e = self.spk_emb[self.speakers.index(name)]
        else:
            e = self.spk_emb[0]
        return torch.from_numpy(e).float().to(self.device)[None], name

    def embedding_from_audio(self, path: str | Path) -> torch.Tensor:
        return torch.from_numpy(spk_mod.embed_file(path)).float().to(self.device)[None]

    @torch.no_grad()
    def synthesize(self, text: str, speaker: str | None = None, ref_audio: str | Path | None = None,
                   seed: int | None = 1234, n_steps: int = 2, temperature: float = 0.0,
                   duration_std: float = 0.12) -> dict:
        ids, toks = text_to_ids(text, str(self.vocab_path))
        if len(ids) <= 2:
            raise ValueError("空文本或无法解析出拼音")
        t0 = time.time()
        idt = torch.tensor([ids], device=self.device)
        lt = torch.tensor([len(ids)], device=self.device)
        if ref_audio:
            spk = self.embedding_from_audio(ref_audio)
            used = Path(ref_audio).name
        else:
            spk, used = self.speaker_embedding(speaker)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=self.device == "cuda"):
            out = self.model.synthesize(idt, lt, spk, n_steps=n_steps, temperature=temperature,
                                        duration_std=duration_std, seed=seed)
        mel_t = out["mel"].float().squeeze(0).cpu()
        wav = vocode(self.vocoder, mel24.denormalize(mel_t))
        dur = len(wav) / self.sr
        elapsed = time.time() - t0
        durs = out["durations"][0, : len(toks)].detach().cpu().numpy().astype(int).tolist()
        return {
            "audio": wav, "sample_rate": self.sr, "text": text, "speaker": used,
            "tokens": toks, "durations": durs, "n_steps": n_steps,
            "temperature": temperature, "seed": seed,
            "duration_sec": round(dur, 3), "latency_sec": round(elapsed, 3),
            "rtf": round(elapsed / max(1e-6, dur), 3),
            "mel": mel_t.numpy(), "n_frames": int(mel_t.shape[1]),
            "checkpoint": Path(self.ckpt_path).name, "ckpt_step": int(self.step),
        }

    def speaker_list(self) -> list[dict]:
        return [{"id": s, "gender": "", "ref": self.refs.get(s, "")} for s in self.speakers]
