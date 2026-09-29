# Backend

FastAPI read-only integration with the BUP Fuel Supply Simulator. Simulator responses are validated before being returned to API clients. No simulator writes or decision logic are implemented yet.

Requirements: Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The simulator defaults to `http://localhost:8000`; configure `SIMULATOR_BASE_URL` if needed. The backend defaults to an 8-second upstream timeout, configurable with `SIMULATOR_TIMEOUT_SECONDS`.

- Swagger UI: `http://localhost:8001/docs`
- Backend liveness: `http://localhost:8001/api/v1/health`
- Simulator read API: `http://localhost:8001/api/v1/simulator`

Available read resources: health, instance, regions, depots (list/detail), stations (list/detail), routes, supply arrivals, events, allocations, demand history, and metrics. The SSE stream is available at `/api/v1/simulator/stream`; documented event payloads are validated before forwarding.

Run tests from this directory:

```bash
python -m pytest
```
