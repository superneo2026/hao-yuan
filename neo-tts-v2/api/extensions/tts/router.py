# TTS V2 推理接口（CFM + HiFT），含与 v1 服务的同文对比
from __future__ import annotations

import io
import json
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from fastapi.responses import FileResponse

from configs.config import OUTPUT_DIR, PREFIX, V1_URL

router = APIRouter(prefix=PREFIX)

_ENGINE = {"obj": None, "lock": threading.Lock(), "error": ""}
REFS = OUTPUT_DIR / "refs"
REFS.mkdir(parents=True, exist_ok=True)


class SynthRequest(BaseModel):
    text: str
    speaker: str | None = None
    ref_id: str | None = None
    seed: int | None = 1234
    n_steps: int = 2
    temperature: float = 0.0
    duration_std: float = 0.12
    tag: str = "ui"


def get_engine():
    with _ENGINE["lock"]:
        if _ENGINE["obj"] is None:
            from src.infer.engine import V2Engine

            _ENGINE["obj"] = V2Engine()
        return _ENGINE["obj"]


def _safe(text: str, n: int = 18) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text).strip("_")
    return s[:n] or "tts"


def _save(wav, tag: str, text: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9]+", "", tag) or "tts"
    name = f"{tag}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.wav"
    import soundfile as sf

    sf.write(str(OUTPUT_DIR / name), wav, 24000, subtype="PCM_16")
    return name


@router.get("/tts/state")
def tts_state():
    eng = _ENGINE["obj"]
    if eng is None:
        return {"loaded": False, "error": _ENGINE["error"]}
    return {"loaded": True, "checkpoint": Path(eng.ckpt_path).name, "ckpt_step": eng.step,
            "load_info": eng.load_info, "device": eng.device, "sample_rate": eng.sr}


@router.get("/tts/speakers")
def tts_speakers():
    eng = get_engine()
    return {"speakers": eng.speaker_list()}


@router.post("/tts/synthesize")
def tts_synthesize(req: SynthRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "text is empty")
    if len(text) > 200:
        raise HTTPException(400, "text too long (max 200 chars)")
    try:
        eng = get_engine()
        ref = None
        if req.ref_id:
            p = REFS / f"{req.ref_id}.wav"
            if p.exists():
                ref = p
        res = eng.synthesize(text, speaker=req.speaker, ref_audio=ref, seed=req.seed,
                             n_steps=max(1, min(req.n_steps, 32)),
                             temperature=req.temperature, duration_std=req.duration_std)
        name = _save(res["audio"], req.tag, text)
        meta = {k: res[k] for k in ("sample_rate", "speaker", "duration_sec", "latency_sec", "rtf",
                                    "n_steps", "temperature", "seed", "n_frames", "checkpoint", "ckpt_step")}
        meta["audio_url"] = f"/api/tts/audio/{name}"
        meta["text"] = text
        meta["tokens"] = res["tokens"][:200]
        return meta
    except Exception as exc:
        raise HTTPException(500, f"{type(exc).__name__}: {exc}")


@router.get("/tts/audio/{name}")
def tts_audio(name: str):
    p = (OUTPUT_DIR / name).resolve()
    if OUTPUT_DIR.resolve() not in p.parents or not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(p), media_type="audio/wav", filename=name)


@router.post("/tts/reference")
async def tts_reference(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    import librosa
    import soundfile as sf

    try:
        y, _ = librosa.load(io.BytesIO(raw), sr=16000, mono=True)
    except Exception as exc:
        raise HTTPException(400, f"decode failed: {exc}")
    y = y[: 16000 * 10]
    rid = uuid.uuid4().hex[:10]
    sf.write(str(REFS / f"{rid}.wav"), y, 16000, subtype="PCM_16")
    return {"ref_id": rid, "duration_sec": round(len(y) / 16000, 2), "url": f"/api/tts/reference/{rid}"}


@router.get("/tts/reference/{rid}")
def tts_reference_get(rid: str):
    p = REFS / f"{rid}.wav"
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(p), media_type="audio/wav", filename=p.name)


def _v1_synth(text: str, n_iter: int = 32) -> dict:
    body = json.dumps({"text": text, "n_iter": n_iter}).encode("utf-8")
    req = urllib.request.Request(f"{V1_URL}/api/tts", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    url = data.get("audio_url", "")
    if url:
        with urllib.request.urlopen(f"{V1_URL}{url}", timeout=60) as r:
            wav_bytes = r.read()
        import librosa
        import soundfile as sf

        y, _ = librosa.load(io.BytesIO(wav_bytes), sr=24000, mono=True)
        name = f"v1_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.wav"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        sf.write(str(OUTPUT_DIR / name), y, 24000, subtype="PCM_16")
        data["v2_audio_url"] = f"/api/tts/audio/{name}"
    return data


@router.post("/tts/compare")
def tts_compare(req: SynthRequest):
    v2 = tts_synthesize(req)
    out = {"v2": v2, "v1": None, "v1_error": ""}
    try:
        out["v1"] = _v1_synth(req.text.strip())
    except Exception as exc:
        out["v1_error"] = f"{type(exc).__name__}: {exc}"
    return out


@router.get("/tts/presets")
def tts_presets():
    return {"items": [
        "今天的天气真不错，我们出去走走吧。",
        "这个问题我已经解释过很多次了，请你认真听。",
        "你觉得这件事情应该怎么处理呢？",
        "人工智能正在改变我们的生活方式。",
        "二零二六年十一月二十四日，北京。",
        "他说：“别担心，一切都会好起来的。”",
    ]}
