# Work plan and implementation status

**Purpose:** one concise source of truth for teammates and agents about what is implemented, what is deliberately not done, and the next work to pick up.

## Current repository state

The following deployment/backend/frontend milestones are committed on `main`:

| Commit | Work delivered |
| --- | --- |
| `58ca98b` — Initialize FastAPI backend scaffold | Base FastAPI app, root info, backend health endpoints, CORS defaults, requirements, run instructions, and starter tests. |
| `3fc3df4` — Add validated read-only simulator integration | Async simulator HTTP client, Pydantic response models, simulator REST read routes, SSE proxy/event validation, upstream error mapping, stale header forwarding, and mock-based tests. |
| `efe9cf1` — Configure Next.js frontend with shadcn UI | Next.js App Router/TypeScript/Tailwind v4 scaffold, shadcn/ui Nova/Radix setup and components, providers, same-origin FastAPI rewrite, starter page, and frontend tooling. |
| `7af9252` — Dockerize frontend and backend services | Multi-stage frontend/backend Dockerfiles, root Compose stack including the simulator, health checks, and guides for all-in-one or VPS + Vercel deployment. |

The frontend-facing API is committed and pushed on `feature/frontend-backend-api` (`a528383`). The operator overview UI described below is in the current working tree and has not yet been committed.

### Implemented in the current working tree

#### Backend

- FastAPI runs on port **8001**; service liveness: `/api/v1/health`; interactive OpenAPI docs: `/docs`.
- Validated simulator read routes remain under `/api/v1/simulator`, including health, instance, regions, depots/list/detail, stations/list/detail, routes, supply arrivals, events, allocations, demand history, and metrics. `/api/v1/simulator/stream` proxies the validated SSE stream.
- `GET /api/v1/dashboard/snapshot` fetches dashboard resources through FastAPI, returns usable partial state with per-resource freshness/errors, and compares simulator ticks before/after collection. It is explicitly best-effort, not transactional or cached.
- `GET /api/v1/allocations`, `POST /api/v1/allocations`, and `POST /api/v1/allocations/{id}/cancel` provide frontend-facing allocation state and explicit simulator commands. Writes are disabled unless `SIMULATOR_WRITES_ENABLED=true`; no recommendation logic is involved.
- Allocation request bodies are validated; simulator responses are validated and successful upstream status codes are preserved. A retry must retain the same body `idempotency_key`.
- There is no operator authentication/authorization yet. Keep writes disabled on public deployments until access control is provided.
- Simulator-owned state/history is not copied into an application database.
- Backend tests: **14 pass** using a mocked simulator API. They cover partial snapshots, freshness, validation, disabled writes, create/cancel forwarding, and existing proxy/SSE behavior. This is mock-based; no live organizer simulator test has run.

#### Frontend

- Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v4, React Compiler.
- shadcn/ui configured with the Nova preset, Radix primitives, CSS variables, theme support, Lucide, and common UI primitives.
- TanStack Query provider/devtools, React Hook Form, Zod, Recharts, date-fns, Sonner, ESLint, TypeScript, and Prettier/Tailwind sorting are set up.
- Same-origin rewrite: `/api/backend/*` → FastAPI `/api/*`; default target is server-only `http://127.0.0.1:8001`.
- The operator overview now reads `/api/backend/v1/dashboard/snapshot` via TanStack Query and presents service level, unmet demand, station inventory cards, depot stock/routes, activity, arrivals, demand trends, and recent deliveries. Station cards open a detail sheet; stale/partial/unavailable data is described in operator-friendly language without exposing simulator IDs or raw error codes.
- The overview refreshes at a modest interval (15 seconds while running, 30 seconds otherwise) and can be manually refreshed. SSE notifications, multi-page network views, recommendations, and action controls remain future work.
- The API contract is documented in [frontend-backend-api.md](frontend-backend-api.md). Verified after UI changes: `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build`; the frontend proxy returned HTTP 200. The organizer simulator was not running for live-data validation.

#### Containers / deployment

- `backend/Dockerfile`: Python 3.12 slim, non-root FastAPI image, liveness health check.
- `frontend/Dockerfile`: multi-stage Node 20 Alpine image with Next standalone output, non-root runtime, HTTP health check.
- Root `docker-compose.yml`: simulator, backend, and frontend with health-gated dependencies. Default bind addresses keep simulator/admin and backend ports on loopback; `SIMULATOR_WRITES_ENABLED` defaults to false.
- `deploy/README.md`: one-command full stack and split VPS backend + Vercel frontend instructions; `deploy/Caddyfile.example` and Compose env sample included.
- Verified previously: Compose YAML parses; Next standalone build and proxy smoke test succeeded; regular Vercel-mode `npm run build` succeeded.
- Not verified: actual Docker image/Compose build against a Docker daemon. Docker CLI/daemon was unavailable in the authoring environment; run the documented Docker-host verification before relying on it at judging.

