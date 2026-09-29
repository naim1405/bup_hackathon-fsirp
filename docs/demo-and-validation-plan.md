# Demo and validation plan

**Status:** planned validation procedure. Run it against the published simulator image before demo day; exact event timing and amounts should be dry-run and adjusted if the resulting state does not show the intended effect.

## Demo objective

Show the engineering loop, not just a slide or an isolated model:

> Normal state → changing demand or disruption → detection and forecast → explainable feasible recommendation → human approval → simulated allocation → measured impact → API/application fault → visible fallback and recovery.

All displayed quantities and metrics must be labeled as simulator data.

## Local test setup

Use the root Docker Compose stack as the reproducible default:

```bash
docker compose up --build -d
docker compose ps
```

This starts the organizer simulator image, FastAPI, and Next.js. The simulator defaults to paused. The exact images/Dockerfiles still need validation on a host with Docker installed. For a manual non-container run, use the per-service commands in the READMEs.

The services use these non-conflicting ports:

- Simulator: organizer image on port `8000`, paused for deterministic replay.
- FastAPI: port `8001`, `SIMULATOR_BASE_URL=http://localhost:8000`.
- Next.js: port `3000`, `BACKEND_API_URL=http://127.0.0.1:8001`.

The integration guide recommends a paused simulator plus `POST /admin/step` for reproducible tests. The published simulator container/image is authoritative; do not alter simulator source. Admin endpoints are self-test/demo controls only, not normal product actions.

Before the demo, verify:

- Simulator `GET /v1/health` and `/v1/instance` succeed.
- FastAPI `/api/v1/health` works even if the simulator is stopped; `/api/v1/simulator/instance` reflects the simulator or a useful unavailable error.
- Frontend `/api/backend/v1/health` reaches FastAPI through the same-origin rewrite.
- The UI indicates current tick/time, loading state, stale data, and errors without showing fabricated live data.

## Baseline replay

1. Use `POST /admin/reset`; ensure the instance is paused.
2. Fetch initial instance, stations, depots, routes, supply arrivals, allocations, metrics, and a limited demand-history window.
3. Run the no-action or threshold baseline for a fixed number of ticks using `POST /admin/step` once per tick.
4. Record tick/time, aggregate service level, unmet liters, allocation failures, and station/fuel demand-history outcomes.
5. Save the reset procedure, number of steps, observations, and event schedule.

Do not compare a policy run with different reset conditions, tick counts, or crisis schedule.

## Candidate crisis demonstration

A clear scenario can combine a Dhaka demand increase with a disrupted direct route to Mirpur. The exact start tick/duration should be chosen after a dry run.

Example event shapes from the guide (choose future ticks relative to the reset state):

```json
{
  "type": "demand_spike",
  "start_tick": 8,
  "duration_ticks": 12,
  "parameters": { "region_ids": ["region-dhaka"], "multiplier": 1.8 }
}
```

```json
{
  "type": "route_disruption",
  "start_tick": 8,
  "duration_ticks": 12,
  "parameters": { "route_ids": ["route-gazipur-mirpur"] }
}
```

Demo sequence:

1. Show normal state and identify the currently selected station/fuel signal.
2. Inject the event(s) through the simulator’s admin self-test controls; return to the operator UI.
3. Show the event and updated state from REST (SSE notification should trigger a REST refresh).
4. Show risk change and explanation. If the direct route is unavailable, exclude it and show a feasible alternate route/ETA or explain that no shipment can arrive in time.
5. Operator inspects and approves a proposal; the action layer (when implemented) submits a single idempotent simulator allocation.
6. Advance known ticks, track `PENDING` → `IN_TRANSIT` → arrival/failure, and compare resulting service/unmet-demand metrics.
7. Reset and replay under baseline/no action with the same event schedule for comparison.

Do not promise a particular stockout, delivery, or percentage improvement until the team has run the exact event and recorded actual simulator results. The simulator is deterministic for a fixed scenario/seed/events/actions, but actions change subsequent state.

## API fault demonstration

Domain crises test the decision policy. Inject a separate simulator API fault to test application resilience.

Example setup:

```json
{
  "type": "unavailable",
  "duration_seconds": 30,
  "parameters": {}
}
```

Use admin controls to activate the fault, then exercise an affected participant route such as `GET /v1/depots` via the app. Expected safe behavior:

- UI clearly marks simulator state as unavailable/degraded and timestamps cached state.
- Existing cached state may remain viewable, but is labeled stale/read-only.
- New recommendations are paused, marked provisional, or require explicit review; do not submit an allocation from stale inputs.
- User sees retry/recovery status; after fault clears/expires, the app refetches REST state and resumes.

Important test detail: `/admin/*` endpoints bypass fault injection, and `/v1/health` does too. To prove client behavior, call an affected `/v1/*` data endpoint. Other useful faults are latency, error rate, stale data, and stream disconnect. Do not treat 15 seconds of SSE silence as a failure; it is the documented keepalive interval.

## Automated validation matrix

| Test                           | Injection/setup                                       | Expected behavior                                                                     |
| ------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Cold start / no history        | Reset; query before enough observations exist         | Use documented prior, low confidence, no invented precision                           |
| Demand rises                   | `demand_spike` on target station/region               | Risk increases; reason identifies changed demand signal                               |
| Fast route blocked             | `route_disruption` on shortest route                  | Exclude route; compare valid alternate ETA or state no feasible option                |
| Station outage                 | `station_outage`                                      | No shipment to closed station; show outage and monitor recovery                       |
| Depot constraint               | `depot_constraint`                                    | Treat as caution; still respect actual API constraints; do not invent capacity number |
| Supply delayed/reduced         | `shipment_delay` / `supply_shortfall`                 | Revise depot supply forecast; do not count unarrived stock as current inventory       |
| Destination nearly full        | Construct station/candidate case                      | Limit shipment to current capacity headroom or return no feasible shipment            |
| Dispatch limit reached         | Existing pending/in-flight shipments consume headroom | Do not exceed dispatch capacity; propose wait/other depot where feasible              |
| Existing allocation covers gap | Pending/in-transit shipment exists                    | Avoid duplicate recommendation; show inbound allocation/ETA                           |
| Stale data                     | `stale_data` fault                                    | Propagate stale marker and make advice visibly provisional/read-only                  |
| Simulator unavailable          | `unavailable` or transient error                      | Timeout/error state, bounded retry/degraded display, no unsafe action                 |
| SSE disconnect/reconnect       | `stream_disconnect` fault                             | Reconnect with backoff, then full REST refresh (no event replay exists)               |
| Invalid payload                | Mock upstream malformed state                         | Backend validation error, not silently coerced into false state                       |

## Load-test evidence

Load-test at least one meaningful application path (eventually the recommendation-evaluation API or dashboard snapshot API). Use a stated workload and avoid flooding the single-tenant simulator unnecessarily.

Record:

- endpoint and test environment;
- request mix, duration, concurrency, and warm-up;
- success/error rate, average, p50, p95, p99 latency when available;
- CPU/memory and simulator request volume;
- observed bottleneck and chosen safe operating rate.

Do not report only a maximum throughput number without describing the workload.

## Evidence to capture

- A short live-demo checklist and exact reset/event/tick sequence.
- Screenshots or recording of risk explanation, operator approval, shipment status, and health/degraded state.
- Before/after metric snapshots and matching baseline run notes.
- Test output, load-test summary, architecture diagram, and known limitations.
