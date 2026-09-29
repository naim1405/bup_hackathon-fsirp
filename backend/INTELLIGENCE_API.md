# Intelligence Engine — API & Usage Guide

**Package:** `backend/app/intelligence/` (all intelligence code lives only here)
**Integration branch:** `integration/intelligence-engine` (based on latest `main`) · Backend suite: **95 tests passing**
**Base URL:** `http://localhost:8001/api/v1/intelligence` · Swagger UI: `http://localhost:8001/docs`

---

## 1. What it does

The engine turns the simulator's raw state into operator-ready decisions:

```
simulator ──► snapshot ──► TRAIN (bootstrap + online) ──► PREDICT ──► DETECT ──► PLAN ──► operator review ──► approve ──► execute ──► reconcile
```

| Capability | Where | Summary |
| --- | --- | --- |
| **Training** | `forecaster.py`, `training.py` | On first contact with a run it fetches each station's demand history from `/v1/demand-history` and batch-trains. Then it keeps learning **online every tick** in process memory (prequentially — forecasts are recorded *before* observations are learned). Model = seasonal tick-of-day profile + EWMA level + a pooled **online ridge regression per fuel type** (pure Python, zero new dependencies). Raw history is not copied to local persistent storage; after a backend restart the engine trains again from simulator-owned history. |
| **Prediction** | `projection.py` | Point forecast + empirical p10/p90 per station/fuel for the next 24 ticks, plus a deterministic inventory projection (receipt-before-use, outage-aware) and risk tiers (`critical/high/watch/normal/unknown`). |
| **Detection** | `detection.py` | Current stockouts, station outages, route blocks, depot constraints, demand spikes/drops (robust z-score), supply ETA slippage / shortfall / overdue, stale-data findings, and predictive shortage findings. Alerts have stable IDs, severity, evidence, and operator acknowledgement. |
| **Decision** | `allocator.py` | Constraint-aware greedy planner: depot stock net of pending commitments + hard reserve, per-depot dispatch headroom, route max-shipment, station tank headroom. Every plan is re-validated independently, and a baseline-vs-plan **impact** summary is computed under identical assumptions. |
| **Operator actions** | `service.py`, `routes.py` | Approve → execute workflow. Execution requires both write controls (each defaults to `false`), revalidates against a **fresh, consistent, non-stale** snapshot, validates the simulator's allocation response, and POSTs `/v1/allocations` with stable **idempotency keys**. Ambiguous or malformed outcomes are reconciled via `GET /v1/allocations` — never blindly retried. |
| **Loop & health** | `service.py` | A background loop computes once per new simulator tick and exposes engine/training health for the status panel. |

---

## 2. Running it

```bash
# Terminal 1 — simulator (organizer image), or the bundled fake for dev:
cd backend
uvicorn tools.fake_simulator:app --port 8000        # dev double; demos via /admin/demo/*

# Terminal 2 — backend with the engine loop enabled:
cd backend
SIMULATOR_BASE_URL=http://localhost:8000 \
INTELLIGENCE_LOOP_SECONDS=5 \
uvicorn app.main:app --port 8001
```

The engine starts with the app. Within seconds of boot it bootstraps training from the simulator's history and produces its first prediction/detection/plan. Nothing is submitted to the simulator until a human approves a plan.

### Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SIMULATOR_WRITES_ENABLED` | `false` | Existing backend-wide master switch for simulator writes. |
| `INTELLIGENCE_EXECUTION_ENABLED` | `false` | Intelligence-specific second gate. Both write switches must be `true`. |
| `INTELLIGENCE_LOOP_ENABLED` | `true` | Background per-tick advisory loop; does not execute plans. |
| `INTELLIGENCE_LOOP_SECONDS` | `5` | Poll interval (wall-clock). |
| `INTELLIGENCE_HORIZON_TICKS` | `24` | Planning/forecast horizon (ticks). |
| `INTELLIGENCE_IMMEDIATE_HORIZON_TICKS` | `6` | "Urgent" window for risk tiers and ranking. |
| `INTELLIGENCE_SEASON_TICKS` | `96` | Tick-of-day season length (auto-adapts to `tick_minutes`). |
| `INTELLIGENCE_TRAINED_WEIGHT` | `0.6` | Blend weight of the trained model at horizon 1. |
| `INTELLIGENCE_TRAINING_MIN_SAMPLES` | `200` | Samples before the trained model may be promoted. |
| `INTELLIGENCE_DESIRED_COVER_TICKS` | `6` | Demand cover targeted after a delivery. |
| `INTELLIGENCE_SAFETY_BUFFER` | `0.15` | Safety-buffer fraction of horizon demand. |
| `INTELLIGENCE_DEPOT_RESERVE` | `0.10` | Hard reserve fraction withheld from depot stock. |
| `INTELLIGENCE_PLAN_EXPIRY_TICKS` / `_SECONDS` | `2` / `120` | Plan expiry (first of tick-age or wall-age). |
| `INTELLIGENCE_REVALIDATE_MAX_AGE` | `20` seconds | Rejects a revalidation snapshot that is old, stale-marked, or inconsistent. |

