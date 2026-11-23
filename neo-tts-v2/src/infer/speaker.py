"""CAM++ speaker embedding (192-d) used as zero-shot timbre conditioning."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

CAMPPLUS = Path(r"D:\Env\git\ai-models\Fun-CosyVoice3-0.5B-2512\models\FunAudioLLM\Fun-CosyVoice3-0.5B-2512\campplus.onnx")
SR = 16000


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort

    opt = ort.SessionOptions()
    opt.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    opt.intra_op_num_threads = 2
    return ort.InferenceSession(str(CAMPPLUS), sess_options=opt, providers=["CPUExecutionProvider"])


def embed(y16: np.ndarray) -> np.ndarray:
    import torch
    import torchaudio.compliance.kaldi as kaldi

    wav = torch.from_numpy(np.asarray(y16, dtype=np.float32))
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)
    feat = kaldi.fbank(wav, num_mel_bins=80, dither=0, sample_frequency=SR)
    feat = feat - feat.mean(dim=0, keepdim=True)
    sess = _session()
    out = sess.run(None, {sess.get_inputs()[0].name: feat.unsqueeze(0).numpy()})[0]
    return np.asarray(out, dtype=np.float32).flatten()


def embed_file(path: str | Path) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=SR, mono=True)
    return embed(y)


def embed_bytes(data: bytes) -> np.ndarray:
    import io

    import librosa

    y, _ = librosa.load(io.BytesIO(data), sr=SR, mono=True)
    return embed(y)
