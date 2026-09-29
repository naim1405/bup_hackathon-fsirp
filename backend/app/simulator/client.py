"""HTTP client and error translation for the simulator read API."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import HTTPException, Response
from pydantic import TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


class SimulatorClient:
    """Small asynchronous HTTP client for the local simulator instance."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get_validated(
        self,
        path: str,
        adapter: TypeAdapter[Any],
        response: Response,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET a simulator resource and validate its JSON response."""
        try:
            upstream = await self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "SIMULATOR_TIMEOUT", "message": "The simulator request timed out."},
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "SIMULATOR_UNAVAILABLE", "message": "The simulator could not be reached."},
            ) from exc

        self._raise_for_upstream_error(upstream)
        self._copy_stale_header(upstream, response)

        try:
            payload = upstream.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "INVALID_SIMULATOR_RESPONSE", "message": "The simulator returned invalid JSON."},
            ) from exc

        try:
            return adapter.validate_python(payload)
        except ValidationError as exc:
            logger.warning("Simulator response failed validation for %s: %s", path, exc)
            errors = [
                {
                    "loc": list(error["loc"]),
                    "message": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors(include_input=False)
            ]
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "INVALID_SIMULATOR_RESPONSE",
                    "message": "The simulator response did not match the expected schema.",
                    "errors": errors,
                },
            ) from exc

    async def open_event_stream(self) -> httpx.Response:
        """Open the simulator SSE endpoint without buffering its events."""
        try:
            request = self._http.build_request(
                "GET", "/v1/stream", headers={"Accept": "text/event-stream"}
            )
            upstream = await self._http.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "SIMULATOR_TIMEOUT", "message": "The simulator stream timed out while connecting."},
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "SIMULATOR_UNAVAILABLE", "message": "The simulator stream could not be reached."},
            ) from exc

        if upstream.is_error:
            await self._raise_for_stream_error(upstream)

        content_type = upstream.headers.get("content-type", "")
        if "text/event-stream" not in content_type.lower():
            await upstream.aclose()
            raise HTTPException(
                status_code=502,
                detail={"code": "INVALID_SIMULATOR_RESPONSE", "message": "The simulator stream returned an unexpected content type."},
            )
        return upstream

    @staticmethod
    def _copy_stale_header(upstream: httpx.Response, downstream: Response) -> None:
        if upstream.headers.get("X-Simulator-Stale", "").lower() == "true":
            downstream.headers["X-Simulator-Stale"] = "true"

    @staticmethod
    def _raise_for_upstream_error(upstream: httpx.Response) -> None:
        if not upstream.is_error:
            return
        try:
            detail: Any = upstream.json()
        except ValueError:
            detail = upstream.text[:1000]
        raise HTTPException(
            status_code=upstream.status_code,
            detail={
                "code": "SIMULATOR_REQUEST_FAILED",
                "upstream_status": upstream.status_code,
                "upstream_detail": detail,
            },
        )

    @classmethod
    async def _raise_for_stream_error(cls, upstream: httpx.Response) -> None:
        try:
            body = await upstream.aread()
            try:
                detail: Any = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = body.decode("utf-8", errors="replace")[:1000]
        finally:
            await upstream.aclose()
        raise HTTPException(
            status_code=upstream.status_code,
            detail={
                "code": "SIMULATOR_REQUEST_FAILED",
                "upstream_status": upstream.status_code,
                "upstream_detail": detail,
            },
        )
