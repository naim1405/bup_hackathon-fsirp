# BUP Fuel Supply Intelligence & Resilience Platform

Monorepo for the BUP CSE Fest hackathon project. The backend is a FastAPI service with validated, read-only integration endpoints for the fuel simulator. The frontend and decision engine will be added in later work.

## Backend quick start

Requirements: Python 3.11 or newer.

```bash
cd backend
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

The backend listens on port `8001` so the simulator can use its documented default port `8000`. Set `SIMULATOR_BASE_URL` if the simulator is exposed elsewhere (default: `http://localhost:8000`).

The server provides:

- API information: <http://localhost:8001/>
- Health check: <http://localhost:8001/api/v1/health>
- Swagger UI: <http://localhost:8001/docs>
- ReDoc: <http://localhost:8001/redoc>
- Simulator read endpoints: `/api/v1/simulator/*`

CORS defaults to `http://localhost:3000` and `http://localhost:5173`. Set `CORS_ORIGINS` to a comma-separated list to override these origins.

## Run backend tests

From the `backend` directory with the virtual environment activated:

```bash
python -m pytest
```
