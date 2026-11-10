from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from configs.configs import APP_NAME, APP_VERSION, SERVER_HOST, SERVER_PORT, WEB_DIST_DIR
from configs.runtime import resolve_free_port, update_runtime
from core.harness import harness_instance, init_harness
from core.telemetry import telemetry
from extensions import approvals, fs, marketplace, plugins, sessions, settings, skills, supervisor, system, usage
from extensions.ws import ws_endpoint


@asynccontextmanager
async def lifespan(app: FastAPI):
    harness = await init_harness()
    telemetry.start()
    yield
    await telemetry.stop()
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

for module in (system, sessions, skills, settings, fs, usage, plugins, marketplace, approvals, supervisor):
    app.include_router(module.router)

for middleware, kwargs in harness.plugin_middlewares:
    app.add_middleware(middleware, **kwargs)

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


harness.attach_app(app)
harness.mount_all_plugin_routers()


if __name__ == "__main__":
    port = resolve_free_port(SERVER_HOST, SERVER_PORT)
    update_runtime(api_port=port)
    if port != SERVER_PORT:
        print(f"[HaoYuan] port {SERVER_PORT} is in use, falling back to {port}", flush=True)
    print(f"[HaoYuan] API serving at http://{SERVER_HOST}:{port}", flush=True)
    uvicorn.run("main:app", host=SERVER_HOST, port=port, reload=False)