---

## 3. Endpoints

All responses are JSON. Every artifact carries its `snapshot_id` and `as_of_tick` so the UI can show how fresh advice is. Frontend note: call these through the Next.js same-origin proxy, e.g. `GET /api/backend/v1/intelligence/recommendations`.

### 3.1 `GET /status` — engine & training health

```json
{
  "engine": "healthy",                  // healthy | degraded | disabled
  "last_run_tick": 214,
  "last_run_at_epoch": 1790658855.1,
  "last_error": null,
  "snapshot_age_seconds": 0.4,
  "run_count": 29,
  "total_runtime_ms": 812.6,
  "training": {
    "trained": true,
    "samples": 1532,
    "last_trained_tick": 154,
    "validation_mae_liters": 2.91,      // trained-model prequential MAE
    "baseline_mae_liters": 1.92,        // untrained ensemble MAE
    "improvement_vs_baseline": -0.52,
    "message": "Bootstrapped from 2216 historical rows (112 ms, 0 fetch errors)."
  },
  "execution_enabled": true,
  "fallback_active": false
}
```

Use this for the "Prediction Service / Decision Engine" rows of the system-status panel. `degraded` means stale data, a failed run, or fallback priors are in use — show it and require fresh data before approvals.

### 3.2 `POST /run` — trigger a run now

```json
// request (optional body)
{ "force": false }
```

`"force": true` recomputes even if this simulator tick was already processed (normal loop runs compute once per tick). Response:

```json
{ "snapshot_id": "1:baseline:1.0.0:42@214#29", "has_prediction": true, "has_detection": true, "has_plan": true, "plan_id": "plan-1-214-29" }
```

### 3.3 `GET /prediction` — forecast + projection + risk

Returns the latest `PredictionResult`:

```json
{
  "snapshot_id": "…@214#29",
  "as_of_tick": 214,
  "horizon_ticks": 24,
  "forecasts": [
    {
      "station_id": "station-mirpur",
      "fuel_type": "DIESEL",
      "method": "trained_ensemble",         // cold_start_prior | seasonal_naive_ewma | trained_ensemble
      "confidence": "high",                 // high | medium | low
      "point":  [1204.1, "… one value per future tick …"],
      "p10":    [ 980.0, "…"],
      "p90":    [1420.9, "…"],
      "history_count": 214,
      "ewma_level": 1.02,
      "trained_model_used": true,
      "trained_model_samples": 1532,
      "reasons": [
        { "code": "SEASONAL_LEVEL", "detail": "Seasonal tick-of-day profile scaled by the recent demand level (EWMA).", "values": { "observations": 214, "level_ratio": 1.02 } },
        { "code": "TRAINED_MODEL_ADJUSTMENT", "detail": "Trained per-fuel model adjusts the seasonal level; adjustment decays over the horizon.", "values": { "trained_next_tick_liters": 1211.4, "weight": 0.6 } }
      ]
    }
    // … 12 cells total (4 stations × 3 fuels)
  ],
  "projections": [
    {
      "station_id": "station-mirpur",
      "fuel_type": "DIESEL",
      "current_inventory_liters": 300.0,
      "capacity_liters": 15000.0,
      "projected_inventory": [180.2, 60.1, 0.0, "…"],
      "projected_demand":    [119.9, "…"],
      "projected_unmet":     [0.0, 0.0, 119.8, "…"],
      "expected_unmet_liters": 1976.4,
      "first_unmet_offset": 3,             // ticks until demand goes unserved
      "first_zero_offset": 3,              // ticks until the tank hits zero
      "burn_rate_liters_per_tick": 82.4
    }
  ],
  "risk_by_cell":     { "station-mirpur:DIESEL": "critical", "…": "…" },
  "risk_by_station":  { "station-mirpur": "critical", "…": "…" },
  "probability_status": "EMPIRICAL_UNCALIBRATED"
}
```

