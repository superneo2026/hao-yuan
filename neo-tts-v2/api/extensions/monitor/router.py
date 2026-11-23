# 训练实时监控：状态 / 曲线 / 日志 / 探针 / WebSocket 推送
from __future__ import annotations

import asyncio
import json
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from configs.config import CKPT_DIR, DATA_DIR, LOG_DIR, PREFIX, V2_VERSION

router = APIRouter(prefix=PREFIX)

_GPU_CACHE = {"ts": 0.0, "data": {}, "busy": False}
_GPU_QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed"


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _tail_jsonl(path: Path, limit: int = 200) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return rows[-limit:]
    return rows[-limit:]


def _poll_gpu() -> None:
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={_GPU_QUERY}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=3).stdout.strip().splitlines()[0]
        util, used, total, temp, power, fan = [x.strip() for x in out.split(",")]
        data = {"util": float(util), "mem_used_mb": float(used), "mem_total_mb": float(total),
                "temp": float(temp), "power": float(power), "fan": float(fan)}
        _GPU_CACHE.update(data=data, ts=time.time())
    except Exception as e:
        if not _GPU_CACHE["data"]:
            _GPU_CACHE.update(data={"error": str(e)}, ts=time.time())
    finally:
        _GPU_CACHE["busy"] = False


def _gpu() -> dict:
    """Return the cached GPU snapshot; refresh in a daemon thread so a hung
    nvidia-smi / driver query can never block a request."""
    if time.time() - _GPU_CACHE["ts"] > 2.0 and not _GPU_CACHE["busy"]:
        _GPU_CACHE["busy"] = True
        threading.Thread(target=_poll_gpu, daemon=True).start()
    return _GPU_CACHE["data"]


def _proc() -> dict:
    try:
        import psutil

        p = psutil.Process()
        return {"api_cpu": p.cpu_percent(interval=None), "api_rss_mb": round(p.memory_info().rss / 1024**2, 1)}
    except Exception:
        return {}


def _checkpoints() -> list[dict]:
    out = []
    if CKPT_DIR.exists():
        for p in sorted(CKPT_DIR.glob("*.pt")):
            st = p.stat()
            out.append({"name": p.name, "mb": round(st.st_size / 1024**2, 1),
                        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))})
    return out


PIPELINE = [
    {"key": "S0", "name": "环境标定", "budget_h": 0.5, "desc": "mel round-trip · 200 步冒烟 · 反推步数"},
    {"key": "S1", "name": "数据构建", "budget_h": 0.5, "desc": "AISHELL-3 → 24k/80band mel · 音素对齐 · CAM++"},
    {"key": "S2a", "name": "CFM 预训练", "budget_h": 1.5, "desc": "137 说话人 · 19.9h · 时长监督 + 随机流采样"},
    {"key": "S2b", "name": "CFM 续训", "budget_h": 0.5, "desc": "余弦退火 · EMA · 探针门禁"},
    {"key": "S3", "name": "匹配标定", "budget_h": 0.2, "desc": "mel 统计锁定 · 声码器 round-trip"},
    {"key": "S5", "name": "评测导出", "budget_h": 0.3, "desc": "v1/v2 接口评测 · HTML 报告"},
]


