"""FastAPI application factory for the public SPEDIA dashboard."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.api.dependencies import Settings, get_settings, _get_factory
from src.api.limits import RequestBodyLimit
from src.api.routers.alerts import router as alerts_router
from src.api.routers.health import router as health_router
from src.api.routers.hours import router as hours_router
from src.api.routers.inference import router as inference_router
from src.api.routers.models import router as models_router
from src.api.routers.overview import router as overview_router
from src.api.routers.replay import router as replay_router
from src.api.routers.users import router as users_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional pre-built Settings object; useful for testing.

    Returns:
        A fully configured FastAPI application instance.
    """
    if settings is None:
        settings = get_settings()

    # Expose /docs and /redoc only when explicitly enabled or in development.
    docs_enabled = (
        settings.app_env == "development"
        or os.getenv("DOCS_ENABLED", "0") == "1"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Warm up the database connection pool on startup."""
        logger.info("Tracely AI FastAPI starting (env=%s)", settings.app_env)
        try:
            _get_factory()  # initialise engine + pool
        except Exception as exc:
            logger.error("Database initialisation failed: %s", exc)
            raise
        yield
        logger.info("Tracely AI FastAPI shutting down")

    app = FastAPI(
        title="Tracely AI — UEBA",
        description=(
            "Insider Threat Detection and User Entity Behavior Analytics API. "
            "Risk indices are not probabilities. Source timestamps retain their "
            "supplied time basis. Departments and employee intent are unavailable "
            "from the SPEDIA source."
        ),
        version="2.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )

    app.add_middleware(RequestBodyLimit, max_bytes=settings.max_upload_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Content-Type"],
    )

    # -- Exception handlers --
    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            {"error": exc.detail, "status": "error"},
            status_code=exc.status_code,
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError):
        logger.error("Database request failed (%s)", type(exc).__name__)
        return JSONResponse(
            {"error": "Database operation unavailable", "status": "error"},
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            {"error": "Internal server error", "status": "error"},
            status_code=500,
        )

    app.include_router(health_router)
    app.include_router(hours_router)
    app.include_router(overview_router)
    app.include_router(users_router)
    app.include_router(alerts_router)
    app.include_router(models_router)
    app.include_router(replay_router)
    app.include_router(inference_router)

    return app