**UI hints:** render `point` with `p10..p90` as a band; show `first_unmet_offset` as "time to shortage"; treat `confidence: low` / `cold_start_prior` as "warming up".

### 3.4 `GET /detection` — latest findings

```json
{
  "snapshot_id": "…", "as_of_tick": 214,
  "findings": [
    {
      "finding_id": "CURRENT_STOCKOUT:station-mirpur:DIESEL",
      "type": "CURRENT_STOCKOUT",
      "category": "OBSERVED",                 // OBSERVED | PREDICTED | ENGINEERING
      "entity_ids": ["station-mirpur"],
      "fuel_type": "DIESEL",
      "severity": "critical",
      "confidence": "high",
      "title": "station-mirpur is stocked out of DIESEL",
      "detail": "Tank is empty while demand continues…",
      "evidence": [
        { "name": "inventory_liters", "value": 0.0, "unit": "L" },
        { "name": "expected_next_tick_demand_liters", "value": 118.7, "unit": "L" }
      ],
      "recommendation_hints": ["Immediate dispatch from any feasible depot/route."],
      "first_seen_tick": 212, "last_seen_tick": 214
    }
  ],
  "blocked_station_fuel": ["station-x:DIESEL"]   // cells the planner must not serve
}
```

Finding `type` values: `CURRENT_STOCKOUT`, `STATION_OUTAGE`, `ROUTE_BLOCKED`, `ROUTE_DELAY`, `DEPOT_CONSTRAINT`, `DEMAND_SPIKE`, `DEMAND_DROP`, `DEMAND_LEVEL_SHIFT`, `SUPPLY_ETA_SLIPPAGE`, `SUPPLY_OVERDUE`, `SUPPLY_SHORTFALL`, `DATA_STALE`, `DATA_INSUFFICIENT`, `PROJECTED_STOCKOUT`, `REPLENISHMENT_TOO_LATE`, `NO_TIMELY_REPLENISHMENT`.

### 3.5 `GET /alerts` and `POST /alerts/{finding_id}/acknowledge`

```bash
GET /api/v1/intelligence/alerts?state=active     # active | acknowledged | resolved | run_ended
POST /api/v1/intelligence/alerts/CURRENT_STOCKOUT%3Astation-mirpur%3ADIESEL/acknowledge
{ "operator": "mahfuz", "comment": "reviewed, dispatch approved" }
```

Alert records wrap findings with lifecycle state and the acknowledgement audit (`acknowledged_by`, `acknowledged_at_epoch`, `comment`). On a simulator reset, open alerts end as `run_ended` (not "resolved") so history stays honest.

### 3.6 `GET /recommendations` — the current proposed plan

The heart of the operator UI:

