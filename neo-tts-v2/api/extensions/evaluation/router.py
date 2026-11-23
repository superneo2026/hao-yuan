# 训练前 / 后推理接口评测：读取 reports/v2 产物，支持后台触发
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from configs.config import PREFIX, PROJECT, REPORT_DIR

router = APIRouter(prefix=PREFIX)
_RUN = {"proc": None, "started": 0.0}
_LOCK = threading.Lock()
EVAL_LOG = PROJECT / "logs" / "eval.log"


@router.get("/eval/summary")
def eval_summary():
    p = REPORT_DIR / "eval_summary.json"
    if not p.exists():
        return {"ready": False, "hint": "run tools/evaluate_v2.py or POST /api/eval/run"}
    data = json.loads(p.read_text(encoding="utf-8"))
    data["ready"] = True
    return data


@router.get("/eval/items")
def eval_items():
    p = REPORT_DIR / "eval_summary.json"
    if not p.exists():
        return {"items": []}
    return {"items": json.loads(p.read_text(encoding="utf-8")).get("items", [])}


@router.get("/eval/audio/{system}/{name}")
def eval_audio(system: str, name: str):
    base = (REPORT_DIR / "audio" / system).resolve()
    p = (base / name).resolve()
    if base not in p.parents or not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(str(p), media_type="audio/wav", filename=name)


@router.post("/eval/run")
def eval_run(limit: int = 20):
    with _LOCK:
        proc = _RUN.get("proc")
        if proc is not None and proc.poll() is None:
            return {"started": False, "message": "evaluation already running"}
        EVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        f = open(EVAL_LOG, "w", encoding="utf-8")
        cmd = [sys.executable, str(PROJECT / "tools" / "evaluate_v2.py"), "--limit", str(limit)]
        proc = subprocess.Popen(cmd, cwd=str(PROJECT), stdout=f, stderr=subprocess.STDOUT)
        _RUN.update(proc=proc, started=time.time())
    return {"started": True, "pid": proc.pid, "limit": limit}


@router.get("/eval/status")
def eval_status():
    proc = _RUN.get("proc")
    running = proc is not None and proc.poll() is None
    tail = []
    if EVAL_LOG.exists():
        tail = EVAL_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    return {"running": running, "pid": proc.pid if proc else None,
            "elapsed_s": round(time.time() - _RUN["started"], 1) if _RUN["started"] else 0,
            "tail": tail,
            "ready": (REPORT_DIR / "eval_summary.json").exists()}
