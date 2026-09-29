from __future__ import annotations

import json
import logging
import math
import sys
import time
from collections import Counter, deque
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("fsirp.telemetry")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def event(name: str, **fields: object) -> None:
    logger.info(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(),
                            "event": name, "request_id": request_id.get(), **fields}))


class Telemetry:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.lock = Lock()
        self.counts: Counter[str] = Counter()
        self.durations: deque[float] = deque(maxlen=1000)
        self.routes: Counter[str] = Counter()
        self.health: str | None = None

    def health_transition(self, status: str) -> None:
        with self.lock:
            previous = self.health
            self.health = status
        if previous != status:
            event("health_transition", previous=previous, status=status)
            if previous == "degraded" and status == "healthy":
                self.increment("recoveries_total")

    def increment(self, name: str) -> None:
        with self.lock:
            self.counts[name] += 1

    def request(self, route: str, status: int, seconds: float, stream: bool) -> None:
        with self.lock:
            self.counts["requests_total"] += 1
            self.counts["server_errors_total"] += int(status >= 500)
            self.counts["client_errors_total"] += int(400 <= status < 500)
            self.routes[route] += 1
            if not stream:
                self.durations.append(seconds * 1000)

    def snapshot(self) -> dict:
        with self.lock:
            samples = sorted(self.durations)
            uptime = max(time.monotonic() - self.started, .001)
            def percentile(p: float) -> float:
                return round(samples[max(0, math.ceil(len(samples) * p) - 1)], 2) if samples else 0
            return {
                "uptime_seconds": round(uptime, 2),
                "requests_per_second_since_start": round(self.counts["requests_total"] / uptime, 3),
                "counters": dict(self.counts),
                "routes": dict(self.routes),
                "latency_window": "last 1000 completed non-stream requests in this process",
                "latency_samples": len(samples),
                "latency_avg_ms": round(sum(samples) / len(samples), 2) if samples else 0,
                "latency_p50_ms": percentile(.5),
                "latency_p95_ms": percentile(.95),
                "latency_p99_ms": percentile(.99),
            }


telemetry = Telemetry()


class ObservabilityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identifier = uuid4().hex
        token = request_id.set(identifier)
        started = time.monotonic()
        status = 500
        stream = False

        async def wrapped_send(message):
            nonlocal status, stream
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                stream = any(k.lower() == b"content-type" and b"text/event-stream" in v for k, v in headers)
                headers.append((b"x-request-id", identifier.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception:
            telemetry.increment("unhandled_errors_total")
            event("unhandled_error")
            raise
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            duration = time.monotonic() - started
            telemetry.request(route, status, duration, stream)
            event("http_request", route=route, status=status,
                  method=scope["method"] if scope["method"] in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER",
                  duration_ms=round(duration * 1000, 2), stream=stream)
            request_id.reset(token)
