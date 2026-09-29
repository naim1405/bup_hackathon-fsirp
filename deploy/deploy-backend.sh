#!/usr/bin/env bash
set -euo pipefail

release_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec 9>/opt/fsirp/deploy.lock
flock -w 600 9
cd "$release_dir"

test -f /opt/fsirp/.env
export SIMULATOR_BIND_ADDRESS=127.0.0.1
export BACKEND_BIND_ADDRESS=127.0.0.1
compose=(docker compose --project-name fsirp --env-file /opt/fsirp/.env -f "$release_dir/docker-compose.yml")

"${compose[@]}" config --quiet
"${compose[@]}" build backend
"${compose[@]}" up -d --no-recreate --wait --wait-timeout 180 simulator
"${compose[@]}" up -d --no-deps --wait --wait-timeout 120 backend

curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8001/api/v1/health
curl --fail --silent --show-error --max-time 15 http://127.0.0.1:8001/api/v1/simulator/instance
printf '\nBackend release verified: %s\n' "$release_dir"
