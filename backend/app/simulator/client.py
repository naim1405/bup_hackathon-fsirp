"""HTTP client and error translation for the simulator API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from fastapi import HTTPException, Response
from pydantic import TypeAdapter, ValidationError
from app.telemetry import event, telemetry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidatedSimulatorResult:
    data: Any
    stale: bool
    status_code: int


class SimulatorClient:
    """Small asynchronous HTTP client for the local simulator instance."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def get_validated_result(
        self,
        path: str,
        adapter: TypeAdapter[Any],
        *,
        params: dict[str, Any] | None = None,
    ) -> ValidatedSimulatorResult:
        """GET a resource and return validated data plus freshness metadata."""
        return await self._request_validated("GET", path, adapter, params=params)

    async def get_validated(
        self,
        path: str,
        adapter: TypeAdapter[Any],
        response: Response,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """GET, validate, and return JSON while forwarding the stale marker."""
        result = await self.get_validated_result(path, adapter, params=params)
        self._copy_stale_marker(result, response)
        return result.data

    async def post_validated(
        self,
        path: str,
        json_body: dict[str, Any] | None,
        adapter: TypeAdapter[Any],
        response: Response,
    ) -> Any:
        """POST a command, preserve the simulator status, and validate its result."""
        result = await self._request_validated("POST", path, adapter, json_body=json_body)
        response.status_code = result.status_code
        self._copy_stale_marker(result, response)
        return result.data

    async def _request_validated(
        self,
        method: Literal["GET", "POST"],
        path: str,
        adapter: TypeAdapter[Any],
        **kwargs: Any,
    ) -> ValidatedSimulatorResult:
        telemetry.increment("simulator_requests_total")
        try:
            result = await self._request_once(method, path, adapter, **kwargs)
        except HTTPException as exc:
            code = exc.detail.get("code", "SIMULATOR_REQUEST_FAILED")
            telemetry.increment("simulator_errors_total")
            if code == "INVALID_SIMULATOR_RESPONSE":
                telemetry.increment("simulator_invalid_total")
            if code == "SIMULATOR_TIMEOUT":
                telemetry.increment("simulator_timeouts_total")
            event("simulator_failure", method=method, code=code, status=exc.status_code)
            raise
        if result.stale:
            telemetry.increment("simulator_stale_total")
            event("simulator_stale", method=method)
        if method == "POST":
            telemetry.increment("commands_succeeded_total")
            event("simulator_command", status=result.status_code)
        return result

    async def _request_once(
        self,
        method: Literal["GET", "POST"],
        path: str,
        adapter: TypeAdapter[Any],
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> ValidatedSimulatorResult:
        try:
            upstream = await self._http.request(method, path, params=params, json=json_body)
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
        try:
            payload = upstream.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "INVALID_SIMULATOR_RESPONSE", "message": "The simulator returned invalid JSON."},
            ) from exc

        try:
            data = adapter.validate_python(payload)
        except ValidationError as exc:
            logger.warning("Simulator response failed schema validation")
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

        return ValidatedSimulatorResult(
            data=data,
            stale=upstream.headers.get("X-Simulator-Stale", "").lower() == "true",
            status_code=upstream.status_code,
        )

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
    def _copy_stale_marker(result: ValidatedSimulatorResult, response: Response) -> None:
        if result.stale:
            response.headers["X-Simulator-Stale"] = "true"

    @staticmethod
    def _raise_for_upstream_error(upstream: httpx.Response) -> None:
        if not upstream.is_error:
            return
        try:
            detail: Any = upstream.json()
        except ValueError:
            detail = upstream.text[:1000]

        error_body: Any = detail
        if isinstance(detail, dict):
            if isinstance(detail.get("detail"), dict):
                error_body = detail["detail"]
            elif isinstance(detail.get("error"), dict):
                error_body = detail["error"]
        upstream_code = error_body.get("code") if isinstance(error_body, dict) else None
        message = error_body.get("message") if isinstance(error_body, dict) else None
        raise HTTPException(
            status_code=upstream.status_code,
            detail={
                "code": "SIMULATOR_REQUEST_FAILED",
                "upstream_code": upstream_code if isinstance(upstream_code, str) else None,
                "message": message if isinstance(message, str) else "The simulator rejected the request.",
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
