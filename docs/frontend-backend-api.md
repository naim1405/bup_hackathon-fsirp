# Frontend ↔ backend API contract

The browser must call the Next.js same-origin proxy; it must never call the simulator. Next rewrites `/api/backend/*` to FastAPI `/api/*`, and FastAPI is the only component that calls the simulator.

```text
Browser → /api/backend/... → Next.js server rewrite → FastAPI → simulator
```

For example, browser `GET /api/backend/v1/dashboard/snapshot` becomes FastAPI `GET /api/v1/dashboard/snapshot`, which fans out to validated simulator `GET /v1/*` calls. This works with the existing local, Compose, and Vercel/VPS layouts.

## Endpoints

| FastAPI endpoint | Frontend path | Purpose |
| --- | --- | --- |
| `GET /api/v1/health` | `/api/backend/v1/health` | Backend liveness; does not contact the simulator. |
| `GET /api/v1/dashboard/snapshot` | `/api/backend/v1/dashboard/snapshot` | Best-effort aggregate of the current simulator state for initial render and refresh. |
| `GET /api/v1/allocations` | `/api/backend/v1/allocations` | Read allocation state from the simulator. |
| `POST /api/v1/allocations` | `/api/backend/v1/allocations` | Submit one explicit operator-approved allocation. Disabled by default. |
| `POST /api/v1/allocations/{allocation_id}/cancel` | same path under `/api/backend` | Request cancellation of an allocation. Disabled by default. |
| `GET /api/v1/simulator/{resource}` | same path under `/api/backend` | Granular validated read endpoints for health, instance, regions, depots, stations, routes, supply arrivals, events, allocations, demand history, and metrics. |
| `GET /api/v1/simulator/stream` | `/api/backend/v1/simulator/stream` | Validated simulator SSE proxy. |
| `WS /api/v1/ws` | Browser connects to the configured FastAPI WebSocket URL | Receives refresh notifications; it never calls the simulator. |

### Live refresh notifications

The browser opens a WebSocket to FastAPI at `/api/v1/ws`. FastAPI sends a small `connected` message on connect and an `update` message after the intelligence engine collects a fresh simulator tick. The frontend treats `update` only as a signal to refetch `/api/backend/v1/dashboard/snapshot`; REST remains the validated source of truth. Existing periodic and manual refreshes remain as a fallback when the socket is unavailable.

A `decision_required` message is handled as a user-facing toast and also invalidates the REST snapshot. To manually test that path in Swagger, keep an operator dashboard open with its WebSocket connected, then run `POST /api/v1/realtime/test-decision-notification` from FastAPI `/docs`. The response reports `connected_clients`; the open dashboard should show “Decision needed.” This sample endpoint does not create a plan or change simulator state. It only tests notification delivery; automatic decision-triggered notifications are not wired by this test route.

Next.js rewrites do not proxy WebSocket upgrades, so this socket uses `NEXT_PUBLIC_BACKEND_WS_URL` (for example, `ws://localhost:8001/api/v1/ws` locally or `wss://api.example.com/api/v1/ws` in production). Configure the backend's `CORS_ORIGINS` with the exact frontend origin. These messages contain no simulator state or IDs.

Dashboard demand history can be narrowed with `?history_limit=200&station_id=station-mirpur`; `history_limit` is constrained to 1–2000. Snapshot resources are fetched concurrently and are **not** a simulator transaction. `consistent` is true only when the simulator tick before and after the fetch matches.

## Snapshot response shape

`GET /api/v1/dashboard/snapshot` returns these top-level fields:

- `requested_at`, `as_of_tick`, `consistent`, `complete`, `stale`
- `simulator_health`, `instance`, `regions`, `depots`, `stations`, `routes`, `supply_arrivals`, `events`, `allocations`, `demand_history`, `metrics`
- `resource_status`: a map keyed by the resource names above (including `instance` and `simulator_health`). Each entry has `status` (`available`, `stale`, or `unavailable`), and may include `error_code`, `message`, and `upstream_status`.

A failed resource is `null`; other valid resources remain available. `complete` is false if any resource is unavailable. Stale resources remain populated and are marked in `resource_status`; if any resource is stale, the response also has `X-Simulator-Stale: true`. The frontend should show partial/stale state rather than treating it as a fully current snapshot. The backend does not cache or persist simulator-owned state.

## Allocation commands

The request body for `POST /api/v1/allocations` is validated and rejects unknown fields:

```json
{
  "idempotency_key": "stable-unique-key-for-this-operator-action",
  "source_depot_id": "depot-gazipur",
  "destination_station_id": "station-mirpur",
  "route_id": "route-gazipur-mirpur",
  "fuel_type": "DIESEL",
  "quantity": 500
}
```

`idempotency_key` is 1–150 characters. `source_depot_id`, `destination_station_id`, and `route_id` must identify a matching depot/station/route from current simulator state; select a route whose endpoints match the chosen depot and station. `quantity` must be positive and no greater than the route's `max_shipment`; `fuel_type` is `DIESEL`, `PETROL`, or `OCTANE`. The backend validates the command shape and forwards the command; the simulator remains authoritative for current feasibility (inventory, status, capacities, and conflicts). FastAPI validates the simulator's `Allocation` response and preserves its success status. A client retry after a timeout must reuse the **same idempotency key and same request body**; do not generate a new key for a retry. After success or cancellation, refetch the snapshot/allocation list to display simulator-owned state. These endpoints forward explicit commands only: there is no recommendation or automatic allocation logic in this API.

`SIMULATOR_WRITES_ENABLED` defaults to `false`. Set it to `true` only in a trusted operator environment. **There is no operator authentication/authorization in this milestone**; do not enable writes on a publicly reachable backend until access is protected (for example, by adding application auth or a private network/access gateway). The flag is a safety switch, not authentication.

## Errors and frontend behavior

- Simulator gateway failures use FastAPI HTTP errors with structured `detail.code` values such as `SIMULATOR_TIMEOUT`, `SIMULATOR_UNAVAILABLE`, `SIMULATOR_REQUEST_FAILED`, and `INVALID_SIMULATOR_RESPONSE`. For an upstream rejection, inspect `detail.upstream_code` (for example, `ROUTE_MISMATCH`, `INSUFFICIENT_INVENTORY`, or `CANNOT_CANCEL`) and `detail.upstream_detail`; the HTTP status from the simulator is preserved.
- The snapshot normally returns HTTP 200 with per-resource failure details so the UI can display partial state. Validate that each resource has a usable `resource_status` before rendering it as current.
- A `422` indicates invalid frontend query/body input; a `503` with `SIMULATOR_WRITES_DISABLED` means operator commands are not enabled.
- Do not submit commands from stale or incomplete state. Keep explicit operator confirmation in the UI; do not interpret simulator events or a recommendation as authorization.

## Current boundary / not included

The frontend fetches REST snapshot state on page load and uses WebSocket notifications to refresh when simulator ticks advance. SSE remains available for validated simulator events. Both are notification channels; refetch REST rather than treating a push event as full state. Recommendation UI, database persistence, and operator authentication are not part of this milestone.
