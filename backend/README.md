# Backend

Minimal FastAPI service foundation. Simulator integration and recommendation endpoints are intentionally not part of this initial scaffold.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `/docs` for Swagger UI and `/api/v1/health` for the health check. Run `python -m pytest` from this directory to execute the backend tests.
