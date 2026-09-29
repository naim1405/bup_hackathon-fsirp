# Work plan and implementation status

**Purpose:** one concise source of truth for teammates and agents about what is in Git now, what is deliberately not done, and the next work to pick up.

## Current repository state

The `main` branch has these implementation milestones:

| Commit                                                    | Work delivered                                                                                                                                                                               |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `58ca98b` — Initialize FastAPI backend scaffold           | Base FastAPI app, root info, backend health endpoints, CORS defaults, requirements, run instructions, and starter tests.                                                                     |
| `3fc3df4` — Add validated read-only simulator integration | Async simulator HTTP client, Pydantic response models, public simulator REST read routes, SSE proxy/event validation, upstream error mapping, stale header forwarding, and mock-based tests. |
| `efe9cf1` — Configure Next.js frontend with shadcn UI     | Next.js App Router/TypeScript/Tailwind v4 scaffold, shadcn/ui Nova/Radix setup and components, providers, same-origin FastAPI rewrite, starter page, and frontend tooling.                   |
| `7af9252` — Dockerize frontend and backend services       | Multi-stage frontend/backend Dockerfiles, root Compose stack including the simulator, health checks, and guides for all-in-one or VPS + Vercel deployment.                                                                                                   |
| `feature/intelligence-engine` — Add intelligence engine   | Trained demand forecaster (seasonal + EWMA + pooled online ridge, bootstrap-trained on simulator history), shared inventory projector, detection findings/alerts, constraint-aware greedy planner with what-if impact, operator approval + idempotent simulator submission with reconciliation, `/api/v1/intelligence/*` API, background per-tick loop, JSON training persistence, fake simulator dev double, and 53 deterministic tests (validated live end-to-end: train → detect → plan → approve → execute → delivered). |

### Implemented today

#### Backend

- FastAPI runs on port **8001**; service liveness: `/api/v1/health`; interactive OpenAPI docs: `/docs`.
- Simulator adapter lives in `backend/app/simulator/`.
- Read endpoints are rooted at `/api/v1/simulator` and cover health, instance, regions, depots/list/detail, stations/list/detail, routes, supply arrivals, events, allocations, demand history, and metrics.
- `/api/v1/simulator/stream` proxies the simulator SSE stream and validates documented event payloads.
- Pydantic models validate timestamps, status/fuel enums, numeric bounds, required fuel levels, and response shapes. Demand-history parameters are validated (limit 1–2000, default 200).
- Upstream errors are translated to structured errors; stale data header is propagated.
- Backend tests: **10 pass** using a mocked simulator API.

#### Frontend

- Next.js 16 App Router, React 19, TypeScript, Tailwind CSS v4, React Compiler.
- shadcn/ui configured with the Nova preset, Radix primitives, CSS variables, theme support, Lucide, and common UI primitives.
- TanStack Query provider/devtools, React Hook Form, Zod, Recharts, date-fns, Sonner, ESLint, TypeScript, and Prettier/Tailwind sorting are set up.
- Same-origin rewrite: `/api/backend/*` → FastAPI `/api/*`; default target is server-only `http://127.0.0.1:8001`.
- Starter page accurately says live data is not connected yet. No inventory, recommendation, or operator-action UI has been implemented.
- Verified: `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build`; frontend and backend health proxy smoke tests return HTTP 200.

#### Containers / deployment

- `backend/Dockerfile`: Python 3.12 slim, non-root FastAPI image, liveness health check.
- `frontend/Dockerfile`: multi-stage Node 20 Alpine image with Next standalone output, non-root runtime, HTTP health check.
- Root `docker-compose.yml`: simulator, backend, and frontend with health-gated dependencies. Default bind addresses keep simulator/admin and backend ports on loopback.
- `deploy/README.md`: one-command full stack and split VPS backend + Vercel frontend instructions; `deploy/Caddyfile.example` and Compose env sample included.
- Verified: Compose YAML parses; Next standalone build and proxy smoke test succeeded; regular Vercel-mode `npm run build` succeeded.
- Not verified: actual Docker image/Compose build against a Docker daemon. Docker CLI/daemon was unavailable in the authoring environment; run the documented Docker-host verification before relying on it at judging.

#### Intelligence engine (feature/intelligence-engine)

- Everything intelligence-related lives in `backend/app/intelligence/` (config, priors, forecaster, projection, inbound, detection, allocator, training, service, routes); no other backend package contains decision logic.
- Training: bootstrap from `/v1/demand-history` (per station), online prequential updates per tick, periodic ridge re-solve; history + model persist as JSON under `INTELLIGENCE_HISTORY_DIR` keyed by run id; a simulator reset isolates the new run.
- Prediction: per station/fuel point forecast with empirical p10/p90, shared deterministic inventory projection (receipt-before-use, outage service failures kept separate from physical shortage), risk tiers per cell/station.
- Detection: observed stockouts, outages, route/depot states, demand spikes/drops (robust z), supply ETA slippage/shortfall/overdue, stale-data findings, plus predictive shortage findings with stable alert identities and operator acknowledgement.
- Decision: greedy constrained allocator over depot stock (net of commitments + reserve), per-depot dispatch headroom, route max-shipment, and station tank headroom; independent whole-plan validation; baseline-vs-plan impact summary; explicit uncovered-need reasons.
- Operator actions: plan approve/reject/execute endpoints; execution revalidates a fresh snapshot, submits with stable idempotency keys, reconciles ambiguous outcomes via `GET /v1/allocations`, and reports `PARTIALLY_APPLIED`/`APPLIED`/`REJECTED` honestly. `INTELLIGENCE_EXECUTION_ENABLED` gates all writes.
- Verified against a deterministic in-process fake simulator (11 E2E service tests + 4 HTTP route tests) and live: fake simulator + backend running together, shortage injected, plan generated, approved, submitted (11×201), and allocations ARRIVED at stations. Backend suite: **63 passed**.

