"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers, register_middleware
from app.core.logging import configure_logging, configure_sentry, get_logger

log = get_logger("api.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "api_starting",
        environment=settings.environment,
        auth_provider=settings.auth_provider,
        version=settings.api_version,
    )
    yield
    log.info("api_stopping")


def create_app() -> FastAPI:
    configure_logging(settings)
    configure_sentry(settings)
    # Refuses to boot production on dev defaults instead of failing quietly later.
    settings.assert_production_safe()

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        lifespan=lifespan,
        # OpenAPI is the handover artifact (Phase 5), so keep it on everywhere.
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()
