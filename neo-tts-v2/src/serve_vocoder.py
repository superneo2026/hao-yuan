"""24 kHz HiFT neural vocoder (CosyVoice-3, pretrained) for neo-tts v2.

Single-stage mel -> waveform; no Griffin-Lim, no cascaded resampling.
The vocoder's mel convention is exactly src/audio/mel.py (24 kHz, 80 mel,
hop 480, fmax 12 kHz), verified by a round-trip probe in S0.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

COSY_ROOT = Path(r"D:\Env\git\ai-models\Fun-CosyVoice3-0.5B-2512\third_party\CosyVoice")
HIFT_WEIGHTS = Path(r"D:\Env\git\ai-models\Fun-CosyVoice3-0.5B-2512\models\FunAudioLLM\Fun-CosyVoice3-0.5B-2512\hift.pt")
SAMPLE_RATE = 24000
_HIFT = {}


def _build_hift():
    for p in (COSY_ROOT, COSY_ROOT / "third_party" / "Matcha-TTS"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from cosyvoice.hifigan.f0_predictor import CausalConvRNNF0Predictor
    from cosyvoice.hifigan.generator import CausalHiFTGenerator

    f0 = CausalConvRNNF0Predictor(num_class=1, in_channels=80, cond_channels=512)
    g = CausalHiFTGenerator(
        in_channels=80, base_channels=512, nb_harmonics=8, sampling_rate=24000,
        nsf_alpha=0.1, nsf_sigma=0.003, nsf_voiced_threshold=10,
        upsample_rates=[8, 5, 3], upsample_kernel_sizes=[16, 11, 7],
        istft_params={"n_fft": 16, "hop_len": 4},
        resblock_kernel_sizes=[3, 7, 11],
        resblock_dilation_sizes=[[1, 3, 5], [1, 3, 5], [1, 3, 5]],
        source_resblock_kernel_sizes=[7, 7, 11],
        source_resblock_dilation_sizes=[[1, 3, 5], [1, 3, 5], [1, 3, 5]],
        lrelu_slope=0.1, audio_limit=0.99, conv_pre_look_right=4, f0_predictor=f0,
    )
    g.load_state_dict(torch.load(HIFT_WEIGHTS, map_location="cpu", weights_only=False))
    return g.eval()


def get_hift(device: str = "cuda"):
    if device not in _HIFT:
        _HIFT[device] = _build_hift().to(device).eval()
    return _HIFT[device]


@torch.no_grad()
def vocode(hift, log_mel: torch.Tensor, device: str | None = None) -> np.ndarray:
    """log_mel [80, T] (denormalized) -> float32 wav, peak-normalized to 0.97."""
    if log_mel.dim() == 2:
        log_mel = log_mel.unsqueeze(0)
    dev = device or next(hift.parameters()).device
    mel = log_mel.float().to(dev)
    audio, _ = hift.inference(mel)
    audio = audio.squeeze().float().cpu().numpy()
    peak = float(np.max(np.abs(audio)) + 1e-8)
    return (audio / peak * 0.97).astype(np.float32)


def warmup(device: str = "cuda") -> None:
    h = get_hift(device)
    z = torch.randn(1, 80, 50, device=device)
    vocode(h, z)
