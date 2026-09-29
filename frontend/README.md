# Frontend

Next.js App Router workspace for the FSIRP operator console. It is set up with TypeScript, Tailwind CSS v4, shadcn/ui (Radix primitives), React Compiler, TanStack Query, React Hook Form, Zod, Recharts, Lucide icons, and Prettier.

## Local development

Requirements: Node.js 20.9 or newer.

```bash
npm ci
cp .env.example .env.local
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Open <http://localhost:3000> for the operator network overview. It reads the best-effort dashboard snapshot through `/api/backend/v1/dashboard/snapshot` and never calls the simulator directly. Same-origin `/api/backend/*` requests are rewritten server-side to FastAPI `/api/*`. Configure the server-only `BACKEND_API_URL` in `.env.local` if FastAPI is not reachable at `http://127.0.0.1:8001`.

## Available commands

```bash
npm run lint
npm run typecheck
npm run format:check
npm run build
```

## Deployment

- Docker image: the repo-root Compose stack builds the production standalone image with `BACKEND_API_URL=http://backend:8001` for its private service network.
- Vercel: set the project root directory to `frontend` and configure `BACKEND_API_URL` to the public HTTPS FastAPI origin at build time. Rebuild after changing it. See [`../deploy/README.md`](../deploy/README.md) for split deployment notes and the SSE caveat.

## UI components

`components.json` configures the Nova shadcn/ui preset with Radix primitives, Lucide icons, CSS-variable theming, and the Tailwind v4 stylesheet. Add components with `npx shadcn@latest add <component>`.

## Operator pages and intelligence

The shared operations layout owns one WebSocket connection and network snapshot query.
Routes: `/` (summary/trends), `/depots` (stock/routes/inbound supply), `/stations`
(stock cards/detail drawer), `/activity` (events), `/deliveries` (shipment ledger),
and `/intelligence` (forecasts, alerts, plan review and execution outcomes).
Existing same-origin backend rewrites and `NEXT_PUBLIC_BACKEND_WS_URL` remain unchanged.
Intelligence queries refresh on WebSocket updates/decision notifications and poll every
15 seconds. Errors retain historical results with a visible warning.

Operator ID is required for audited decisions; it is not authentication. Approval and
execution are separate confirmed actions. Execute is disabled unless the backend reports
execution enabled. This frontend does not change backend write switches. Reviewed plan IDs
stay pinned so new background recommendations cannot silently replace an operator's plan.

Validation: `npx next typegen && npm run typecheck && npm run lint && npm run build`.
Browser smoke test (mock API responses, no live simulator writes): install Playwright with
`npm install --no-save --package-lock=false playwright`, then
`npx playwright install --with-deps chromium`. Start a production build with `npm start`
and run `node tests/operator-smoke.mjs`. Covers all routes, prediction display,
operator identity, confirmations, execution gating, outcomes, alerts and mobile station details.
