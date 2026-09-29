# Frontend

Next.js App Router workspace for the FSIRP operator console. It is set up with TypeScript, Tailwind CSS v4, shadcn/ui (Radix primitives), React Compiler, TanStack Query, React Hook Form, Zod, Recharts, Lucide icons, and Prettier.

## Local development

Requirements: Node.js 20.9 or newer.

```bash
npm ci
cp .env.example .env.local
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Open <http://localhost:3000>. The frontend proxies same-origin requests from `/api/backend/*` to the FastAPI service. For example, `/api/backend/v1/simulator/instance` maps to the backend's `/api/v1/simulator/instance` endpoint. Configure the server-only `BACKEND_API_URL` in `.env.local` if FastAPI is not reachable at `http://127.0.0.1:8001`.

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
