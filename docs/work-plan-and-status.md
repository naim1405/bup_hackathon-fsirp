# Work plan and implementation status

**Purpose:** a shared source of truth for teammates and agents about what is implemented, what remains deliberately out of scope, and the next work to pick up.

## Current repository state

`main` contains the initial backend/frontend scaffolds, simulator read proxy, containerization, deployment automation, and the latest timestamp compatibility fixes. The `feature/frontend-backend-api` branch adds frontend API endpoints and the operator overview; PR #2 is open to merge those changes into `main`.

| Commit | Work delivered |
| --- | --- |
| `58ca98b` — Initialize FastAPI backend scaffold | FastAPI app, backend health, CORS, requirements, run instructions, starter tests. |
| `3fc3df4` — Add validated read-only simulator integration | Async HTTPX client, Pydantic simulator response models, REST reads, SSE proxy/event validation, upstream error handling, stale marker forwarding, and mock tests. |
| `efe9cf1` — Configure Next.js frontend with shadcn UI | Next.js/TypeScript/Tailwind foundation, shadcn/ui, providers, same-origin backend rewrite, and frontend tooling. |
| `7af9252` — Dockerize frontend and backend services | App Dockerfiles, root Compose stack with simulator, health checks, and deployment guides. |
| `aa60936` — Add automatic VPS backend deployment | Backend CI and SSH-based VPS deployment workflow; Vercel native Git integration remains the frontend deploy path. |
| `7cf5c3e`, `30aaa3d` | Backend timestamp compatibility, tests, and related repository/deployment documentation updates. |
| `a528383` — Add frontend-facing backend API endpoints | Best-effort dashboard snapshot, explicit allocation read/create/cancel APIs, write feature gate, request/response validation, and API contract docs. On the feature branch. |
| `d8c5849` — Build operator network overview dashboard | Responsive overview UI wired to the backend snapshot with inventory, depot, activity, arrivals, demand, and delivery views. On the feature branch. |

### Implemented on `feature/frontend-backend-api`

#### Backend

- FastAPI runs on port **8001**; liveness is `/api/v1/health`; interactive docs are `/docs`.
- Validated simulator reads remain under `/api/v1/simulator` for health, instance, regions, depots/list/detail, stations/list/detail, routes, supply arrivals, events, allocations, demand history, and metrics. `/api/v1/simulator/stream` proxies validated SSE events.
- Simulator timestamps accept timezone-less and timezone-aware values for instance, demand-history, and SSE tick-event data; absent timezone information is not silently replaced with one.
- `GET /api/v1/dashboard/snapshot` fetches resources through FastAPI, returns usable partial data with per-resource freshness/errors, and compares simulator ticks before/after collection. It is best-effort, not transactional or cached.
- `GET /api/v1/allocations`, `POST /api/v1/allocations`, and `POST /api/v1/allocations/{id}/cancel` provide allocation reads and explicit commands. Writes are disabled unless `SIMULATOR_WRITES_ENABLED=true`; there is no recommendation logic.
- Allocation bodies and simulator responses are validated; successful upstream statuses are preserved. Clients must reuse the same body `idempotency_key` for retries.
- There is no operator authentication/authorization. Keep writes disabled on public deployments until access control is provided.
- Simulator state/history is not copied into an application database.
- Backend tests: **23 pass** using the mocked simulator API, including partial snapshots, freshness, timestamp handling, validation, and gated action forwarding. Live simulator integration has not been verified from this environment.

#### Frontend

- Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v4, and React Compiler.
- shadcn/ui with Nova/Radix primitives, CSS-variable theming, Lucide icons, and common UI components; TanStack Query, Recharts, and other form/utility dependencies are configured.
- Same-origin rewrite: browser `/api/backend/*` → FastAPI `/api/*`; default server-only target is `http://127.0.0.1:8001`.
- Operator overview reads `/api/backend/v1/dashboard/snapshot` via TanStack Query. It presents service level, unmet demand, station inventory cards, depot stock/routes, activity, supply arrivals, demand trends, and recent deliveries. Selecting a station opens its details. Stale, partial, and unavailable data use operator-friendly language, without raw simulator IDs or error codes.
- Refreshes every 15 seconds while the simulator is running and every 30 seconds otherwise; also has a manual refresh control. Frontend SSE handling, dedicated multi-page network views, recommendations, and action controls remain future work.
- Verified: `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build`; frontend-to-backend proxy smoke test returned HTTP 200. The simulator was not running during the smoke test, so live-data rendering used its honest unavailable/partial states rather than sample values.

