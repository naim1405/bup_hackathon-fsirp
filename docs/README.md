# Project docs

These documents are the shared working context for teammates and coding agents. Read them in this order:

1. [Problem analysis](problem-analysis.md) — challenge, scope, constraints, evaluation, and the system we need to demonstrate.
2. [Recommendation engine design](recommendation-engine-design.md) — engine inputs, available data, forecasting, risk, allocation feasibility, outputs, and testing guidance.
3. [Architecture overview](architecture-overview.md) — current components and intended end-to-end data flow.
4. [Work plan and implementation status](work-plan-and-status.md) — what is already in the repository versus what remains.
5. [Demo and validation plan](demo-and-validation-plan.md) — reproducible scenarios, resilience checks, measurements, and demo outline.
6. [Recommended artifacts](recommended-artifacts.md) — additional contracts, ADRs, runbooks, and evidence worth creating.
7. [Deployment guide](../deploy/README.md) — full Compose stack and VPS-backend/Vercel-frontend options.

## Source of truth

- The official hackathon participant brief defines the challenge and judging.
- `BUP_Fuel_Supply_Simulator_Integration_Guide_Final.pdf` and the supplied `openapi.json` define simulator integration. The OpenAPI document currently leaves most GET response bodies untyped, so the companion guide’s examples are also important.
- The running implementation is in `backend/` and `frontend/`. Treat these docs as design context; update them when the implementation or organizer-provided contract changes.

## Current local ports

- Simulator: `http://localhost:8000` (when started from the organizer-provided image).
- FastAPI backend: `http://localhost:8001`.
- Next.js frontend: `http://localhost:3000`.

The frontend should call `/api/backend/...` on its own origin. Next.js rewrites that path to FastAPI server-side; browser code should not call `localhost` directly.
