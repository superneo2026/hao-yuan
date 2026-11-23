"""neo-tts v2 mel front-end: a single source of truth.

24 kHz / 80 mel / hop 480 / fmax 12 kHz, matching the pretrained
CosyVoice-3 HiFT vocoder that ships on this machine.

The transform is byte-for-byte the one the HiFT generator was trained
with (librosa slaney filterbank + torch.stft, reflect pad (n_fft-hop)/2,
center=False, log(clamp(x, 1e-5))).  Training, inference and the vocoder
all import THIS module so the mel convention can never drift.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

SAMPLE_RATE = 24000
N_FFT = 1920
HOP_LENGTH = 480
WIN_LENGTH = 1920
N_MELS = 80
F_MIN = 0.0
F_MAX = 12000.0
LOG_FLOOR = 1e-5
FRAME_RATE = SAMPLE_RATE / HOP_LENGTH  # 50 Hz

ROOT = Path(__file__).resolve().parents[2]
STATS_PATH = ROOT / "data" / "v2" / "mel_stats.json"


@lru_cache(maxsize=4)
def _basis(device: str = "cpu"):
    import librosa

    m = librosa.filters.mel(
        sr=SAMPLE_RATE, n_fft=N_FFT, n_mels=N_MELS, fmin=F_MIN, fmax=F_MAX,
        htk=False, norm="slaney",
    )
    return torch.from_numpy(m).float().to(device)


@lru_cache(maxsize=4)
def _window(device: str = "cpu"):
    return torch.hann_window(WIN_LENGTH).to(device)


def mel_spectrogram(y: torch.Tensor) -> torch.Tensor:
    """[B, T] or [T] waveform in [-1, 1] -> log-mel [B, 80, frames]."""
    if y.dim() == 1:
        y = y.unsqueeze(0)
    y = y.float()
    device = y.device
    pad = (N_FFT - HOP_LENGTH) // 2
    y = torch.nn.functional.pad(y.unsqueeze(1), (pad, pad), mode="reflect").squeeze(1)
    spec = torch.stft(
        y, N_FFT, hop_length=HOP_LENGTH, win_length=WIN_LENGTH,
        window=_window(device=str(device)), center=False, pad_mode="reflect",
        normalized=False, onesided=True, return_complex=True,
    )
    mag = torch.sqrt(spec.real.pow(2) + spec.imag.pow(2) + 1e-9)
    mel = torch.matmul(_basis(device=str(device)), mag)
    return torch.log(torch.clamp(mel, min=LOG_FLOOR))


def frames_for_samples(n: int) -> int:
    """Number of mel frames produced for n samples (center=False, padded)."""
    return 1 + (int(n) + 2 * ((N_FFT - HOP_LENGTH) // 2) - N_FFT) // HOP_LENGTH


@lru_cache(maxsize=1)
def load_stats() -> tuple[float, float]:
    if STATS_PATH.exists():
        d = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        return float(d["mean"]), float(d["std"])
    return -5.0, 2.6


def normalize(mel: torch.Tensor) -> torch.Tensor:
    mean, std = load_stats()
    return (mel - mean) / std


def denormalize(mel: torch.Tensor) -> torch.Tensor:
    mean, std = load_stats()
    return mel * std + mean


def logmel_from_wav(y: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        return mel_spectrogram(torch.from_numpy(np.asarray(y, dtype=np.float32))).squeeze(0).numpy()