#### Containers / deployment

- Python 3.12 slim, non-root backend image; multi-stage Node 20 Alpine frontend image using Next standalone output.
- Root Compose runs simulator/backend/frontend with health-gated dependencies. Simulator/admin and backend host ports default to loopback. `SIMULATOR_WRITES_ENABLED` defaults to false.
- `deploy/README.md` documents all-in-one Compose, VPS + Vercel, and automatic VPS backend deployment; Caddy and Compose environment examples are included.
- Main-branch deployment automation validates Compose, shell syntax, backend tests, and backend image build, then deploys over verified SSH. Vercel native Git integration deploys the frontend independently.
- Docker Compose configuration, deployment-script shell syntax, and backend image build were validated in the separate automation workstream. Full Compose startup and remote VPS/Vercel end-to-end behavior still require validation.

### Not implemented yet

- Live run against the organizer simulator image. Confirm response/request contracts and smoke-test snapshot, read routes, allocation creation, and cancellation against the actual simulator.
- Frontend SSE notifications/reconnect handling and dedicated station/depot/delivery pages.
- Forecasting, shortage detection, recommendation policy/API/UI, recommendation persistence, or policy versioning.
- Operator authentication/authorization and a capability signal for action availability; the write feature flag is not a security boundary.
- Frontend allocation/cancellation controls and their explicit confirmation workflow.
- Application database, recommendation audit history, or decision-history retention policy.
- Docker-host end-to-end validation, remote deployment verification, load-test results, full observability evidence, and final demo artifacts.

## Recommended work order and ownership

Owners are roles; assign actual names in the team. Keep deployment/observability in the work from the start instead of leaving it as final-day work.

### P0 — Shared integration contract (backend/integration owner)

1. Start the organizer simulator next to FastAPI and smoke-test snapshot, reads, allocation creation, and cancellation against actual responses.
2. Confirm request/response models against live OpenAPI/docs and the integration guide.
3. Test tick changes during snapshot collection, stale headers, partial failure, timestamp variants, and upstream error mapping.
4. Test simulator unavailability, request timeouts, and stream reconnect behavior.

**Done when:** the team can start simulator + backend reproducibly, query every read endpoint, and see valid/stale/error behavior clearly.

### P1 — Recommendation engine (engine owner)

1. Implement the pure forecast/risk/decision module described in [Recommendation Engine Design](recommendation-engine-design.md).
2. Add cold-start profile priors, history-based demand estimates, ETA-aware projected stock, and explanation/confidence output.
3. Implement feasibility filters for routes, depot inventory, dispatch headroom, station capacity, inbound allocations, outages, and stale state.
4. Build deterministic baseline-vs-policy replays and evaluate service level, unmet demand, stockouts, and failures.

**Done when:** replay tests show feasible, explainable recommendations that outperform or usefully complement a stated baseline.

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

1. Add bounded timeout/retry/backoff and degraded behavior where justified; never act on stale state.
2. Instrument backend latency/errors, simulator reachability, stale detection, stream reconnects, recommendation latency, and action outcomes.
3. Add a fault-injection runbook and simple operational metrics/log view.
4. Load-test a meaningful application path and record workload, latency percentiles, errors, and resource use.
5. Validate the full Compose stack and remote deployment end to end.

**Done when:** the team can demonstrate a named failure, visible detection, safe degradation/recovery, and measured performance.

### P2 — Demo and judging evidence (demo owner, whole team)

Use [Demo and Validation Plan](demo-and-validation-plan.md). Save screenshots/logs/metric readings and compare baseline versus policy. Label simulated outcomes clearly.

## Working agreement for coding agents

- Read `docs/README.md`, the relevant design doc, and local package instructions (`backend/README.md` or `frontend/README.md`) before editing.
- Do not add simulator writes, strategy, or fabricated data unless the task explicitly requests them.
- Keep recommendation logic isolated from HTTP/UI and add deterministic tests.
- Keep secrets/config credentials out of Git; use environment configuration.
- Update this status document when milestones ship; distinguish mock tests from live-simulator validation.
