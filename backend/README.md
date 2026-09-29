# Backend

FastAPI frontend API for the BUP Fuel Supply Simulator. Simulator responses are validated before being returned to clients. The API includes a best-effort dashboard snapshot and explicit allocation/cancellation command routes. Writes are disabled by default; no recommendation or automatic decision logic is implemented.

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001 --no-access-log
```

The simulator defaults to `http://localhost:8000`; configure `SIMULATOR_BASE_URL` if needed. The backend defaults to an 8-second upstream timeout, configurable with `SIMULATOR_TIMEOUT_SECONDS`. Set `SIMULATOR_WRITES_ENABLED=true` only in a trusted operator environment. There is no operator authentication/authorization yet; do not enable writes on a publicly reachable backend.

- Swagger UI: `http://localhost:8001/docs`
- Backend liveness: `http://localhost:8001/api/v1/health`
- Dependency status: `http://localhost:8001/api/v1/status` (503 when unavailable/stale)
- Protected metrics: `http://localhost:8001/api/v1/observability/metrics` (requires `Authorization: Bearer <OBSERVABILITY_TOKEN>`)
- Dashboard snapshot: `http://localhost:8001/api/v1/dashboard/snapshot`
- Frontend allocation API: `http://localhost:8001/api/v1/allocations`
- Granular simulator reads: `http://localhost:8001/api/v1/simulator`

The snapshot fetches resources concurrently, returns valid partial state with per-resource availability/freshness statuses, and reports whether the simulator tick was unchanged during retrieval. Simulator state/history are not copied into an application database. Granular read resources include health, instance, regions, depots (list/detail), stations (list/detail), routes, supply arrivals, events, allocations, demand history, and metrics. The SSE stream is available at `/api/v1/simulator/stream`; documented event payloads are validated before forwarding.

See [`../docs/frontend-backend-api.md`](../docs/frontend-backend-api.md) for the UI request contract. The frontend calls same-origin `/api/backend/*` through the Next.js server rewrite; only FastAPI talks to the simulator.

Run tests from this directory:

```bash
python -m pytest
```

## Container deployment

See [observability setup](../deploy/observability.md) for JSON logs, the Site24x7 plugin, health UI, fault demonstrations and load testing. Metrics are process-local; use the default single worker. Monitoring is read-only and does not automatically retry simulator writes.

From the repository root, `docker compose up -d --build backend` starts this API together with the simulator service it depends on. See [`../deploy/README.md`](../deploy/README.md) for local/full-stack and VPS deployment instructions. Do not publish the simulator/admin port publicly.