```json
{
  "plan_id": "plan-1-214-29",
  "run_id": "1:baseline:1.0.0:42",
  "snapshot_id": "…@214#29",
  "as_of_tick": 214,
  "status": "draft",                       // draft → approved → submitting → applied | partially_applied | rejected | expired | failed
  "method": "GREEDY_CONSTRAINED",          // or NO_ACTION
  "policy_version": "policy-v1",
  "requires_operator_approval": true,
  "recommendations": [
    {
      "severity": "high",
      "action": {
        "action_id": "act-02-station-mirpur-diesel",
        "source_depot_id": "depot-gazipur",
        "destination_station_id": "station-mirpur",
        "route_id": "route-gazipur-mirpur",
        "fuel_type": "DIESEL",
        "quantity_liters": 1890.0,
        "dispatch_tick": 214,
        "expected_arrival_tick": 216,
        "transit_ticks": 2,
        "idempotency_key": "1:baseline:1.0.0:42:plan-1-214-29:act-02-station-mirpur-diesel"
      },
      "reason_codes": ["PROJECTED_SHORTAGE", "ETA"],
      "reasons": [
        { "code": "PROJECTED_SHORTAGE", "detail": "This delivery covers the projected shortage window.",
          "values": { "expected_unmet_after_liters": 0.0, "first_unmet_offset": null } },
        { "code": "ETA", "detail": "Departs at tick 214 on route route-gazipur-mirpur (2 transit ticks), arriving tick 216.",
          "values": { "transit_ticks": 2, "expected_arrival_tick": 216 } }
      ],
      "serving_findings": ["PROJECTED_STOCKOUT:station-mirpur:DIESEL"],
      "constraints_checked": ["route_available", "route_direction", "route_max_shipment",
                              "depot_usable_stock", "depot_dispatch_headroom",
                              "station_capacity_headroom", "station_open", "fuel_identity"],
      "binding_constraint": null,
      "alternatives": [
        { "route_id": "route-patiya-mirpur", "source_depot_id": "depot-patiya",
          "transit_ticks": 4, "max_shipment_liters": 5000.0,
          "not_chosen_because": "later arrival or less remaining depot stock" }
      ]
    }
  ],
  "impact": {
    "expected_unmet_before_liters": 11390.0,
    "expected_unmet_after_liters": 523.7,
    "unmet_avoided_liters": 10866.3,
    "stockouts_before": 3,
    "stockouts_after": 0,
    "worst_service_ratio_before": 0.0,
    "worst_service_ratio_after": 0.96,
    "note": "Deterministic base-case projection; both scenarios share the same demand forecast, confirmed inbound, and capacity assumptions. Simulator outcomes may differ."
  },
  "depot_state_after": [
    { "depot_id": "depot-gazipur", "fuel_type": "DIESEL",
      "remaining_usable_liters": 49712.0, "dispatch_headroom_liters": 9856.0 }
  ],
  "no_action_reasons": [
    { "station_id": "station-x", "fuel_type": "OCTANE", "reason_code": "STATION_OUTAGE",
      "detail": "Station is in OUTAGE; ~640L of underlying demand cannot be served until it reopens…" }
  ],
  "uncovered_needs": [
    { "station_id": "station-y", "fuel_type": "DIESEL", "reason_code": "INSUFFICIENT_DEPOT_STOCK",
      "detail": "~2100L projected unmet demand; no depot has usable DIESEL stock beyond commitments and reserves." }
  ],
  "warnings": []
}
```

`reason_code` values for gaps: `STATION_OUTAGE`, `NO_AVAILABLE_ROUTE`, `INSUFFICIENT_DEPOT_STOCK`, `CONSTRAINT_LIMITED`. Show `uncovered_needs` prominently — "we cannot fix 2,100 L of the gap with current supply" is decision-critical information, not a failure.

### 3.7 `GET /plans/{plan_id}` — any recent plan (with outcomes)

Returns the same shape as `/recommendations` plus `approved_by`, `executed_at_epoch`, and per-action `outcomes`. The service keeps the last 20 plans.

### 3.8 `POST /plans/{plan_id}/approve` — operator approval

```json
{ "operator": "mahfuz", "comment": "approved for dispatch" }
```

- **200** → plan is `approved` and ready to execute.
- **409** → not approvable: expired (`status` becomes `expired`), no recommendations, or already applied. Recompute with `POST /run {"force": true}` and review the fresh plan.

### 3.9 `POST /plans/{plan_id}/execute` — submit to the simulator

```json
{ "operator": "mahfuz" }
```

What happens, in order:

1. Requires both `SIMULATOR_WRITES_ENABLED=true` and `INTELLIGENCE_EXECUTION_ENABLED=true`, an `approved` plan, and a non-expired plan. Both switches default to `false`; the API does not authenticate operators.
2. Fetches a **fresh, non-stale, consistent** simulator snapshot and re-validates the whole plan against it. If data is stale/inconsistent or the world changed (tank filled elsewhere, route disrupted, stock moved), the plan is rejected and nothing is submitted.
3. For each action, POSTs `/v1/allocations` with exactly the simulator's required fields and the stable `idempotency_key`. A successful response is schema- and request-matched before it is marked submitted; malformed responses are reconciled by that key. Duplicate clicks / retries reuse the same key.
4. A timeout or 5xx is **never** blindly retried: the engine reconciles via `GET /v1/allocations` by idempotency key and marks the action `submitted` (with the real allocation id) or `unknown_outcome` for manual reconciliation.

Response (success):

```json
{
  "status": "applied",                     // applied | partially_applied | rejected | failed
  "rejection_reason": "none",              // none | execution_disabled | plan_missing | plan_expired |
                                           // snapshot_stale | already_executed | rejected_by_simulator |
                                           // simulator_unavailable | ambiguous_outcome
  "outcomes": [
    { "action_id": "act-02-station-mirpur-diesel", "status": "submitted",
      "simulator_allocation_id": 1004, "http_status": 201, "detail": null }
  ]
}
```

