"""neo-tts v2 CFM acoustic-model pretraining with live monitoring.

Every 10 steps the trainer writes logs/train_status.json (read by the
FastAPI monitor) plus an append-only logs/train_metrics.jsonl; every
N steps it renders probe wavs through the frozen HiFT vocoder so the
web console can play the model *while it trains*.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.audio import mel as mel24  # noqa: E402
from src.data.dataset import MelDataset, collate  # noqa: E402
from src.models.cfm import CFMTTS  # noqa: E402

LOGS = ROOT / "logs"
CKPT = ROOT / "checkpoints" / "cfm"
PROBES = LOGS / "probes"

PROBE_TEXTS = [
    "今天的天气真不错，我们出去走走吧。",
    "这个问题我已经解释过很多次了，请你认真听。",
    "你觉得这件事情应该怎么处理呢？",
    "人工智能正在改变我们的生活方式。",
]


def now() -> float:
    return time.time()


def iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or now()))


def gpu_stats() -> dict:
    """Torch-only device memory stats.

    Never call nvidia-smi from the training loop: the driver query can block
    indefinitely on WDDM and stall training.  The web API polls nvidia-smi
    out-of-band for utilisation/temperature.
    """
    if not torch.cuda.is_available():
        return {}
    try:
        free, total = torch.cuda.mem_get_info()
        return {"gpu_mem_gb": round((total - free) / 1024**3, 2),
                "gpu_mem_total_gb": round(total / 1024**3, 2)}
    except Exception:
        return {}


class ModelEma:
    def __init__(self, model: torch.nn.Module, decay: float = 0.999):
        self.decay = decay
        self.shadow = {k: v.detach().clone().float() for k, v in model.state_dict().items() if v.dtype.is_floating_point}
        self.n = 0

    @torch.no_grad()
    def update(self, model: torch.nn.Module):
        self.n += 1
        d = min(self.decay, (1 + self.n) / (10 + self.n))
        for k, v in model.state_dict().items():
            if k in self.shadow:
                self.shadow[k].mul_(d).add_(v.detach().float(), alpha=1 - d)

    def state_dict(self):
        return self.shadow


def lr_at(step: int, base: float, warmup: int, total: int, final: float = 1e-5) -> float:
    if step < warmup:
        return base * (step + 1) / max(1, warmup)
    p = min(1.0, (step - warmup) / max(1, total - warmup))
    return final + 0.5 * (base - final) * (1 + math.cos(math.pi * p))


@torch.no_grad()
def validate(model, loader, device, max_batches: int = 20) -> float:
    model.eval()
    tot, n = 0.0, 0
    for i, b in enumerate(loader):
        if i >= max_batches:
            break
        b = {k: v.to(device, non_blocking=True) for k, v in b.items() if torch.is_tensor(v)}
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(b["ids"], b["lengths"], b["mel"], b["spk"], durations=b["durations"])
        tot += float(out["loss"].item())
        n += 1
    model.train()
    return tot / max(1, n)


def save_ckpt(path: Path, model, ema, opt, step, cfg, best_val, best_step):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    torch.save({
        "step": step, "model": model.state_dict(), "ema": ema.state_dict(),
        "optimizer": opt.state_dict(), "cfg": cfg,
        "best_val": best_val, "best_step": best_step,
    }, tmp)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--minutes", type=float, default=0, help="wall-clock budget; 0 = step bound only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--smoke", type=int, default=0)
    ap.add_argument("--val-every", type=int, default=500)
    ap.add_argument("--save-every", type=int, default=1000)
    ap.add_argument("--probe-every", type=int, default=1500)
    ap.add_argument("--resume", default="")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--text-layers", type=int, default=6)
    ap.add_argument("--d-model", type=int, default=384)
    ap.add_argument("--decoder-channels", type=int, default=256)
    args = ap.parse_args()

    for p in (LOGS, CKPT, PROBES):
        p.mkdir(parents=True, exist_ok=True)
    logf = open(LOGS / "train.log", "a", encoding="utf-8")

    def log(msg: str):
        line = f"[{iso()}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ds = MelDataset(ROOT / "data/v2/train.jsonl", ROOT / "data/v2/spk_emb.npy")
    val = MelDataset(ROOT / "data/v2/val.jsonl", ROOT / "data/v2/spk_emb.npy")
    vocab = json.loads((ROOT / "data/v2/vocab.json").read_text(encoding="utf-8"))
    n_spk = int(np.load(ROOT / "data/v2/spk_emb.npy").shape[0])
    log(f"dataset train={len(ds)} val={len(val)} speakers={n_spk} vocab={vocab['size']} device={device}")

    dl = DataLoader(ds, batch_size=args.batch, shuffle=True, num_workers=args.workers,
                    collate_fn=collate, pin_memory=True, drop_last=True, persistent_workers=args.workers > 0,
                    prefetch_factor=2 if args.workers > 0 else None)
    vdl = DataLoader(val, batch_size=args.batch, shuffle=False, num_workers=0, collate_fn=collate)

    cfg = {
        "vocab_size": vocab["size"], "n_mels": 80, "d_model": args.d_model,
        "text_layers": args.text_layers, "text_heads": 2, "spk_dim": 192,
        "decoder_channels": args.decoder_channels, "n_speakers": n_spk,
        "sample_rate": 24000, "hop_length": 480, "fmax": 12000,
    }
    model = CFMTTS(**{k: v for k, v in cfg.items() if k in {
        "vocab_size", "n_mels", "d_model", "text_layers", "text_heads", "spk_dim",
        "decoder_channels", "n_speakers"}}).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log(f"model params={n_params / 1e6:.2f}M")

    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, betas=(0.9, 0.99), weight_decay=1e-4)
    ema = ModelEma(model, 0.999)
    step0 = 0
    best_val, best_step = 1e9, 0
    resume_path = Path(args.resume) if args.resume else (CKPT / "last.pt" if (CKPT / "last.pt").exists() and not args.reset else None)
    if resume_path and resume_path.exists():
        ck = torch.load(resume_path, map_location=device, weights_only=False)
        model.load_state_dict(ck["model"])
        ema.shadow = {k: v.to(device) for k, v in ck["ema"].items()}
        ema.n = ck.get("step", 0)
        opt.load_state_dict(ck["optimizer"])
        step0 = ck.get("step", 0)
        best_val = ck.get("best_val", 1e9)
        best_step = ck.get("best_step", 0)
        log(f"resumed {resume_path} @ step {step0} best_val={best_val:.4f}")

    total_steps = step0 + args.steps if args.smoke == 0 else args.smoke
    config_out = dict(vars(args), params=n_params, total_steps=total_steps, cfg=cfg, started_at=iso())
    (LOGS / "train_config.json").write_text(json.dumps(config_out, indent=2), encoding="utf-8")

    hift = None
    spk_ref = None
    if args.smoke == 0:
        from src.serve_vocoder import get_hift
        from src.text.frontend import text_to_ids
        hift = get_hift(str(device))
        spk_ref = torch.from_numpy(np.load(ROOT / "data/v2/spk_emb.npy")[0]).float().to(device)[None]

    smoke = args.smoke > 0
    status_path = LOGS / ("smoke_status.json" if smoke else "train_status.json")
    metrics_path = LOGS / ("smoke_metrics.jsonl" if smoke else "train_metrics.jsonl")
    t_start = now()
    running = None
    model.train()
    it = iter(dl)
    epoch = 0
    probes: list[dict] = []
    if status_path.exists():
        try:
            probes = json.loads(status_path.read_text(encoding="utf-8")).get("probes", [])[-8:]
        except Exception:
            probes = []

    def write_status(step, loss, cfm, dur, lr, t_s, val_loss=None, training=True, extra=None):
        elapsed = now() - t_start
        done = max(1, step - step0)
        eta = (total_steps - step) / max(1e-6, done / elapsed) if step > step0 else 0
        st = {
            "schema": 2, "stage": "S2_CFM_PRETRAIN", "training": training,
            "started_at": config_out["started_at"], "updated_at": iso(),
            "step": step, "step_offset": step0, "total_steps": total_steps,
            "progress": round(step / max(1, total_steps), 4), "epoch": epoch,
            "loss": loss, "loss_cfm": cfm, "loss_dur": dur, "lr": lr,
            "it_s": round(done / max(1e-6, elapsed), 2), "elapsed_s": round(elapsed, 1),
            "eta_s": round(eta, 1), "val_loss": val_loss, "best_val": round(best_val, 5) if best_val < 1e8 else None,
            "best_step": best_step, "vram_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2) if device.type == "cuda" else 0,
            "params_m": round(n_params / 1e6, 2), "batch": args.batch,
            "probes": probes[-8:], "checkpoint": str(CKPT / "best.pt"),
        }
        st.update(gpu_stats())
        if extra:
            st.update(extra)
        status_path.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    def do_probe(step):
        if hift is None:
            return
        from src.text.frontend import text_to_ids
        from src.serve_vocoder import vocode
        for i, text in enumerate(PROBE_TEXTS):
            ids, toks = text_to_ids(text, str(ROOT / "data/v2/vocab.json"))
            idt = torch.tensor([ids], device=device)
            lt = torch.tensor([len(ids)], device=device)
            t0 = now()
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                out = model.synthesize(idt, lt, spk_ref, n_steps=2, temperature=0.0, seed=1234 + i)
            m = out["mel"].float().squeeze(0).cpu()
            wav = vocode(hift, mel24.denormalize(m))
            dur = len(wav) / 24000
            path = PROBES / f"step_{step:06d}_{i}.wav"
            import soundfile as sf
            sf.write(str(path), wav, 24000, subtype="PCM_16")
            probes.append({"step": step, "text": text, "wav": f"logs/probes/{path.name}",
                           "dur_sec": round(dur, 2), "rtf": round((now() - t0) / max(1e-6, dur), 3),
                           "tokens": len(ids)})
        del probes[:-8]
        log(f"probe @{step}: {len(PROBE_TEXTS)} clips")

    last_t = now()
    step = step0
    while step < total_steps:
        if args.minutes and (now() - t_start) > args.minutes * 60:
            log(f"time budget reached at step {step}")
            break
        try:
            b = next(it)
        except StopIteration:
            epoch += 1
            it = iter(dl)
            continue
        b = {k: v.to(device, non_blocking=True) for k, v in b.items() if torch.is_tensor(v)}
        lr = lr_at(step, args.lr, args.warmup, total_steps)
        for g in opt.param_groups:
            g["lr"] = lr
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
            out = model(b["ids"], b["lengths"], b["mel"], b["spk"], durations=b["durations"])
        loss = out["loss"]
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        ema.update(model)
        step += 1

        l = float(loss.item())
        running = l if running is None else 0.98 * running + 0.02 * l
        if step % 20 == 0:
            rec = {"step": step, "loss": round(l, 5), "loss_ema": round(running, 5),
                   "cfm": round(float(out["loss_cfm"].item()), 5), "dur": round(float(out["loss_dur"].item()), 5),
                   "reg": round(float(out["loss_reg"].item()), 5),
                   "lr": lr, "it_s": round(20 / max(1e-6, now() - last_t), 2),
                   "frames": int(b["mel"].shape[-1]), "epoch": epoch, "ts": iso()}
            last_t = now()
            with metrics_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if step % 10 == 0:
                write_status(step, round(l, 5), float(out["loss_cfm"].item()), float(out["loss_dur"].item()),
                             lr, last_t, training=True)

        if step % args.val_every == 0:
            vl = validate(model, vdl, device)
            log(f"val @{step}: loss={vl:.5f} (best={best_val:.5f})")
            if vl < best_val:
                best_val, best_step = vl, step
                save_ckpt(CKPT / "best.pt", model, ema, opt, step, cfg, best_val, best_step)
            write_status(step, round(l, 5), float(out["loss_cfm"].item()), float(out["loss_dur"].item()),
                         lr, now(), vl, training=True)

        if step % args.probe_every == 0:
            try:
                do_probe(step)
            except Exception as e:
                log(f"probe failed: {e}")
            write_status(step, round(l, 5), float(out["loss_cfm"].item()), float(out["loss_dur"].item()),
                         lr, now(), training=True)

        if step % args.save_every == 0:
            save_ckpt(CKPT / "last.pt", model, ema, opt, step, cfg, best_val, best_step)
            tmp = CKPT / "ema.pt.tmp"
            torch.save({"step": step, "ema": ema.state_dict(), "cfg": cfg}, tmp)
            os.replace(tmp, CKPT / "ema.pt")

    save_ckpt(CKPT / "last.pt", model, ema, opt, step, cfg, best_val, best_step)
    torch.save({"step": step, "ema": ema.state_dict(), "cfg": cfg}, CKPT / "ema.pt")
    if best_val >= 1e8:
        save_ckpt(CKPT / "best.pt", model, ema, opt, step, cfg, best_val, best_step)
    write_status(step, float(loss.item()) if 'loss' in dir() else 0.0, 0.0, 0.0, 0.0, now(),
                 training=False, extra={"finished_at": iso()})
    if smoke:
        elapsed = now() - t_start
        calib = {"steps": step - step0, "elapsed_s": round(elapsed, 2),
                 "it_s": round((step - step0) / max(1e-6, elapsed), 2),
                 "vram_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 2) if device.type == "cuda" else 0,
                 "params_m": round(n_params / 1e6, 2), "batch": args.batch,
                 "frames_per_batch": args.batch * 241, "gpu": gpu_stats(),
                 "at": iso()}
        (LOGS / "calibration.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")
        log(f"calibration {calib}")
    log(f"done @ step {step}")
    logf.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
