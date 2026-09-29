# BUP Fuel Supply Intelligence & Resilience Platform

Monorepo for the BUP CSE Fest hackathon project. The backend is a FastAPI service; frontend and simulator integration will be added in later work.

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
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The server provides:

- API information: <http://localhost:8000/>
- Health check: <http://localhost:8000/api/v1/health>
- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

CORS defaults to `http://localhost:3000` and `http://localhost:5173`. Set `CORS_ORIGINS` to a comma-separated list to override these origins.

## Run backend tests

From the `backend` directory with the virtual environment activated:

```bash
python -m pytest
```
