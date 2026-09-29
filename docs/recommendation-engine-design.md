# Recommendation engine: full design context

**Audience:** teammate(s) implementing forecasting and shipment recommendations, and coding agents working on that task.

**Status:** design specification for the next workstream. The current backend fetches and validates simulator data; it does **not** calculate recommendations, persist them, or submit allocations.

## 1. Mission and boundaries

The engine turns a current simulator snapshot plus recent observations into **explainable, feasible, time-aware fuel replenishment advice**.

It should answer:

1. Which open station/fuel combinations are likely to run short, and when?
2. Which currently feasible depot/route can help before the shortage?
3. How much should be sent without exceeding simulator constraints or overfilling the station?
4. What evidence supports the advice, what outcome is expected, and how reliable is the estimate?

### The engine is not

- The simulator itself: do not recreate its demand/state transition rules or modify its source.
- An autonomous dispatcher: generate a recommendation, show it to an operator, then let the operator approve. The eventual backend action layer can submit the approved allocation.
- A chatbot-only feature or an RL research experiment. A transparent policy/optimizer is a meaningful intelligence capability and is the recommended first implementation.
- A real-world fuel operations tool. All quantities and outcomes in this project are simulated.

Keep four concerns separate: **state acquisition/validation → analysis → recommendation presentation → operator approval/action**. This makes the engine testable as a pure function of a snapshot and history.

## 2. Data the engine can use

The current FastAPI read adapter is rooted at `/api/v1/simulator`. It proxies the simulator’s documented public `GET /v1/*` endpoints. The frontend can reach FastAPI through its same-origin `/api/backend/*` rewrite. Do not make browser code call `localhost` directly.

