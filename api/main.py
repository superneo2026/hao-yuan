from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from configs.configs import APP_NAME, APP_VERSION, SERVER_HOST, SERVER_PORT, WEB_DIST_DIR
from core.harness import harness_instance, init_harness
from extensions import approvals, fs, plugins, sessions, settings, skills, system, usage
from extensions.ws import ws_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    harness = await init_harness()
    yield
    await harness.shutdown()


harness = harness_instance()
app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in (system, sessions, skills, settings, fs, usage, plugins, approvals):
    app.include_router(module.router)

for router in harness.plugin_routers:
    app.include_router(router)

app.add_api_websocket_route("/ws", ws_endpoint)


@app.get("/api")
async def api_root():
    return {"code": 200, "data": {"name": APP_NAME, "version": APP_VERSION, "docs": "/docs"}}


@app.get("/api/ready")
async def ready():
    return {"code": 200, "data": {"ready": True, "plugins": harness.plugin_status()}}


if (WEB_DIST_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=str(WEB_DIST_DIR), html=True), name="web")
else:

    @app.get("/")
    async def root():
        return {
            "code": 200,
            "data": {
                "name": APP_NAME,
                "version": APP_VERSION,
                "message": "HaoYuan API is running. Build the web app in web/ or run the Vite dev server.",
                "docs": "/docs",
            },
        }


if __name__ == "__main__":
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