### Not implemented yet

- Frontend SSE notification handling, dedicated multi-page station/depot/delivery views, recommendation review, and explicit action confirmation UI.
- Live run against the organizer's simulator image. Current proxy/action behavior is tested with mocks; confirm request/response contracts against actual simulator OpenAPI/docs and the integration guide.
- Demand forecasting, shortage detection, recommendation policy, recommendation persistence, or policy versioning.
- Operator authentication/authorization; the write feature flag is not a security boundary.
- Application database, recommendation audit history, or decision-history retention policy.
- Docker-host validation, CI, metrics dashboards, load-test results, and final demo evidence.

## Recommended work order and ownership

Owners are roles; assign actual names in the team. Keep deployment/observability in the work from the start instead of leaving it as final-day work.

### P0 — Shared integration contract (backend/integration owner)

1. Start the organizer-published simulator image next to FastAPI and smoke-test snapshot, reads, allocation creation, and cancellation against actual responses.
2. Confirm every response/request model against live OpenAPI/docs and the integration guide. Resolve differences before generating frontend types.
3. Test tick changes during snapshot collection, stale headers, partial simulator failure, and API error mapping.
4. Add integration tests for simulator unavailable, request timeout, and stream reconnect behavior.

**Done when:** team can start simulator + backend reproducibly, query every read endpoint, and see valid/stale/error behavior clearly.

### P1 — Recommendation engine (engine owner)

1. Implement the pure forecast/risk/decision module described in [Recommendation Engine Design](recommendation-engine-design.md).
2. Add cold-start profile priors, history-based demand estimate, ETA-aware projected stock, and explanation/confidence output.
3. Implement feasibility filters for route, depot inventory, dispatch headroom, station capacity, existing inbound allocations, outages, and stale state.
4. Build baseline-vs-policy deterministic replays and tune policy with service-level, unmet-demand, stockout, and failure measurements.

**Done when:** unit cases and repeatable simulator replays show feasible, explainable recommendations that outperform or usefully complement a stated baseline.

### P1 — Operator UI/data wiring (frontend owner)

1. Extend the overview into dedicated station/depot/delivery pages as the operator workflows grow; keep all calls on same-origin `/api/backend/*`.
2. Consume SSE notifications, refetch affected REST state, refresh all after reconnect, and coalesce frequent tick events into bounded refreshes.
3. Add risk-ranked recommendations with reasons/ETA/confidence and an explicit review flow when the backend engine and response contract exist.
4. Add keyboard, screen-reader, and mobile usability checks for the operational workflows.

**Done when:** an operator can use the dashboard with live simulator data and distinguish healthy, stale, loading, and unavailable states.

### P1 — Safe operator actions (backend + frontend owners)

1. Add authentication/access control before enabling writes in any publicly reachable deployment.
2. Wire the frontend to `POST /api/backend/v1/allocations` only after explicit operator approval; validate/refresh feasibility before enabling the action.
3. Use a stable request `idempotency_key`, handle 404/409/503/504, show submitted and subsequent statuses, and make duplicate clicks/retries safe.
4. Keep cancellation explicit and respect simulator status/validation; do not expose admin simulator controls as normal fuel actions.

**Done when:** an approved shipment is created once, shown with correct status, and all failure/conflict cases produce a useful operator message.

### P2 — Resilience, observability, and load test (DevOps/reliability owner)

1. Add bounded timeout/retry/backoff and degraded cached read behavior where justified; never submit an action from stale state.
2. Instrument backend request count/latency/error, simulator reachability, stale-data detection, stream reconnects, recommendation latency/confidence, and allocation/fallback outcomes.
3. Expose component health and a simple metrics/log view. Add fault-injection runbook.
4. Load-test one meaningful application path and record workload, concurrency, p50/p95/p99 where available, error rate, and resource use.
5. Validate `docker compose up --build` on a Docker host, then add CI for backend tests, frontend checks, and container builds.

**Done when:** team can demonstrate a named failure, visible detection, safe fallback/degradation, recovery, and measured performance.

### P2 — Demo and judging evidence (demo owner, whole team)

Use the repeatable sequence in [Demo and Validation Plan](demo-and-validation-plan.md). Save screenshots/logs/metric readings and annotate baseline vs policy. Keep all claims clearly labeled as simulator results.

## Working agreement for coding agents

- Read `docs/README.md`, the specific design doc, and local package instructions (`backend/README.md` or `frontend/README.md`) before editing.
- Do not add simulator writes, strategy, or fabricated data unless the task explicitly requests them.
- Keep domain recommendation logic isolated from HTTP/UI and add deterministic tests.
- Confirm no secrets/config credentials enter Git. Use environment configuration for endpoints.
- Update this status document when a milestone ships; distinguish mock tests from live-simulator validation.