| Backend endpoint                        | Useful data                                                                          | Engine use / caveats                                                                                                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/health`                               | Simulator, database, and simulation health/tick                                      | A health check, not a business-state substitute. Backend liveness is separately `/api/v1/health`.                                                                          |
| `/instance`                             | `tick`, `sim_time`, `tick_minutes`, `status`, `seed`, scenario id/version            | Establishes the current simulated time and tick duration. Do not hard-code 15 minutes if `tick_minutes` says otherwise.                                                    |
| `/regions`                              | `id`, name, `demand_factor`                                                          | Demand context and a potential fairness/reporting grouping.                                                                                                                |
| `/depots` and `/depots/{entity_id}`     | Status, fuel inventory/capacity, `dispatch_capacity_per_tick`, region                | Current source stock and dispatch constraints. `CONSTRAINED` depots remain shippable in the simulator; the status is a constraint signal, not a numeric capacity override. |
| `/stations` and `/stations/{entity_id}` | Status, per-fuel inventory/capacity, region, `demand_profile`, `demand_multiplier`   | Main risk targets and receiving constraints. An `OUTAGE` station is not open for allocations.                                                                              |
| `/routes`                               | Source depot, destination station, `status`, `transit_ticks`, `max_shipment`         | Feasible paths and lead time. Only `AVAILABLE` routes can be used.                                                                                                         |
| `/supply-arrivals`                      | Depot, fuel, quantity, planned/actual tick, status                                   | Future replenishment **to depots**, not direct-to-station inbound. Do not add these quantities to station inventory.                                                       |
| `/allocations`                          | Existing source/destination/fuel/quantity, tick fields, route, status                | Avoid duplicate recommendations; estimate station-bound inbound and reserve depot capacity. Statuses: `PENDING`, `IN_TRANSIT`, `ARRIVED`, `FAILED`, `CANCELLED`.           |
| `/demand-history?station_id=&limit=`    | Per-station/per-fuel observations: tick/time, demand, served, unmet liters           | Forecasting and station-level impact analysis. `limit` defaults to 200 and is clamped by the simulator to 1–2000. The table grows without bound; always request a limit.   |
| `/metrics`                              | Aggregate served/unmet demand, service level, allocation liters, allocation failures | Network-level outcome tracking only. Metrics are not station/fuel-specific.                                                                                                |
| `/events`                               | Scheduled/active/resolved domain events and parameters                               | Event-aware forecasts/eligibility and human-readable explanations.                                                                                                         |
| `/stream`                               | SSE notifications for ticks, allocation status, inventory changes, and notices       | Trigger refresh/re-analysis. Event payloads are hints; re-GET affected REST state. Re-fetch the full snapshot after reconnect because the stream has no replay.            |

The current response models live in `backend/app/simulator/models.py`; proxy routes/client are under `backend/app/simulator/`. Most GET response schemas in the supplied OpenAPI file are empty, so the implementation uses field shapes from the simulator integration guide. If organizers publish a richer schema, reconcile it before changing assumptions.

### Data quality and timing requirements

- Mark the snapshot stale when a response includes `X-Simulator-Stale: true`. Do not present a stale-data recommendation as safe to auto-approve; identify it as degraded and require a fresh read/operator review.
- Keep all records associated with the instance `tick` and `sim_time`. Reject or quarantine impossible/malformed data; do not let a parsing error silently become zero inventory or zero demand.
- Sort history by tick/time in our code unless the official contract explicitly guarantees response ordering.
- The simulator clock may run quickly (default 8 ticks per wall-clock second while running). Refresh the affected REST resources after notifications, but coalesce expensive UI/forecast work so the engine does not repeatedly recompute identical snapshots.
- On SSE reconnect, re-fetch state before acting. Silence for 15 seconds is a normal keepalive interval, not proof the connection is dead.

## 3. Documented world prior (useful before history accumulates)

The default world has 2 regions, 2 depots, 4 stations, 6 routes, and three fuels: Diesel, Petrol, and Octane. The tick is 15 simulated minutes by default (96 ticks/day).

Stable IDs documented for the default world:

- Regions: `region-dhaka`, `region-chattogram`.
- Depots: `depot-gazipur`, `depot-patiya`.
- Stations: `station-mirpur`, `station-tongi`, `station-karnaphuli`, `station-coxsbazar`.

All IDs and status must still be read from the active simulator rather than treated as an immutable API contract.

### Region demand factors

| Region                                    | Factor |
| ----------------------------------------- | -----: |
| Dhaka Division (`region-dhaka`)           |   1.00 |
| Chattogram Division (`region-chattogram`) |   1.08 |

### Station demand profiles

Documented nominal liters per simulated day, in Diesel / Petrol / Octane order:

| Profile      | Diesel | Petrol | Octane | Noise scale |
| ------------ | -----: | -----: | -----: | ----------: |
| `urban_high` |  8,500 | 10,500 |  5,600 |        0.10 |
| `industrial` | 14,000 |  4,500 |  2,200 |        0.08 |
| `highway`    | 10,500 | 11,000 |  6,200 |        0.12 |
| `regional`   |  7,200 |  7,600 |  3,600 |        0.10 |

### Documented hour-of-day multipliers

| Profile      | Higher-demand window(s)           | Other hours        |
| ------------ | --------------------------------- | ------------------ |
| `industrial` | 06:00–17:59 → 1.55                | 18:00–05:59 → 0.45 |
| `highway`    | 06:00–09:59 or 16:00–19:59 → 1.35 | Otherwise → 0.75   |
| `urban_high` | 07:00–09:59 or 16:00–19:59 → 1.45 | Otherwise → 0.70   |
| `regional`   | 07:00–20:59 → 1.25                | 21:00–06:59 → 0.65 |

Use these as a **prior**, not as a claim that the engine knows the simulator's exact internal demand-generation formula. Start with profile/hour/region/station signals, compare against actual history, and calibrate. Avoid double-counting region or event multipliers if the observed `demand_liters` already reflects them.

### Routes and lead times

| Route                | Transit ticks | Max shipment (L) |
| -------------------- | ------------: | ---------------: |
| Gazipur → Mirpur     |             2 |            7,000 |
| Gazipur → Tongi      |             2 |            6,500 |
| Patiya → Karnaphuli  |             2 |            7,000 |
| Patiya → Coxsbazar   |             3 |            6,000 |
| Gazipur → Karnaphuli |             4 |            5,000 |
| Patiya → Mirpur      |             4 |            5,000 |

Always use live route state and the current `tick_minutes`; this table is documentation, not a substitute for fetching `/routes`.

### Initial capacity/inventory reference

Values are ordered Diesel / Petrol / Octane, in liters.

| Entity             | Dispatch capacity/tick |         Storage capacity |        Initial inventory |
| ------------------ | ---------------------: | -----------------------: | -----------------------: |
| Gazipur depot      |                 12,000 | 90,000 / 70,000 / 45,000 | 60,000 / 45,000 / 26,000 |
| Patiya depot       |                 11,000 | 85,000 / 65,000 / 40,000 | 55,000 / 42,000 / 24,000 |
| Mirpur station     |                      — |  15,000 / 14,000 / 9,000 |    9,000 / 9,000 / 5,000 |
| Tongi station      |                      — |   18,000 / 9,000 / 6,000 |   11,000 / 6,000 / 3,500 |
| Karnaphuli station |                      — |  14,000 / 15,000 / 9,000 |    8,500 / 9,500 / 5,200 |
| Coxsbazar station  |                      — |  12,000 / 12,000 / 7,000 |    7,500 / 7,500 / 4,200 |

Fetch live values; do not hard-code these as operational truth.

### Supply-arrival pattern in the documented scenarios

The guide describes 22 scheduled depot arrivals in all scenarios: 4 initial-burst arrivals around ticks 12–20 and 18 recurring resupply arrivals spaced 64 ticks apart (about 16 simulated hours at the default tick length). Recurring quantities are sized at roughly one day of regional demand. Shipment-delay and supply-shortfall events can change the schedule or amounts. Use the live `/supply-arrivals` response for decisions; use this pattern only as scenario context.

## 4. Events the engine must understand

Domain events affect the simulated world. The engine reads `/events`; event injection is an admin/test operation, not a normal recommendation action.

| Event              | Documented effect while active / once applied                           | Recommendation implication                                                                      |
| ------------------ | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `demand_spike`     | Multiplies affected station demand multipliers; reverses on resolution  | Increase near-term demand forecast; explain which region/stations and multiplier were observed. |
| `route_disruption` | Affected routes become `DISRUPTED`; return to `AVAILABLE` on resolution | Exclude disrupted routes; search alternate routes and compare ETA.                              |
| `station_outage`   | Affected stations become `OUTAGE`; served demand drops to zero          | Do not create an allocation for a closed station; report outage and monitor resolution.         |
| `depot_constraint` | Depot becomes `CONSTRAINED`; it is still shippable                      | Treat as a caution signal; do not invent an undocumented numeric capacity reduction.            |
| `shipment_delay`   | Future supply arrival tick is shifted; one-shot                         | Adjust depot supply expectations; do not count the delayed quantity before arrival.             |
| `supply_shortfall` | Future supply-arrival quantity is reduced; one-shot                     | Recalculate future depot stock and shortages.                                                   |

Do not confuse these with **API faults** (latency, unavailable, error rate, stale data, stream disconnect). Domain events test decision adaptation; API faults test application reliability.

## 5. Recommended analysis pipeline

### Step A — Build a consistent snapshot

Fetch or refresh instance, depot, station, route, supply-arrival, event, allocation, recent demand-history, and metric data. Associate every result with a tick/time. Do not mix data from clearly different ticks without marking the snapshot as inconsistent. Preserve stale/degraded metadata.

For historical data, request recent observations with a finite limit. A row represents a station/fuel/tick observation; the documented world creates 4 × 3 = 12 rows per tick. The full table is unbounded. Query with `station_id` where useful and filter/group by `fuel_type` locally.

### Step B — Forecast demand per station and fuel

Produce a short-horizon forecast for each open station/fuel combination. A practical staged approach:

1. **Cold start:** use the documented profile as a prior, scaled to the live tick length and adjusted using applicable region/station context. Mark confidence low until observations arrive.
2. **Warm start:** compute a robust recent mean or EWMA from `demand_liters`, and consider same-hour/daypart observations to capture the documented daily pattern.
3. **Blend:** combine the profile prior with observed demand. Increase the historical weight as clean observations accumulate; keep the exact weights configurable and validate them on deterministic replays.
4. **Event adjustment:** use active events and live `demand_multiplier`/status. Avoid applying the same multiplier twice if it is already visible in actual demand history.
5. **Uncertainty:** calculate a simple residual spread or empirical quantile. Return a point estimate plus an uncertainty range or confidence label; do not claim a calibrated stockout probability without testing it.

A simple initial formula can be:

`forecast_tick = blend(profile_prior_for_tick, recent_observed_demand)`

`forecast_cumulative(h) = sum(forecast_tick for the next h ticks)`

If history is sparse, stale, or unusually volatile, lower confidence and surface that uncertainty.

### Step C — Project inventory and identify risk

For station `s`, fuel `f`, and future tick offset `h`, estimate:

`projected_stock_without_new_action(s, f, h) = current_station_stock + confirmed_station_inbound_due_by_h - forecast_cumulative_demand(s, f, h)`

Use arrival ticks/status for inbound allocations where known. A `PENDING` allocation may not yet have departure/ETA fields; estimate conservatively from its route/current tick or label the ETA uncertain, and refresh after the next tick. Never count `FAILED` or `CANCELLED` allocations as inbound. Depot `supply-arrivals` are not station inbound.

Useful risk signals:

- Estimated stock-cover ticks/hours: the earliest horizon at which projected stock reaches zero or a safety threshold.
- Whether projected stock is below zero **before the earliest feasible replenishment ETA**.
- Expected unmet demand over a chosen planning horizon.
- Current unmet demand and service history from station-level `demand-history`.
- Event, route, outage, and data-freshness context.

A risk status can be `critical`, `high`, `watch`, or `normal`, but thresholds should be configurable and documented. Avoid pretending thresholds are inherent simulator facts.

### Step D — Generate and validate candidate shipments

For every at-risk open station/fuel pair, enumerate depots and routes that match the actual source/destination. Exclude options when:

- Station is not `OPEN`.
- Route is not `AVAILABLE` or does not connect the chosen depot/station.
- Depot has no current fuel stock for the chosen fuel.
- Estimated arrival is after the relevant shortage window (unless it still reduces later unmet demand).
- Existing shipments already cover the projected gap.

Validate proposed quantities against the simulator's real allocation rules:

- `quantity > 0` and `quantity <= route.max_shipment`.
- Current depot inventory for that fuel is sufficient.
- Pending/in-flight shipment quantities from the depot on the relevant tick plus this quantity do not exceed `dispatch_capacity_per_tick`.
- Current station inventory for the fuel plus this quantity does not exceed station capacity. The API checks this at allocation submission time; do not assume projected demand before arrival frees capacity for validation.
- Depot, station, and route identifiers exist and match.
- The station is open and route available at decision time.

An allocation may be accepted as `PENDING` before it departs; it is not instant delivery. Track it through `IN_TRANSIT`, `ARRIVED`, `FAILED`, or `CANCELLED`. Create actions only after operator approval and only through the future action endpoint layer (`POST /v1/allocations` via backend). This read-only integration currently does not submit anything.

### Step E — Size and rank recommendations

Define a configurable coverage horizon (for example, enough to cover forecast demand through the next review/replenishment interval) and a safety buffer. Do not hard-code a universal target until replay tests show it helps.

One sizing pattern:

`target_stock_at_arrival = forecast_demand_over_coverage_horizon + safety_buffer`

`needed_quantity = max(0, target_stock_at_arrival - projected_stock_without_new_action_at_arrival)`

`feasible_quantity = min(needed_quantity, route_limit, depot_available_stock, depot_dispatch_headroom, station_capacity_headroom)`

This is a recommendation ceiling, not an instruction to ship the maximum. Evaluate the expected service benefit of the amount and avoid sending fuel that is not needed.

For the first version, a deterministic greedy policy is likely sufficient for a world with 12 station/fuel cells and six routes:

1. Rank urgent shortages by expected unmet liters before feasible replenishment, then stockout timing.
2. For each priority, choose the available route/depot with the earliest helpful arrival and enough usable stock.
3. Allocate only the amount that improves projected service, bounded by all constraints.
4. Update remaining depot stock, per-tick dispatch headroom, and station capacity before considering the next candidate.
5. Add a modest fairness rule so one region does not receive all constrained supply while another has equally severe risk.

A small LP/ILP can be added later if it improves measured decisions. Reinforcement learning is optional; do not start there. No explicit route cost field is documented, so optimize for shortage avoided, ETA, feasibility, and service fairness—not invented monetary cost.

A useful decision objective is lexicographic:

1. Minimize weighted expected unmet demand (earlier stockouts carry higher urgency).
2. Reduce severe service gaps across station/region/fuel cells.
3. Prefer earlier feasible arrival and avoid over-replenishment.
4. Avoid allocations likely to fail the simulator's validation.

The official aggregate `service_level` is `served_demand_liters / (served_demand_liters + unmet_demand_liters)` (1.0 means no unmet demand) and can assess network-wide results. `allocation_liters` counts shipments currently `IN_TRANSIT` plus `ARRIVED`, not `PENDING`; `allocation_failures` counts `FAILED` allocations. Calculate station/fuel-level outcomes from demand history for more diagnostic comparisons.

## 6. Recommendation output contract

Keep the engine output separate from the simulator's allocation object. Suggested object shape:

```json
{
  "recommendation_id": "rec-<stable-id-for-snapshot-and-option>",
  "generated_at_tick": 18,
  "generated_at": "<simulation-time>",
  "kind": "replenishment",
  "severity": "high",
  "station_id": "station-mirpur",
  "fuel_type": "DIESEL",
  "risk": {
    "stock_cover_ticks": 3,
    "earliest_stockout_tick": 21,
    "expected_unmet_liters_without_action": 450.0,
    "confidence": "medium"
  },
  "action": {
    "source_depot_id": "depot-patiya",
    "route_id": "route-patiya-mirpur",
    "quantity_liters": 1500.0,
    "estimated_arrival_tick": 22
  },
  "expected_impact": {
    "unmet_liters_avoided_estimate": 350.0,
    "note": "Estimate from the current forecast; simulator outcome may differ."
  },
  "reasons": [
    "Recent diesel demand is elevated compared with the profile prior.",
    "The direct route is disrupted; this is the fastest available alternative.",
    "Quantity is below route, depot, dispatch, and station-capacity limits."
  ],
  "constraints_checked": [
    "route_available",
    "depot_stock",
    "dispatch_headroom",
    "station_capacity"
  ],
  "requires_operator_approval": true
}
```

The values are illustrative, not a scenario prediction. A recommendation can also be `monitor`, `no_action`, `alternate_route`, `wait_for_supply`, or `operator_review`. Return a reasoned no-action result when no shipment is needed; do not force an allocation for every update.

For stale data, an outage, or no feasible shipment, return a clear warning and alternatives/limitations instead of an invalid allocation. Put the snapshot tick and data-freshness status on every result so the UI can tell when advice has aged.

## 7. Engine API and implementation recommendation

Design the engine core as a pure function, for example:

```text
recommend(snapshot, demand_history, policy_config) -> list[Recommendation]
```

It should not make HTTP calls, mutate simulator state, or depend on browser/UI state. Put acquisition/retries in the simulator client and decision display/approval in the API/UI layers. This enables:

- Unit tests with constructed snapshots.
- Deterministic replay of simulator snapshots.
- Baseline-vs-policy comparisons.
- Independent load testing of the calculation endpoint.
- Explicit versioning of policy and generated decisions.

Possible eventual backend routes (design suggestions, not implemented):

- `GET /api/v1/recommendations` — latest stored/recomputed recommendations.
- `POST /api/v1/recommendations/evaluate` — evaluate a supplied/current snapshot without taking action.
- A separate approval/allocation endpoint later; never conflate “recommend” with “dispatch.”

For this small deterministic instance, calculate on a fresh snapshot and meaningful state change. If SSE emits at high tick rates, refresh the affected REST resource per event as required, but coalesce duplicate UI/engine work for the same tick/snapshot.

## 8. Baselines, testing, and metrics

Compare at least:

- No-action policy.
- Simple reorder threshold baseline.
- Proposed forecast + constrained-priority policy.

Use the same reset state, seed, event schedule, tick progression, and starting policy for fair replay. Log each recommendation, policy version, snapshot tick, operator choice, submitted allocation id (when actions exist), and outcome.

Assess:

- Aggregate service level and unmet demand from `/metrics`.
- Station/fuel unmet liters, stockout timing, and served demand from `/demand-history`.
- Allocation failures (including route disruption at departure).
- Number of feasible recommendations and infeasible/duplicate proposals.
- Forecast error by horizon and confidence bucket.
- Recommendation latency and data age.

Recommended unit cases: cold start; station with sufficient inbound; route disruption with alternate route; no alternate route; demand spike; station outage; depot constraint; supply delay/shortfall; capacity-limited depot; dispatch headroom exhausted; station capacity nearly full; failed/cancelled allocation; stale/invalid upstream data; sparse history; high uncertainty. Add deterministic integration replays with the official simulator before tuning thresholds.

## 9. Important simulator rules to preserve

- Same scenario/seed/actions/events produce reproducible state. The active scenario is baked into the published image and cannot be switched at runtime.
- Baseline has no preloaded events. Use admin event/fault controls only for test/demo setup, not as domain writes from the normal operator workflow.
- `REST` is authoritative. SSE is advisory; re-GET after events and do a complete refresh after reconnect.
- `/admin/*` bypasses API fault injection. `/v1/health` does too. Use affected `/v1/*` calls to demonstrate API fault handling.
- Creating allocations uses a body `idempotency_key` (not an HTTP header). Same key/same body is safely replayed; same key/different body returns a conflict. Cancellation only works for `PENDING` allocations and does not free the key.
- Simulator actions and results remain simulated; preserve operator review.
