# BUP Fuel Supply Intelligence & Resilience Platform

Monorepo for the BUP CSE Fest hackathon project:

- `backend/` — FastAPI frontend API for validated simulator state, a dashboard snapshot, SSE proxying, and explicitly gated operator allocation commands.
- `frontend/` — Next.js App Router workspace configured with TypeScript, Tailwind CSS v4, and shadcn/ui. The data-driven operator dashboard will be built on this foundation.

## Run the frontend

Requirements: Node.js 20.9 or newer.

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev -- --hostname 0.0.0.0 --port 3000
```

The frontend uses a same-origin rewrite: browser requests to `/api/backend/*` are proxied server-side to FastAPI. The default target is `http://127.0.0.1:8001`; set `BACKEND_API_URL` in `frontend/.env.local` if the backend runs elsewhere. Do not call the simulator or localhost directly from browser code.

## Run the backend

Requirements: Python 3.11 or newer.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The simulator uses its documented default port `8000`, so the backend listens on `8001`. Set `SIMULATOR_BASE_URL` if the simulator is exposed elsewhere. Backend docs are at <http://localhost:8001/docs>; health is at <http://localhost:8001/api/v1/health>. Allocation write routes are disabled by default; do not enable them on a public backend until operator access is protected.

## Docker / deployment

Run the full simulator + backend + frontend stack with `docker compose up --build -d`. See [`deploy/README.md`](deploy/README.md) for the all-in-one hackathon setup and the split VPS-backend/Vercel-frontend option.

## Team documentation

Start at [`docs/README.md`](docs/README.md) for team context and the [frontend ↔ backend API contract](docs/frontend-backend-api.md), which describes the browser paths, snapshot response, operator action requests, and current security boundary.

## Checks

- Frontend: `cd frontend && npm run lint && npm run typecheck && npm run build`
- Backend: `cd backend && python -m pytest`
