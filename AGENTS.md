# Guidance for coding agents

Before changing this project:

1. Read [`docs/README.md`](docs/README.md), then the task-relevant design/status docs.
2. Read `backend/README.md` or `frontend/README.md` and the relevant source before editing. For container/hosting work, also read `deploy/README.md`.
3. Treat the BUP simulator as an external, published, deterministic **simulation**. Never connect this project to real fuel infrastructure or claim simulated results are real.
4. Backend provides validated read-only simulator REST/SSE integration plus the intelligence engine in `backend/app/intelligence/`. Keep ALL intelligence code (forecasting, detection, planning, training, execution) inside that package; do not spread it into other modules. Simulator writes happen only through the engine's approval/execution flow with idempotency keys and revalidation.
5. Frontend code must call FastAPI using relative same-origin `/api/backend/...` paths. Next.js rewrites these server-side using `BACKEND_API_URL`; do not hard-code a browser-facing `localhost` URL.
6. Preserve REST as source of truth. SSE events prompt REST refresh; after reconnect, refresh the full state.
7. Keep credentials out of source, docs, logs, and commits. Use environment variables for service URLs and secrets.
8. Add deterministic tests for behavior changes and update `docs/work-plan-and-status.md` when a milestone ships.

## Checks

- Backend: `cd backend && python -m pytest`
- Frontend: `cd frontend && npm run lint && npm run typecheck && npm run format:check && npm run build`