Semantics worth honoring in the UI:

- `partially_applied` is a real, expected state (there is no batch endpoint). Show which rows landed.
- Re-executing an `applied` plan is a safe no-op returning `already_executed`.
- `unknown_outcome` rows must be surfaced prominently; the engine keeps the reservation until reconciled.

### 3.10 `POST /plans/{plan_id}/reject`

```json
{ "operator": "mahfuz" }
```

Marks the plan rejected (audit trail keeps the operator id).

---

## 4. Operator workflow (the demo script)

```bash
# 1. Watch the engine think
curl http://localhost:8001/api/v1/intelligence/status
curl http://localhost:8001/api/v1/intelligence/prediction | jq '.risk_by_station'

# 2. (Demo) inject a crisis on the fake simulator
curl -X POST http://localhost:8000/admin/demo/shortage \
  -H 'Content-Type: application/json' \
  -d '{"station_id":"station-mirpur","fuel_type":"DIESEL","level":300}'

# 3. Alerts + a new plan appear within ~2 ticks
curl "http://localhost:8001/api/v1/intelligence/alerts?state=active" | jq '.[].finding.title'
curl http://localhost:8001/api/v1/intelligence/recommendations | jq '.impact'

# 4. Review → approve → execute (fresh plan, within expiry!)
PLAN=$(curl -s -X POST http://localhost:8001/api/v1/intelligence/run \
        -H 'Content-Type: application/json' -d '{"force":true}' | jq -r .plan_id)
curl -X POST http://localhost:8001/api/v1/intelligence/plans/$PLAN/approve \
  -H 'Content-Type: application/json' -d '{"operator":"mahfuz"}'
curl -X POST http://localhost:8001/api/v1/intelligence/plans/$PLAN/execute \
  -H 'Content-Type: application/json' -d '{"operator":"mahfuz"}'

# 5. Confirm fuel is moving in the simulator
curl http://localhost:8001/api/v1/simulator/allocations | jq '.[0]'
```

Planned events (`demand_spike`, `route_disruption`, …) injected via the simulator's admin are picked up automatically: forecasts adapt (live demand multiplier + EWMA), disrupted routes drop out of the plan, alternatives appear with reasons.

---

## 5. Frontend integration notes

- Route everything through the existing same-origin rewrite: `/api/backend/v1/intelligence/…` (Next rewrites to FastAPI server-side). Never call `localhost` from the browser.
- Poll `/status` (or reuse the simulator SSE tick event) and refetch `/prediction` + `/detection` + `/recommendations` when `as_of_tick` changes — payloads are already deduplicated per tick.
- Types map 1:1 to the JSON above; the fields are stable camel-cased-URL but snake_case-body contracts produced by Pydantic models in `app/intelligence/models.py`.
- Color by `severity` (critical/high/medium/low/info) and `risk_by_station`; always render `confidence` and the `note` fields — the judges grade explainability.
- Operator-facing screens must suppress scenario/run IDs, seeds, raw tick counters, raw error codes, simulator payloads, and developer-only diagnostics. Translate healthy/degraded/disabled, stale, rejected, and unknown-outcome states into plain language; do not render raw backend details.

## 6. Guarantees & honest limits

- **No automatic writes.** GET endpoints and the background loop never mutate the simulator. Execution requires explicit approval and both write switches; both default to disabled. The flags are not a substitute for authentication.
- **Idempotent by key.** Same logical transfer ⇒ same `idempotency_key`, safe replay, conflict detection on body mismatch.
- **Fresh-state submission.** Plans expire (2 ticks / 120 s) and are re-validated against a fresh snapshot at execution time.
- **Fallbacks.** If training/bootstrap fails, the engine runs on documented priors with `fallback_active: true`; if planning fails, you get an explicit `NO_ACTION` plan, never an empty success; stale data produces `DATA_STALE` findings and a `degraded` status.
- **Uncertainty is labeled, not invented.** Bounds are empirical prequential quantiles; where data is thin the engine says `cold_start_prior`/`low` confidence instead of pretending precision.
- **Heuristic, not optimal.** The allocator is a deterministic greedy policy; it claims feasibility and explainability, never global optimality.
