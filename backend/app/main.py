"""FastAPI application entrypoint for the FSIRP backend."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _cors_origins() -> list[str]:
    """Read allowed browser origins from a comma-separated environment variable."""
    configured = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


app = FastAPI(
    title="Fuel Supply Intelligence & Resilience Platform API",
    description=(
        "Backend foundation for the BUP Fuel Supply Intelligence & Resilience Platform. "
        "Simulator integration and decision-support endpoints will be added here."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["meta"], summary="API information")
def read_root() -> dict[str, str]:
    """Return basic service information and links to its API documentation."""
    return {
        "service": "fsirp-backend",
        "status": "ok",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/api/v1/health", tags=["health"], summary="Health check")
@app.get("/health", tags=["health"], include_in_schema=False)
def read_health() -> dict[str, str]:
    """Lightweight liveness check for local development and deployment probes."""
    return {"status": "ok", "service": "fsirp-backend"}
