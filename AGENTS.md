# AGENTS.md

## Project commands

- Backend tests: `cd api && python -m pytest -q`
- Backend run: `cd api && python main.py` (port 8030)
- Frontend dev: `cd web && npm run dev` (port 8130, proxies `/api` and `/ws` to 8030)
- Frontend build: `cd web && npm run build`
- Production: build the frontend, then run the API; the API serves `web/dist` at `/`.

## Architecture invariants

- `core/` is the kernel. It must not import from `plugins/`.
- Business capabilities belong in `plugins/<name>/` and register through `register(ctx)`.
- Tool handlers receive `(ctx: ToolContext, args: dict)` and must respect `ctx.workspace`.
- Every state-changing tool that touches the filesystem or executes commands must be `confirm=True` and high risk.
- Events are append-only in SQLite and broadcast over WebSocket. Do not log secrets into event payloads.
- The API envelope is `{ code, data, message }`; `code` is 200 on success.
- Frontend state lives in `web/src/stores/app.js`; API calls go through `web/src/api/client.js`.

## Verification discipline

- After backend changes: run `python -m pytest -q` in `api/`.
- After frontend changes: run `npm run build` in `web/`.
- For UI changes, take Playwright screenshots at 1440x900 and 430x900 with the local Chrome executable, and verify there are no console errors or 404 resources.
- Never claim live-model verification without a configured API key; use mock-mode tests and state that limitation explicitly.
