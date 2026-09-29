# Deployment options

For monitoring and judging evidence, follow [Observability setup](observability.md).

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
- `SIMULATOR_WRITES_ENABLED` (default `false`; backend-wide write gate)
- `INTELLIGENCE_EXECUTION_ENABLED` (default `false`; second intelligence-only write gate)
- `BACKEND_API_URL` (frontend **build-time** HTTP rewrite target; local Compose default is `http://backend:8001`)
- `NEXT_PUBLIC_BACKEND_WS_URL` (frontend **build-time** direct WebSocket URL; use a public `ws://`/`wss://` FastAPI origin for browser clients)
- `CORS_ORIGINS` (comma-separated exact browser origins allowed to open the WebSocket; defaults to localhost development origins)

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
5. Verify `https://hackathon.bebsapati.com/api/v1/health`, `https://hackathon.bebsapati.com/api/v1/status`, `https://hackathon.bebsapati.com/api/v1/dashboard/snapshot`, and `https://hackathon.bebsapati.com/api/v1/simulator/instance` from outside the VPS. Backend liveness can be healthy even if the simulator is not; test simulator-backed routes separately.

### On Vercel

1. Import the same GitHub repository and set **Root Directory** to `frontend`.
2. Use `npm ci` for install and `npm run build` for build (Vercel's Next.js preset usually detects these automatically).
3. Set `BACKEND_API_URL` to `https://hackathon.bebsapati.com` for the server-side HTTP rewrite.
4. Set `NEXT_PUBLIC_BACKEND_WS_URL` to `wss://hackathon.bebsapati.com/api/v1/ws`. WebSocket upgrades are not handled by the Next.js HTTP rewrite, so the browser opens this socket directly to FastAPI. Set the VPS `CORS_ORIGINS` to the exact Vercel production origin (and any Preview origin you intend to allow).
5. Redeploy after changing either value; both are consumed at build time.
6. Keep REST browser requests on relative paths such as `/api/backend/v1/simulator/instance`; Vercel performs the HTTP rewrite to the VPS. Only the WebSocket URL is intentionally public in frontend configuration.

The backend exposes simulator reads, explicit allocation create/cancel routes, and intelligence plan execution. All simulator writes are disabled by default: direct allocation commands require `SIMULATOR_WRITES_ENABLED=true`, while intelligence execution also requires `INTELLIGENCE_EXECUTION_ENABLED=true` and explicit plan approval. There is no application authentication/authorization. Keep both flags false on any publicly reachable VPS until action routes are protected by authenticated/authorized operator access; a public Next.js rewrite or these feature flags alone are not authorization. Contracts are documented in [`../docs/frontend-backend-api.md`](../docs/frontend-backend-api.md) and [`../backend/INTELLIGENCE_API.md`](../backend/INTELLIGENCE_API.md). Apply suitable access controls and rate limits to the public API origin.

Vercel and other serverless gateways may impose connection-duration/idle limits on long-lived responses. Validate the SSE route through the actual Vercel deployment. If the provider closes or buffers the stream, use a streaming-capable route handler/runtime or host the frontend container beside FastAPI behind a reverse proxy (the Caddy example disables proxy buffering for streams). Keep REST refetch/reconnect behavior as the fallback because REST remains the source of truth.

### Automatic deployment from GitHub main

The repository includes `.github/workflows/backend-deploy.yml`. Pull requests run backend tests, Compose validation, shell syntax checks, and a backend image build. Pushes to `main` run the same checks, then upload that exact commit's source over verified SSH and deploy the backend. No GitHub repository credentials are needed on the VPS.

Vercel's native Git integration deploys the frontend independently on `main` pushes. It does **not** wait for this backend workflow. Keep frontend/backend changes backward-compatible; use branch protection to require passing pull-request checks before merging. No Vercel token or second frontend deployment workflow is needed.

#### 1. Prepare the VPS once

Target VPS: `167.99.226.149`. These commands assume an Ubuntu/Debian VPS with Docker Engine, Compose v2 supporting `--wait`, Bash, curl, and flock installed. Run them from an existing administrator SSH session; do not overwrite an existing SSH or reverse-proxy configuration.

```bash
sudo adduser --disabled-password --gecos '' deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy -m 750 /opt/fsirp /opt/fsirp/releases
sudo install -d -o deploy -g deploy -m 700 /home/deploy/.ssh
```

If the user already exists, skip `adduser`. Docker group membership effectively grants root access: use a dedicated deployment key and protect the GitHub production environment. New group membership requires a new login.

Generate a dedicated Ed25519 key on your trusted local machine with `ssh-keygen -t ed25519 -f ~/.ssh/fsirp_deploy`. For unattended CI, use no passphrase for this dedicated key. Append **only the public key** to `/home/deploy/.ssh/authorized_keys`, set ownership to `deploy:deploy` and permissions to `600`. Never commit either private keys or environment files.

Copy the contents of `deploy/compose.env.example` into `/opt/fsirp/.env` on the VPS. Keep simulator and backend bind addresses at `127.0.0.1`; keep the simulator paused initially. Make this file owned by `deploy` with mode `600`. `BACKEND_API_URL` in this file is unused when deploying only the backend; Vercel has its own value.

Allow your SSH access and public TCP ports 80/443 for the HTTPS proxy; do not expose ports 8000/8001. Before changing a firewall, preserve your existing SSH rule and inspect other hosted services.

#### 2. Configure GitHub secrets

Open this repository in GitHub: **Settings -> Environments -> New environment -> production**. Restrict deployment branches to `main`. Required reviewer approval is optional; enabling it makes deployments wait for approval rather than fully automatic.

Add these environment secrets:

- `VPS_HOST`: `167.99.226.149`
- `VPS_USER`: `deploy`
- `VPS_SSH_KEY`: complete contents of the dedicated private key, including BEGIN/END lines.
- `VPS_KNOWN_HOSTS`: verified SSH known-hosts entry for `167.99.226.149` (the workflow uses SSH port 22).

To verify the host key, run `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` in the provider's trusted VPS console. On your local machine, obtain the candidate entry with `ssh-keyscan -t ed25519 167.99.226.149`, save it to a temporary file, and compare its `ssh-keygen -lf` fingerprint with the console output. Only store the entry after they match. Do not blindly trust a scanned key or disable host-key checking.

#### 3. Set up HTTPS for the VPS API

The chosen split is **VPS API at `https://hackathon.bebsapati.com`**, with the frontend on its Vercel-assigned `vercel.app` domain.

- Set the DNS A record for `hackathon.bebsapati.com` to `167.99.226.149`; do not attach this hostname to Vercel.
- `deploy/Caddyfile.example` already uses this API hostname. Set Vercel's `BACKEND_API_URL` to `https://hackathon.bebsapati.com`.

Install Caddy using its official instructions, merge the example site block into the existing host Caddy configuration, validate it with `sudo caddy validate --config /etc/caddy/Caddyfile`, then reload with `sudo systemctl reload caddy`. Do not replace unrelated site blocks. Caddy must run on the host for the example's `127.0.0.1:8001` upstream to work. Remove conflicting AAAA records if this VPS is not serving the chosen hostname over IPv6.

#### 4. Connect Vercel once

In Vercel, **Add New -> Project -> Import Git Repository**, select `naim1405/bup_hackathon-fsirp`, and set:

- Framework: Next.js; Root Directory: `frontend`.
- Install command: `npm ci`; Build command: `npm run build`.
- Production branch: `main` (verify under project Git/environment settings).
- Environment variable: `BACKEND_API_URL` = `https://hackathon.bebsapati.com`, with no `/api` suffix. Set Production; optionally configure Preview to use an appropriate backend too.

Do not set `DOCKER_BUILD=1` on Vercel. Deploy/redeploy after configuring the variable because the rewrite target is built into the output. Browser code continues to use `/api/backend/...` unchanged.

#### 5. Activate and verify

Commit and push these files when ready. The first `main` push deploys the VPS backend after checks pass; alternatively run **Actions -> Backend CI and VPS deployment -> Run workflow**, selecting `main`, once the workflow is committed there.

- Confirm GitHub's deploy job passes both backend health and simulator-instance smoke checks.
- Check the same two routes through the public HTTPS backend origin; the SSH smoke test does not prove DNS/TLS works.
- Check `/api/backend/v1/simulator/instance` through the deployed Vercel frontend and exercise its SSE route separately.

Each backend release is stored under `/opt/fsirp/releases/`. The script serializes deployments, builds before replacing the backend, and starts the simulator with `--no-recreate`. Normal backend deployments must not reset simulator history. Simulator configuration/image changes require a separately planned restart; the script deliberately does not apply them to an existing simulator.

Backend replacement may briefly interrupt requests/SSE. A failed post-deployment health check fails the workflow but does not automatically roll back; inspect container logs and redeploy a known-good source commit via a reviewed revert on `main`. Release archives are retained for diagnosis; monitor disk usage and remove obsolete releases only deliberately. No `docker compose down`, volume deletion, or simulator reset is part of CI/CD.

## Option C — both services in containers on the VPS

If you do not want Vercel, run all Compose services on a single VPS and place a TLS reverse proxy in front of the frontend. Keep the backend and simulator bound to loopback/private networking. Use Vercel only if its deployment model suits the team's demo and backend reachability needs.

## Build/validation notes

- `backend/Dockerfile` uses Python 3.12 slim, installs runtime requirements, runs Uvicorn as a non-root user, and has a liveness check.
- `frontend/Dockerfile` uses a multi-stage Node 20 Alpine build and Next.js standalone output, runs as non-root, and has an HTTP health check.
- Standalone output is enabled for Docker builds only (`DOCKER_BUILD=1`); Vercel uses its native Next adapter.
- Local validation for Option B: `docker compose config --quiet`, deployment script shell syntax, and the backend Docker image build passed. The full Compose stack and remote GitHub/VPS/Vercel deployment still require end-to-end validation.
- The current backend test suite and frontend lint/typecheck/build do not replace a real end-to-end check against the published simulator image.
