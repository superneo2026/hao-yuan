# neo-tts v2 API 入口（端口 8002）
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

API_DIR = Path(__file__).resolve().parent
PROJECT = API_DIR.parent
for p in (str(API_DIR), str(PROJECT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from configs.config import HOST, PORT, V2_VERSION, WEB_DIST  # noqa: E402
from configs.modules import modules  # noqa: E402

app = FastAPI(title="neo-tts v2 console", version=V2_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module_name, module_path in modules.items():
    module = __import__(module_path, fromlist=["router"])
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "neo-tts-v2", "version": V2_VERSION}


@app.get("/api/version")
def version():
    return {"version": V2_VERSION, "name": "neo-tts v2", "sample_rate": 24000,
            "acoustic": "CFM flow-matching (Matcha-style)", "vocoder": "HiFT 24kHz (pretrained)"}


PLAN_DIR = PROJECT / "test" / "plan"
REPORT_DIR = PROJECT / "test" / "testing"
if PLAN_DIR.exists():
    app.mount("/plan", StaticFiles(directory=str(PLAN_DIR), html=True), name="plan")
if REPORT_DIR.exists():
    app.mount("/report", StaticFiles(directory=str(REPORT_DIR), html=True), name="report")

if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")


if __name__ == "__main__":
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