### Not implemented yet

- Live run against the organizer's simulator image. Proxy and engine behavior is tested with a deterministic fake simulator; the real simulator image must be started locally at port 8000 for production state.
- A consistent dashboard/snapshot aggregation endpoint.
- Frontend REST/SSE data hooks, dashboard, alerts, and recommendation review UI.
- Recommendation persistence in an application database (plans/history currently live in memory plus JSON training artifacts) and policy versioning beyond `policy-v1`.
- Cancellation workflow for submitted allocations.
- Docker-host validation of the Dockerfiles/Compose stack, CI, metrics dashboards, load-test results, or final demo evidence.

## Recommended work order and ownership

Owners are roles; assign actual names in the team. Keep deployment/observability in the work from the start instead of leaving it as final-day work.

### P0 — Shared integration contract (backend/integration owner)

1. Start the organizer-published simulator image next to FastAPI and run smoke tests against actual responses.
2. Confirm every response model against the live OpenAPI/docs and integration guide. Resolve differences before generating frontend types.
3. Consider a backend snapshot endpoint that batches/caches the read resources with a single observed simulator tick, or document that the frontend requests each resource separately.
4. Add integration tests for simulator unavailable, invalid payload, stale header, reconnect and request timeout.

**Done when:** team can start the simulator + backend reproducibly, query every read endpoint, and see valid/stale/error behavior clearly.

### P1 — Recommendation engine (engine owner)

1. Implement the pure forecast/risk/decision module described in [Recommendation Engine Design](recommendation-engine-design.md).
2. Add cold-start profile priors, history-based demand estimate, ETA-aware projected stock, and explanation/confidence output.
3. Implement feasibility filters for route, depot inventory, dispatch headroom, station capacity, existing inbound allocations, outages, and stale state.
4. Build baseline-vs-policy deterministic replays and tune policy with service-level, unmet-demand, stockout, and failure measurements.

**Done when:** unit cases and repeatable simulator replays show feasible, explainable recommendations that outperform or usefully complement a stated baseline.

### P1 — Operator UI/data wiring (frontend owner)

1. Add typed client calls through `/api/backend/v1/simulator/*`; do not expose a browser `localhost` URL.
2. Add initial loading/error/stale states and render inventory, status, demand, supply/allocations, events, and metrics.
3. Consume SSE notifications, refetch affected REST state, refresh all after reconnect, and coalesce redundant rendering/recommendation work.
4. Add risk-ranked recommendations with reasons/ETA/confidence and an explicit review flow.

**Done when:** an operator can use the dashboard with live simulator data and distinguish healthy, stale, loading, and unavailable states.

### P1 — Safe operator actions (backend + frontend owners)

1. Add a backend endpoint for allocation submission only after a recommendation is approved.
2. Validate request structure and (when feasible) refresh constraints before posting to simulator.
3. Use a stable body `idempotency_key`, handle 404/409/503, show submitted and subsequent statuses, and make duplicate clicks/retries safe.
4. Optionally support cancel only for `PENDING` allocations; do not expose admin simulator controls as normal fuel actions.

**Done when:** an approved shipment is created once, shown with correct status, and all failure/conflict cases produce a useful operator message.

### P2 — Resilience, observability, and load test (DevOps/reliability owner)

1. Add bounded timeout/retry/backoff and degraded cached read behavior; never submit an action from stale state.
2. Instrument backend request count/latency/error, simulator reachability, stale-data detection, stream reconnects, recommendation latency/confidence, and allocation/fallback outcomes.
3. Expose component health and a simple metrics/log view. Add fault-injection runbook.
4. Load-test one meaningful application path and record workload, concurrency, p50/p95/p99 where available, error rate, and resource use.
5. Validate `docker compose up --build` on a Docker host, then add CI for backend tests, frontend checks, and container builds.

**Done when:** team can demonstrate a named failure, visible detection, safe fallback/degradation, recovery, and measured performance.

### P2 — Demo and judging evidence (demo owner, whole team)

Use the repeatable sequence in [Demo and Validation Plan](demo-and-validation-plan.md). Save screenshots/logs/metric readings and annotate baseline vs policy. Keep all claims clearly labeled as simulator results.

## Working agreement for coding agents

- Read `docs/README.md`, the specific design doc, and the local package instructions (`backend/README.md` or `frontend/README.md`) before editing.
- Do not add simulator writes, strategy, or fabricated data unless the task explicitly requests them.
- Keep domain recommendation logic isolated from HTTP/UI and add deterministic tests.
- Confirm no secrets/config credentials enter Git. Use environment configuration for endpoints.
- Update this status document when a milestone ships; distinguish mock tests from live-simulator validation.
