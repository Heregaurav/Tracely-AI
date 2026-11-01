"""FastAPI application factory.

Replaces src/api/service.py (Flask).

The external API surface — routes, request parameters, response shapes, status
codes, session cookies, and CSRF semantics — is identical to the previous Flask
implementation so that the React frontend requires no changes.

Key differences from Flask:
- SessionMiddleware (Starlette) replaces Flask's signed-cookie sessions.
  Sessions are signed with the same SESSION_SECRET; users need to log in once
  after the migration because the cookie serialisation format changed.
- FastAPI dependency injection replaces Flask's g, closures, and decorators.
- Pydantic models validate all request bodies and document the OpenAPI schema.
- /docs and /redoc expose the interactive API documentation (restricted in
  production — set DOCS_ENABLED=1 to override).
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware

from src.api.dependencies import Settings, get_settings, _get_factory
from src.api.routers import auth as auth_module
from src.api.routers.auth import register_oidc
from src.api.routers.alerts import router as alerts_router
from src.api.routers.health import router as health_router
from src.api.routers.inference import router as inference_router
from src.api.routers.models import router as models_router
from src.api.routers.overview import router as overview_router
from src.api.routers.replay import router as replay_router
from src.api.routers.users import router as users_router

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Security middleware: enforce auth + CSRF on all /api/* paths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

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

    # Middleware is applied in reverse registration order:
    # add_middleware last = outermost wrapper = first to execute.
    # We want:  CORS (outermost) → SessionMiddleware → auth_guard → route

    # 1. auth_guard is innermost — added first so it runs after session is populated.
    @app.middleware("http")
    async def auth_guard(request: Request, call_next):
        path = request.url.path
        method = request.method
        skip = (
            method == "OPTIONS"
            or path in ("/health/live", "/health/ready", "/health")
            or path.startswith("/api/auth/")
            or path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/openapi")
            or not path.startswith("/api/")
        )
        if not skip and not request.session.get("actor"):
            return JSONResponse(
                {"error": "Authentication required", "status": "error"},
                status_code=401,
            )
        return await call_next(request)

    # 2. SessionMiddleware — wraps auth_guard so session is ready when auth runs.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="session",
        same_site="lax",
        https_only=settings.app_env != "development",
        max_age=30 * 60,  # 30 minutes
    )

    # 3. CORS — outermost so preflight OPTIONS passes before session check.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
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
    app.include_router(auth_module.router)
    app.include_router(overview_router)
    app.include_router(users_router)
    app.include_router(alerts_router)
    app.include_router(models_router)
    app.include_router(replay_router)
    app.include_router(inference_router)

    # -- Optional OIDC routes --
    register_oidc(app, settings)

    if settings.app_env == "development":
        logger.warning(
            "Development mode: local username/password login is enabled. "
            "API documentation is available at /docs."
        )
    elif not settings.oidc_issuer:
        raise ValueError(
            "Production requires organization-backed OIDC configuration"
        )

    return app
