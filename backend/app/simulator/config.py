"""Simulator connection settings."""

from __future__ import annotations

import os


SIMULATOR_BASE_URL = os.getenv("SIMULATOR_BASE_URL", "http://localhost:8000").rstrip("/")
SIMULATOR_TIMEOUT_SECONDS = float(os.getenv("SIMULATOR_TIMEOUT_SECONDS", "8"))
SIMULATOR_WRITES_ENABLED = os.getenv("SIMULATOR_WRITES_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
