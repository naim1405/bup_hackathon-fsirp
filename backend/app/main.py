"""FastAPI application entrypoint for the FSIRP backend."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.simulator.client import SimulatorClient
from app.simulator.config import SIMULATOR_BASE_URL, SIMULATOR_TIMEOUT_SECONDS
from app.simulator.routes import router as simulator_router
from app.intelligence.config import POLICY
from app.intelligence.routes import router as intelligence_router
from app.intelligence.service import IntelligenceEngine


def _cors_origins() -> list[str]:
    """Read allowed browser origins from a comma-separated environment variable."""
    configured = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create one reusable async HTTP client for the simulator connection."""
    async with httpx.AsyncClient(
        base_url=SIMULATOR_BASE_URL,
        timeout=httpx.Timeout(SIMULATOR_TIMEOUT_SECONDS, connect=3.0),
        follow_redirects=False,
    ) as simulator_http:
        application.state.simulator_client = SimulatorClient(simulator_http)
        intelligence = IntelligenceEngine(simulator_http, POLICY)
        application.state.intelligence = intelligence
        await intelligence.start_loop()
        try:
            yield
        finally:
            await intelligence.stop_loop()


app = FastAPI(
    title="Fuel Supply Intelligence & Resilience Platform API",
    description=(
        "Read-only backend integration for the BUP Fuel Supply Simulator. "
        "Simulator data is validated before it is returned to clients."
    ),
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(simulator_router)
app.include_router(intelligence_router)


@app.get("/", tags=["meta"], summary="API information")
def read_root() -> dict[str, str]:
    """Return basic service information and links to its API documentation."""
    return {
        "service": "fsirp-backend",
        "status": "ok",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/v1/health",
        "simulator_api": "/api/v1/simulator",
        "intelligence_api": "/api/v1/intelligence",
    }


@app.get("/api/v1/health", tags=["health"], summary="Backend health check")
@app.get("/health", tags=["health"], include_in_schema=False)
def read_health() -> dict[str, str]:
    """Lightweight backend liveness check; does not depend on the simulator."""
    return {"status": "ok", "service": "fsirp-backend"}
