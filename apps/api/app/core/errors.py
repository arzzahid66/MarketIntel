"""Uniform error envelope + request correlation.

Every error the API returns has the same shape, and every log line and error
response carries the same request id. That is what makes a production incident
traceable from a screenshot the client sends you.
"""

from __future__ import annotations

import time
import uuid

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

log = get_logger("api.request")

REQUEST_ID_HEADER = "X-Request-ID"


def register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception(
                "request_failed",
                method=request.method,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        # Health probes would otherwise dominate the log volume.
        if not request.url.path.startswith("/health"):
            log.info(
                "request_completed",
                method=request.method,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        return response


def _envelope(status_code: int, error: str, detail: object, request: Request) -> JSONResponse:
    request_id = request.headers.get(REQUEST_ID_HEADER)
    body = {"error": error, "detail": detail, "status": status_code}
    if request_id:
        body["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error = "http_error"
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            error = str(exc.detail["error"])
        response = _envelope(exc.status_code, error, exc.detail, request)
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Numeric literal: Starlette renamed this constant, and the wire value
        # is the contract, not the constant name.
        return _envelope(422, "validation_error", exc.errors(), request)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Sentry has already captured this via its integration. Never leak internals.
        log.error("unhandled_exception", exc_type=type(exc).__name__)
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected error occurred",
            request,
        )
