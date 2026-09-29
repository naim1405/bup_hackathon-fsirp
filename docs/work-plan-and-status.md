# Work plan and implementation status

**Purpose:** a shared source of truth for teammates and agents about what is implemented, what remains deliberately out of scope, and the next work to pick up.

## Current repository state

`main` is current at `a738ac8` and includes the frontend-facing backend API, operator overview, Site24x7 observability, deployment automation, and timestamp compatibility fixes. The intelligence engine from `feature/intelligence-engine` is being integrated and safety-reviewed on `integration/intelligence-engine`; do not merge it directly to `main` until review and CI are complete.

| Commit                                                    | Work delivered                                                                                                                                                                        |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `58ca98b` — Initialize FastAPI backend scaffold           | Base FastAPI app, root info, backend health endpoints, CORS defaults, requirements, run instructions, and starter tests.                                                              |
| `3fc3df4` — Add validated read-only simulator integration | Async simulator HTTP client, Pydantic response models, simulator REST read routes, SSE proxy/event validation, upstream error mapping, stale header forwarding, and mock-based tests. |
| `efe9cf1` — Configure Next.js frontend with shadcn UI     | Next.js App Router/TypeScript/Tailwind v4 scaffold, shadcn/ui Nova/Radix setup and components, providers, same-origin FastAPI rewrite, starter page, and frontend tooling.            |
| `7af9252` — Dockerize frontend and backend services       | Multi-stage frontend/backend Dockerfiles, root Compose stack including the simulator, health checks, and guides for all-in-one or VPS + Vercel deployment.                            |
| `integration/intelligence-engine` — safety review in progress | Integrated forecasting, detection, projection, and planning API; simulator writes remain gated by two default-off controls. Backend suite: 95 tests currently pass locally; see `backend/INTELLIGENCE_API.md`. |

The frontend-facing API and observability are already present on `main`; the current integration branch adds the intelligence package without replacing either.

### Implemented in the current working tree

#### Backend

- FastAPI runs on port **8001**; service liveness: `/api/v1/health`; interactive OpenAPI docs: `/docs`.
- Simulator adapter lives in `backend/app/simulator/`.
- Read endpoints are rooted at `/api/v1/simulator` and cover health, instance, regions, depots/list/detail, stations/list/detail, routes, supply arrivals, events, allocations, demand history, and metrics.
- `/api/v1/simulator/stream` proxies the simulator SSE stream and validates documented event payloads.
- Pydantic models validate timestamps, status/fuel enums, numeric bounds, required fuel levels, and response shapes. Demand-history parameters are validated (limit 1–2000, default 200).
- Upstream errors are translated to structured errors; stale data header is propagated.
- Simulator timestamps accept both timezone-less values observed on the VPS and timezone-aware values, without assigning a timezone when absent. This covers instance data, demand history, and SSE tick events; malformed timestamps remain rejected.
- Validated simulator read routes remain under `/api/v1/simulator`, including health, instance, regions, depots/list/detail, stations/list/detail, routes, supply arrivals, events, allocations, demand history, and metrics. `/api/v1/simulator/stream` proxies the validated SSE stream.
- `GET /api/v1/dashboard/snapshot` fetches dashboard resources through FastAPI, returns usable partial state with per-resource freshness/errors, and compares simulator ticks before/after collection. It is explicitly best-effort, not transactional or cached.
- `GET /api/v1/allocations`, `POST /api/v1/allocations`, and `POST /api/v1/allocations/{id}/cancel` provide frontend-facing allocation state and explicit simulator commands. Writes are disabled unless `SIMULATOR_WRITES_ENABLED=true`; no recommendation logic is involved.
- Allocation request bodies are validated; simulator responses are validated and successful upstream status codes are preserved. A retry must retain the same body `idempotency_key`.
- There is no operator authentication/authorization yet. Keep writes disabled on public deployments until access control is provided.
- Simulator-owned state/history is not copied into an application database or persistent backend history store. The intelligence engine bootstraps from simulator demand history and keeps in-memory model state only; restart triggers a fresh bootstrap.
- `/api/v1/intelligence/*` provides forecasts, projections, detections/alerts, constrained plans, and approve/reject/execute endpoints. It generates recommendations but never executes automatically. Execution requires both `SIMULATOR_WRITES_ENABLED=true` and `INTELLIGENCE_EXECUTION_ENABLED=true`; both default to false. Stale/inconsistent snapshots suppress recommendations and block writes. No operator authentication exists yet.
- Tests cover timestamp regressions, partial snapshots, freshness, validation, disabled writes, create/cancel forwarding, observability, and proxy/SSE behavior. Intelligence tests cover feasibility, stale-state suppression, dual write gating, response validation, and recovery. A local deterministic fake-simulator smoke passed for health, dashboard, intelligence run, default-off writes, and the explicitly enabled approve → execute path. Organizer-simulator and VPS verification remain pending.

