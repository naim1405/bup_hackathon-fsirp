# Recommended artifacts for the team

The repository now includes the four requested knowledge artifacts plus an architecture overview and a demo/validation plan. The following additional artifacts would reduce handoff ambiguity and improve judging evidence. Prioritize artifacts that directly support implementation and repeatable testing; do not create documents for their own sake.

## Priority 0 — contracts and repeatability

| Artifact                                     | What it should contain                                                                                                                                                                                             | Why / suggested owner                                                                                                         | Status                                                                                                   |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Simulator API contract + data dictionary** | Exact field types, units (liters/ticks/ISO time), nullable fields, enum values, status transitions, freshness behavior, and small real payload examples. Mark documented, observed, and inferred facts separately. | Backend/integration owner. Critical because the supplied OpenAPI describes paths but leaves most GET response bodies as `{}`. | Partial context is in `recommendation-engine-design.md` and Pydantic models; no standalone contract yet. |
| **Deterministic scenario/replay manifest**   | For each case: image/version, seed/scenario, reset steps, pause/run state, event payloads and tick schedule, actions, number of steps, expected observations, baseline metrics.                                    | Engine + test owner. Makes results and comparisons reproducible across machines and agent sessions.                           | Demo plan contains a starter procedure; exact dry-run manifests remain to be recorded.                   |
| **Decision-policy configuration**            | Thresholds, safety-stock method, coverage horizon, forecast blending weights, severity mapping, tie-break/fairness rule, confidence rule, policy version.                                                          | Recommendation-engine owner. Prevents unexplained constants embedded throughout code.                                         | Not implemented.                                                                                         |
| **End-to-end architecture diagram**          | Service boundaries, internal/external endpoints, data and action flow, state ownership, port/env names, and failure boundaries.                                                                                    | Integration owner. Lets new teammates understand what to run and where to add work.                                           | Starter Mermaid diagrams are in `architecture-overview.md`; update as code evolves.                      |

## Priority 1 — engineering and operator handoff

| Artifact                                        | What it should contain                                                                                                                                                                            | Suggested owner            | Status                                                                                         |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------- |
| **ADR: recommendation policy choice**           | Why start with deterministic forecast + constrained heuristic/optimizer; alternatives considered (threshold, LP/ILP, ML/RL); evaluation evidence required before switching.                       | Engine owner.              | Recommended, not written separately.                                                           |
| **ADR: state freshness and SSE policy**         | Which REST resource is refreshed for each SSE event, reconnect/full-refresh behavior, duplicate event handling, UI coalescing, and stale-data action policy.                                      | Backend + frontend owners. | Current guide says REST truth/SSE hint; integration specifics still need implementation tests. |
| **Operator workflow / decision audit contract** | Recommendation lifecycle: generated → reviewed → approved/rejected/edited → submitted → pending/in-transit/arrived/failed/cancelled; actor, tick, reasons, snapshot version, request idempotency. | Product + backend owners.  | Not implemented; required before allocation actions.                                           |
| **Runbook**                                     | Install/start/stop all services, env variables, health checks, simulator reset, pause/step, inject/clear event/fault, common errors, recovery steps.                                              | DevOps owner.              | Per-service READMEs exist; combined Compose runbook remains.                                   |
| **Security / simulation guardrail checklist**   | Secret handling, simulated-only statement, no real infrastructure/actions, server-side proxy boundary, operator approval, safe behavior on stale data.                                            | Whole team / reviewer.     | Guardrails are summarized in problem analysis; operational checklist remains.                  |

## Priority 2 — judging and operational proof

| Artifact                            | What it should contain                                                                                                                                                                                                                             | Suggested owner    | Status                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | -------------------------------------------------------------------------- |
| **Observability/metrics catalog**   | Metric name, meaning, labels, source, owner, alert threshold, and whether it is a simulator metric or app metric. Include data age, simulator request latency/errors, SSE reconnects, engine latency/confidence/fallback, and allocation outcomes. | Reliability owner. | Not implemented.                                                           |
| **Load-test report**                | Endpoint, workload, concurrency, duration, p50/p95/p99, error rate, resource usage, limits, and follow-up actions.                                                                                                                                 | Reliability owner. | Required evidence; not yet run.                                            |
| **Demo script and evidence bundle** | Reset sequence, timing, operator narration, fallback/fault branch, screenshots/recording, metrics before/after, and known limitations.                                                                                                             | Demo owner.        | `demo-and-validation-plan.md` is the start; exact run evidence is pending. |
| **CI workflow**                     | Install, lint, format, typecheck, tests, and build for backend/frontend; dependency/cache strategy and failure policy.                                                                                                                             | DevOps owner.      | Not implemented.                                                           |

## Suggested directory once these are produced

```text
docs/
  README.md
  problem-analysis.md
  recommendation-engine-design.md
  architecture-overview.md
  work-plan-and-status.md
  demo-and-validation-plan.md
  recommended-artifacts.md
  simulator-contract.md             # next high-value addition
  decision-policy.md                # once thresholds are tuned
  adr/
    0001-start-with-explainable-policy.md
    0002-rest-is-authoritative.md
  runbook.md                         # once full Compose stack exists
  evidence/
    replay-baseline.json
    replay-policy.json
    load-test-summary.md
```

Keep generated test evidence compact and anonymized (there should be no real operational data). Store scenario definitions and policy configuration in version control; avoid storing credentials, `.env.local`, `.env`, or transient caches.
