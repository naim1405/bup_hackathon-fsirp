# Backend

FastAPI integration with the BUP Fuel Supply Simulator. Simulator responses are validated before being returned to API clients. The backend hosts the validated simulator read proxy **and** the intelligence engine (forecasting, detection, allocation planning, and operator approval/submission), which lives entirely under `app/intelligence/`.

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The simulator defaults to `http://localhost:8000`; configure `SIMULATOR_BASE_URL` if needed. The backend defaults to an 8-second upstream timeout, configurable with `SIMULATOR_TIMEOUT_SECONDS`.

- Swagger UI: `http://localhost:8001/docs`
- Backend liveness: `http://localhost:8001/api/v1/health`
- Simulator read API: `http://localhost:8001/api/v1/simulator`
- Intelligence API: `http://localhost:8001/api/v1/intelligence` (status, prediction, detection, alerts, recommendations, plan approve/execute)

Run tests from this directory:

```bash
python -m pytest
```

## Intelligence engine

`app/intelligence/` contains everything intelligence-related and nothing else:

| Module | Responsibility |
| --- | --- |
| `config.py` | Operator-tunable policy (horizons, reserve, execution switch). Env-overridable. |
| `priors.py` | Documented world priors for cold-start forecasting. |
| `forecaster.py` | Trained demand model: seasonal profile + EWMA ensemble + pooled online ridge regression per fuel, with prequential error tracking and empirical uncertainty. |
| `projection.py` | The single shared inventory projector (receipt-before-use, outage-aware, capacity-conflict-aware). |
| `inbound.py` | Confirmed station-bound inbound extracted from the allocation ledger. |
| `detection.py` | Observed anomaly/state detectors + predictive risk findings. |
| `allocator.py` | Constraint-aware greedy planner, whole-plan feasibility validation, what-if impact. |
| `training.py` | JSON persistence of demand history + trained model, bootstrap training from `/v1/demand-history`. |
| `service.py` | Orchestrator: snapshot collection, one run per tick, alert registry, approval/execution with idempotency keys and revalidation. |
| `routes.py` | `/api/v1/intelligence/*` HTTP API. |

Key behaviors:

- The engine bootstraps by training on the simulator's own demand history on first contact with a run, then continues learning online (prequentially: forecasts are recorded before observations are learned). Artifacts persist under `INTELLIGENCE_HISTORY_DIR` (default `var/intelligence`, git-ignored).
- Simulator writes happen **only** via `POST /api/v1/intelligence/plans/{id}/execute` after an explicit operator approval, only when `INTELLIGENCE_EXECUTION_ENABLED=true` (the default), only after revalidation against a fresh snapshot, and always with a stable `idempotency_key`. Ambiguous outcomes are reconciled via `GET /v1/allocations`, never blind-retried.
- Degraded data → cached advisory results, explicit `DATA_STALE` findings, and a `degraded` engine status; planning failures produce an explicit NO_ACTION plan rather than an empty success.

Useful engine environment variables: `INTELLIGENCE_EXECUTION_ENABLED` (default true), `INTELLIGENCE_LOOP_SECONDS` (poll interval, default 5), `INTELLIGENCE_HISTORY_DIR`, `INTELLIGENCE_HORIZON_TICKS` (default 24), `INTELLIGENCE_DEPOT_RESERVE` (default 0.10), `INTELLIGENCE_PLAN_EXPIRY_TICKS` (default 2), `INTELLIGENCE_LOOP_ENABLED` (set false to disable the background loop).

## Fake simulator for local development

When the organizer's simulator image is not available, a deterministic test double is included:

```bash
uvicorn tools.fake_simulator:app --port 8000
```

It implements the documented public API plus `/admin/demo/shortage` and `/admin/demo/route_disruption` helpers for demos. It is a development tool, not the official simulator.

## Container deployment

From the repository root, `docker compose up -d --build backend` starts this API together with the simulator service it depends on. See [`../deploy/README.md`](../deploy/README.md) for local/full-stack and VPS deployment instructions. Do not publish the simulator/admin port publicly.