#### Frontend

- Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v4, and React Compiler.
- shadcn/ui with Nova/Radix primitives, CSS-variable theming, Lucide icons, and common UI components; TanStack Query, Recharts, and other form/utility dependencies are configured.
- Same-origin rewrite: browser `/api/backend/*` → FastAPI `/api/*`; default server-only target is `http://127.0.0.1:8001`.
- Operator overview reads `/api/backend/v1/dashboard/snapshot` via TanStack Query. It presents service level, unmet demand, station inventory cards, depot stock/routes, activity, supply arrivals, demand trends, and recent deliveries. Selecting a station opens its details. Stale, partial, and unavailable data use operator-friendly language, without raw simulator IDs or error codes.
- Refreshes every 15 seconds while the simulator is running and every 30 seconds otherwise; also has a manual refresh control. Frontend SSE handling, dedicated multi-page network views, recommendations, and action controls remain future work.
- Verified: `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build`; frontend-to-backend proxy smoke test returned HTTP 200. The simulator was not running during the smoke test, so live-data rendering used its honest unavailable/partial states rather than sample values.

#### Containers / deployment

- Option B automation added locally: GitHub Actions tests/builds the backend and deploys exact source releases over verified SSH on `main`; Vercel native Git integration handles frontend pushes independently. See `deploy/README.md` for VPS provisioning, production secrets, domain selection, and activation. Remote deployment and end-to-end validation remain pending.

- `backend/Dockerfile`: Python 3.12 slim, non-root FastAPI image, liveness health check.
- `frontend/Dockerfile`: multi-stage Node 20 Alpine image with Next standalone output, non-root runtime, HTTP health check.
- Root `docker-compose.yml`: simulator, backend, and frontend with health-gated dependencies. Default bind addresses keep simulator/admin and backend ports on loopback; `SIMULATOR_WRITES_ENABLED` defaults to false.
- `deploy/README.md`: one-command full stack and split VPS backend + Vercel frontend instructions; `deploy/Caddyfile.example` and Compose env sample included.
- Verified: Compose YAML parses; Next standalone build and proxy smoke test succeeded; regular Vercel-mode `npm run build` succeeded.
- Option B validation: backend Docker image build, Compose configuration validation, and deployment shell syntax passed locally. Local backend/simulator Compose startup and fault/load tests also passed as recorded below. Remote VPS/Vercel verification remains pending.

### Not implemented yet

- Intelligence-driven recommendation/alert review and explicit action-confirmation UI; the existing overview remains simulator-state focused.
- Frontend SSE hooks and dedicated station/depot/delivery workflows.
- Operator authentication/authorization. Both simulator write flags default off but are not an access-control boundary.
- Persistent recommendation audit history or decision-history retention policy; current plans live in process memory.
- Live Site24x7 ingestion/alerts, VPS load/resource evidence, remote deployment verification, and final demo evidence.

## Recommended work order and ownership

Owners are roles; assign actual names in the team. Keep deployment/observability in the work from the start instead of leaving it as final-day work.

### P0 — Shared integration contract (backend/integration owner)

1. Start the organizer simulator next to FastAPI and smoke-test snapshot, reads, allocation creation, and cancellation against actual responses.
2. Confirm request/response models against live OpenAPI/docs and the integration guide.
3. Test tick changes during snapshot collection, stale headers, partial failure, timestamp variants, and upstream error mapping.
4. Test simulator unavailability, request timeouts, and stream reconnect behavior.

**Done when:** the team can start simulator + backend reproducibly, query every read endpoint, and see valid/stale/error behavior clearly.

### P1 — Recommendation engine (implemented on integration branch; validation ongoing)

