# Backend

FastAPI service for the BUP Fuel Supply Simulator. It owns simulator communication: browser requests go through FastAPI, simulator read responses are validated, the dashboard and health endpoints are backend-facing, and the intelligence engine provides advisory forecasts, detections, and allocation plans. Simulator state and demand history remain simulator-owned; the engine keeps its training data in process memory and reloads it from the simulator after a restart.

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001 --no-access-log
```

The simulator defaults to `http://localhost:8000`; configure `SIMULATOR_BASE_URL` if needed. The backend defaults to an 8-second upstream timeout, configurable with `SIMULATOR_TIMEOUT_SECONDS`. The API has no operator authentication/authorization yet. Keep simulator writes disabled on publicly reachable deployments.

- Swagger UI: `http://localhost:8001/docs`
- Backend liveness: `http://localhost:8001/api/v1/health`
- Dependency status: `http://localhost:8001/api/v1/status` (503 when unavailable/stale)
- Protected metrics: `http://localhost:8001/api/v1/observability/metrics` (requires `Authorization: Bearer <OBSERVABILITY_TOKEN>`)
- Dashboard snapshot: `http://localhost:8001/api/v1/dashboard/snapshot`
- Frontend allocation API: `http://localhost:8001/api/v1/allocations`
- Granular simulator reads: `http://localhost:8001/api/v1/simulator`
- Intelligence API: `http://localhost:8001/api/v1/intelligence`

The dashboard snapshot fetches simulator resources concurrently and returns valid partial state with per-resource availability/freshness statuses. Granular reads cover health, instance, regions, depots, stations, routes, supply arrivals, events, allocations, demand history, and metrics. The SSE stream is available at `/api/v1/simulator/stream`; documented event payloads are validated before forwarding. Simulator state/history are not copied into an application database or a local history store.

The frontend calls same-origin `/api/backend/*` through the Next.js server rewrite; only FastAPI talks to the simulator. See [`../docs/frontend-backend-api.md`](../docs/frontend-backend-api.md) for the UI contract and [`../deploy/observability.md`](../deploy/observability.md) for monitoring configuration.

Run tests from this directory:

```bash
python -m pytest
```

## Intelligence engine

`app/intelligence/` contains all forecasting, detection, planning, projection, and orchestration code:

| Module | Responsibility |
| --- | --- |
| `config.py` | Operator-tunable policy (horizons, reserve, execution switches). |
| `priors.py` | Documented world priors for cold-start forecasting. |
| `forecaster.py` | Seasonal profile + EWMA ensemble and pooled online ridge regression with prequential error tracking. |
| `projection.py` | Shared inventory projection (receipt-before-use, outage-aware, capacity-conflict-aware). |
| `inbound.py` | Confirmed station-bound inbound extracted from the simulator allocation ledger. |
| `detection.py` | Observed anomaly/state detectors and predictive risk findings. |
| `allocator.py` | Constraint-aware greedy planner, whole-plan feasibility validation, what-if impact. |
| `training.py` | Bootstrap training from simulator-owned `/v1/demand-history`. |
| `service.py` | Snapshot collection, one run per tick, alert registry, plan approval/execution and submission reconciliation. |
| `routes.py` | `/api/v1/intelligence/*` HTTP API. |

Key behaviors:

- The engine reads and validates simulator state/history through FastAPI's upstream client. It trains on demand-history returned by the simulator and holds its current learning state in process memory; it does not create a duplicate persistent demand-history store or database.
- A background loop computes forecasts, detections, and recommendations. It never writes to the simulator automatically. A write can occur only through `POST /api/v1/intelligence/plans/{id}/execute` after explicit plan approval and fresh-state revalidation.
- Execution requires **both** `SIMULATOR_WRITES_ENABLED=true` and `INTELLIGENCE_EXECUTION_ENABLED=true`. Both switches default to `false`. This is an operational safety gate, not authentication; do not expose write endpoints publicly until operator access control is implemented.
- Recommendations are validated against depot inventory/reserves, dispatch capacity, route limits, station capacity, and existing confirmed inbound. Stale or inconsistent snapshots do not authorize a plan for execution. Ambiguous outcomes are reconciled by the idempotency key against `GET /v1/allocations`; requests are never blindly retried.
- Probabilities are explicitly marked uncalibrated; risk tiers are deterministic projections, not calibrated probabilities. Missing/unavailable values are not replaced with invented simulator state.

Useful engine environment variables: `INTELLIGENCE_EXECUTION_ENABLED` (default `false`), `INTELLIGENCE_LOOP_SECONDS` (poll interval, default 5), `INTELLIGENCE_HORIZON_TICKS` (default 24), `INTELLIGENCE_DEPOT_RESERVE` (default 0.10), `INTELLIGENCE_PLAN_EXPIRY_TICKS` (default 2), and `INTELLIGENCE_LOOP_ENABLED` (set false to disable the background loop).

The detailed endpoint and model contract is in [`INTELLIGENCE_API.md`](INTELLIGENCE_API.md).

## Fake simulator for local development

When the organizer's simulator image is not available, a deterministic test double is included:

```bash
uvicorn tools.fake_simulator:app --port 8000
```

It implements the documented public API plus `/admin/demo/shortage` and `/admin/demo/route_disruption` helpers for demos. It is a development tool, not the official simulator.

## Container deployment

See [observability setup](../deploy/observability.md) for JSON logs, the Site24x7 plugin, health UI, fault demonstrations and load testing. Metrics are process-local; use the default single worker. Monitoring is read-only and does not automatically retry simulator writes.

From the repository root, `docker compose up -d --build backend` starts this API together with the simulator service it depends on. See [`../deploy/README.md`](../deploy/README.md) for local/full-stack and VPS deployment instructions. Do not publish the simulator/admin port publicly.
