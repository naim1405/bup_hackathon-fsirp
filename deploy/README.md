# Deployment options

The project now has **standalone Dockerfiles for both applications** and a root Compose file. Use the same container build for the hackathon's reproducible all-in-one launch or deploy the backend and frontend separately.

## Option A — one-command complete stack (hackathon/local)

From the repository root, with Docker Engine and the Compose plugin installed:

```bash
docker compose up --build -d
```

Compose pulls the organizer's published simulator image, builds the FastAPI and Next.js images, waits for health checks, and starts all three services. The simulator starts **paused** by default for reproducible testing; use the simulator's documented admin controls to run/step/inject test events.

Default local URLs:

- Frontend: <http://localhost:3000>
- FastAPI docs: <http://localhost:8001/docs>
- Backend health: <http://localhost:8001/api/v1/health>
- Simulator/admin console: <http://localhost:8000/admin>

The simulator and backend ports bind to host loopback by default. They remain reachable to sibling containers on the Compose network via `http://simulator:8000` and `http://backend:8001`. Frontend browser requests are same-origin; Next's server-side rewrite forwards `/api/backend/*` to FastAPI.

Useful operations:

```bash
docker compose ps
docker compose logs -f frontend backend simulator
docker compose restart backend
docker compose down
```

To reset simulated data, use the simulator's documented `POST /admin/reset`. `docker compose down -v` is not required by the current stack; no application database volume is configured.

### Compose environment overrides

Compose defaults are suitable for a local demo. Set shell variables or copy `deploy/compose.env.example` to an ignored root `.env` to change them:

- `SIMULATION_SPEED` (default 8 ticks/second while running)
- `TICK_MINUTES` (default 15)
- `SIMULATOR_START_MODE` (default `paused`)
- `SIMULATOR_BIND_ADDRESS`, `BACKEND_BIND_ADDRESS`, `FRONTEND_BIND_ADDRESS`
- `SIMULATOR_TIMEOUT_SECONDS`
- `SIMULATOR_WRITES_ENABLED` (default `false`; do not enable on a public backend without operator authentication/access control)
- `BACKEND_API_URL` (frontend **build-time** rewrite target; local Compose default is `http://backend:8001`)

Do not commit `.env` files. The example contains no secrets.

## Option B — backend + simulator on a VPS, frontend on Vercel

This is the recommended split deployment when you want Vercel hosting for the UI and a VPS for the backend. The VPS still runs the simulator beside the backend, because the participant simulator is a single-tenant local image—not a hosted central service.

### On the VPS

1. Install Docker Engine and the Compose plugin; clone this repo and check out the intended commit/tag.
2. Set `SIMULATOR_START_MODE=paused` (or omit it; paused is the default) and run only the backend service. Compose also starts its simulator dependency:

   ```bash
   docker compose up -d --build backend
   ```

3. The simulator is available to FastAPI on the private Compose network as `http://simulator:8000`. The default host port bindings are loopback only:
   - Simulator/admin: `127.0.0.1:8000` — keep private.
   - FastAPI: `127.0.0.1:8001` — put a TLS reverse proxy in front if it must be reachable from Vercel.
4. Configure a domain and HTTPS reverse proxy, such as Caddy. A minimal example is in [`Caddyfile.example`](Caddyfile.example). Set your firewall so only the proxy's public HTTPS port is exposed; do not expose port 8000 or the simulator `/admin` UI.
5. Verify `https://api.example.com/api/v1/health`, `https://api.example.com/api/v1/dashboard/snapshot`, and `https://api.example.com/api/v1/simulator/instance` from outside the VPS. Backend health can be healthy even if the simulator is not; test simulator-backed routes separately.

### On Vercel

1. Import the same GitHub repository and set **Root Directory** to `frontend`.
2. Use `npm ci` for install and `npm run build` for build (Vercel's Next.js preset usually detects these automatically).
3. Set the server-side environment variable `BACKEND_API_URL` to the public HTTPS API origin, e.g. `https://api.example.com`. Configure it for Production and Preview separately as appropriate.
4. Redeploy after changing this value. The Next.js rewrite destination is generated from `next.config.ts` at build time; changing only a runtime variable is not enough for an already-built deployment.
5. From the browser, keep calling relative paths such as `/api/backend/v1/simulator/instance`. Vercel's Next.js layer performs the server-to-server rewrite to the VPS API; do not put the VPS URL in a `NEXT_PUBLIC_*` variable or fetch it directly from browser code.

The backend exposes simulator reads and also has allocation create/cancel routes that are **disabled by default** (`SIMULATOR_WRITES_ENABLED=false`). It has no application authentication/authorization. Keep writes disabled on any publicly reachable VPS unless action routes are protected by authenticated/authorized operator access; a public Next.js rewrite or the feature flag alone is not authorization. The API contract is documented in [`../docs/frontend-backend-api.md`](../docs/frontend-backend-api.md). Apply suitable access controls and rate limits to the public API origin.

Vercel and other serverless gateways may impose connection-duration/idle limits on long-lived responses. Validate the SSE route through the actual Vercel deployment. If the provider closes or buffers the stream, use a streaming-capable route handler/runtime or host the frontend container beside FastAPI behind a reverse proxy (the Caddy example disables proxy buffering for streams). Keep REST refetch/reconnect behavior as the fallback because REST remains the source of truth.

## Option C — both services in containers on the VPS

If you do not want Vercel, run all Compose services on a single VPS and place a TLS reverse proxy in front of the frontend. Keep the backend and simulator bound to loopback/private networking. Use Vercel only if its deployment model suits the team's demo and backend reachability needs.

## Build/validation notes

- `backend/Dockerfile` uses Python 3.12 slim, installs runtime requirements, runs Uvicorn as a non-root user, and has a liveness check.
- `frontend/Dockerfile` uses a multi-stage Node 20 Alpine build and Next.js standalone output, runs as non-root, and has an HTTP health check.
- Standalone output is enabled for Docker builds only (`DOCKER_BUILD=1`); Vercel uses its native Next adapter.
- Docker was not available in the coding environment when these files were authored. Run `docker compose config` and `docker compose up --build` on a Docker host before relying on the images for judging.
- The current backend test suite and frontend lint/typecheck/build do not replace a real end-to-end check against the published simulator image.