def _stage_view(status: dict) -> list[dict]:
    stages = []
    probe = check = False
    cur = status.get("step", 0) / max(1, status.get("total_steps", 1))
    for s in PIPELINE:
        st = dict(s)
        if s["key"] == "S0":
            st["state"] = "done"
            st["progress"] = 1.0
        elif s["key"] == "S1":
            st["state"] = "done" if (DATA_DIR / "train.jsonl").exists() else "pending"
            st["progress"] = 1.0 if st["state"] == "done" else 0.0
        elif s["key"] in ("S2a", "S2b"):
            if status.get("training"):
                active = cur < 0.55 if s["key"] == "S2a" else cur >= 0.55
                st["state"] = "running" if active else ("done" if s["key"] == "S2a" else "pending")
            elif status.get("step", 0) > 0:
                st["state"] = "done"
            else:
                st["state"] = "pending"
            st["progress"] = round(cur, 3) if st["state"] == "running" else (1.0 if st["state"] == "done" else 0.0)
        elif s["key"] == "S3":
            done = (not status.get("training")) and status.get("step", 0) > 0
            st["state"] = "done" if done else "pending"
            st["progress"] = 1.0 if done else 0.0
        else:
            report = Path(__file__).resolve().parents[3] / "reports" / "v2" / "eval_summary.json"
            done = (not status.get("training")) and report.exists()
            st["state"] = "done" if done else "pending"
            st["progress"] = 1.0 if done else 0.0
        stages.append(st)
    return stages


def build_status() -> dict:
    status = _read_json(LOG_DIR / "train_status.json", {})
    cfg = _read_json(LOG_DIR / "train_config.json", {})
    prep = _read_json(DATA_DIR / "prep_report.json", {})
    payload = {
        "version": V2_VERSION,
        "training": bool(status.get("training", False)),
        "stage": status.get("stage", "idle"),
        "step": status.get("step", 0),
        "total_steps": status.get("total_steps", cfg.get("total_steps", 0)),
        "progress": status.get("progress", 0.0),
        "epoch": status.get("epoch", 0),
        "loss": status.get("loss"),
        "loss_cfm": status.get("loss_cfm"),
        "loss_dur": status.get("loss_dur"),
        "lr": status.get("lr"),
        "it_s": status.get("it_s"),
        "elapsed_s": status.get("elapsed_s", 0),
        "eta_s": status.get("eta_s"),
        "val_loss": status.get("val_loss"),
        "best_val": status.get("best_val"),
        "best_step": status.get("best_step"),
        "params_m": status.get("params_m", cfg.get("params") and round(cfg["params"] / 1e6, 2)),
        "batch": status.get("batch", cfg.get("batch")),
        "vram_gb": status.get("vram_gb"),
        "updated_at": status.get("updated_at"),
        "started_at": status.get("started_at", cfg.get("started_at")),
        "finished_at": status.get("finished_at"),
        "probes": status.get("probes", []),
        "checkpoints": _checkpoints(),
        "gpu": _gpu(),
        "api": _proc(),
        "dataset": prep,
        "stages": _stage_view(status),
        "config": cfg,
    }
    return payload


@router.get("/monitor/status")
def monitor_status():
    return build_status()


@router.get("/monitor/curve")
def monitor_curve(limit: int = 1200):
    rows = _tail_jsonl(LOG_DIR / "train_metrics.jsonl", max(10, min(limit, 5000)))
    return {"count": len(rows), "points": rows}


@router.get("/monitor/logs")
def monitor_logs(tail: int = 200):
    p = LOG_DIR / "train.log"
    lines: list[str] = []
    if p.exists():
        with p.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-max(10, min(tail, 2000)):]
    return {"lines": [l.rstrip("\n") for l in lines]}


@router.get("/monitor/probes")
def monitor_probes():
    d = LOG_DIR / "probes"
    if not d.exists():
        return {"items": []}
    items = []
    for p in sorted(d.glob("*.wav"), key=lambda x: x.name)[-48:]:
        items.append({"name": p.name, "url": f"/api/monitor/probe/{p.name}",
                      "kb": round(p.stat().st_size / 1024, 1)})
    return {"items": items}


@router.get("/monitor/probe/{name}")
def monitor_probe_file(name: str):
    p = (LOG_DIR / "probes" / name).resolve()
    base = (LOG_DIR / "probes").resolve()
    if base not in p.parents or not p.exists():
        return {"error": "not found"}
    return FileResponse(str(p), media_type="audio/wav", filename=name)


@router.websocket("/monitor/ws")
async def monitor_ws(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            await ws.send_json(build_status())
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