The engine branch provides bootstrap/online forecasting, inventory projections, detections, constrained plans, approval workflow, idempotent execution, and deterministic unit/API tests. Integration review additionally defaults both write gates off, blocks stale/inconsistent snapshots, validates allocation responses, instruments simulator calls, and keeps demand history simulator-owned. The current backend suite passes locally; live organizer-simulator and VPS verification remain outstanding.

**Done when:** reviewers approve the integration diff, CI passes on the pushed integration branch, and live-simulator behavior is validated without enabling unauthenticated writes publicly.

### P1 — Operator UI/data wiring (frontend owner)

1. Extend the overview into focused station/depot/delivery views as workflows grow; keep calls on same-origin `/api/backend/*`.
2. Consume SSE notifications, refetch affected REST state, fully refresh after reconnect, and coalesce frequent tick events.
3. Add recommendation review only when the backend engine and response contract exist; do not implement recommendation decisions in the frontend.
4. Add keyboard, screen-reader, and mobile usability checks.

**Done when:** an operator can distinguish healthy, stale, loading, and unavailable data and navigate the core network workflows confidently.

### P1 — Safe operator actions (backend + frontend owners)

1. Add authentication/access control before enabling writes on a publicly reachable deployment.
2. Add a backend capability signal so the UI can accurately show whether actions are enabled.
3. Wire create/cancel actions only behind explicit operator review; refresh state after submission.
4. Use stable idempotency keys; handle 404/409/503/504 and make retries/duplicate clicks safe.

**Done when:** an approved shipment is created once, its status is visible, and failure/conflict cases produce clear operator guidance.

### P2 — Resilience, observability, and load test (DevOps/reliability owner)

Implemented on `feature/observability`: structured request/failure/recovery logs, bounded process-local metrics with token protection, validated dependency status, a polling frontend health panel, Site24x7 collection plugin, and k6 dashboard workload. See [setup and remaining acceptance gates](../deploy/observability.md). Existing partial-result degradation is instrumented; writes are not automatically retried. Simulator simulation timestamps accept naive and aware values without inventing a timezone. Live Site24x7 setup, VPS/Vercel validation and performance evidence remain pending. Intelligence simulator calls are instrumented in this integration branch and contribute to the same process-local counters.

Local verification (2026-09-29): backend/plugin tests passed; published simulator 1.0.0 returned healthy dependency status and a complete/fresh snapshot. Injected unavailable and stale-data faults each produced liveness 200, dependency 503, then healthy recovery. k6 local smoke: 2 users, 30 seconds, 54 complete/fresh responses, 0 HTTP failures, 1.78 requests/second, average 122.49 ms, p50 110.53 ms, p95 187.05 ms, p99 202.30 ms. Runner and services shared Docker Desktop: these are not VPS capacity results, and resource peaks were not captured. Frontend lint, generated-route typecheck, changed-file formatting and production build passed. Whole-tree formatting flags 27 untouched files. Browser visual verification and live provider setup remain pending.

1. Add bounded timeout/retry/backoff and degraded cached read behavior where justified; never submit an action from stale state.
2. Instrument backend request count/latency/error, simulator reachability, stale-data detection, stream reconnects, recommendation latency/confidence, and allocation/fallback outcomes.
3. Expose component health and a simple metrics/log view. Add fault-injection runbook.
4. Load-test one meaningful application path and record workload, concurrency, p50/p95/p99 where available, error rate, and resource use.
5. Validate `docker compose up --build` on a Docker host, then add CI for backend tests, frontend checks, and container builds.

**Done when:** the team can demonstrate a named failure, visible detection, safe degradation/recovery, and measured performance.

### P2 — Demo and judging evidence (demo owner, whole team)

Use [Demo and Validation Plan](demo-and-validation-plan.md). Save screenshots/logs/metric readings and compare baseline versus policy. Label simulated outcomes clearly.

## Working agreement for coding agents

- Read `docs/README.md`, the relevant design doc, and local package instructions (`backend/README.md` or `frontend/README.md`) before editing.
- Do not add simulator writes, strategy, or fabricated data unless the task explicitly requests them.
- Keep recommendation logic isolated from HTTP/UI and add deterministic tests.
- Keep secrets/config credentials out of Git; use environment configuration.
- Update this status document when milestones ship; distinguish mock tests from live-simulator validation.
