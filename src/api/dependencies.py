"""FastAPI dependency injection.

Provides reusable dependencies for database sessions, settings, authentication,
role-based access control, and the active ML model.  Replaces Flask's g, the
factory closure, scope(), and require() decorator from the old service.py.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import timedelta
from functools import lru_cache
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.db.models import ModelVersion, RateLimit, now
from src.db.session import database


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class Settings:
    """Typed access to application configuration from environment variables.

    Uses environment variables in the same layout as the Flask app so that
    .env.spedia.local and existing deployment scripts remain unchanged.
    """

    def __init__(self) -> None:
        self.database_url: str = os.environ["DATABASE_URL"]
        self.session_secret: str = os.environ["SESSION_SECRET"]
        self.app_env: str = os.getenv("APP_ENV", "production")
        self.dataset_id: str = os.getenv("DATASET_ID", "spedia-v2")
        self.frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:8000")
        self.feature_path: str = os.getenv(
            "FEATURE_PATH", "data/spedia/features-temporal/features.parquet"
        )
        self.artifact_root: str = os.getenv("ARTIFACT_ROOT", "data/artifacts")
        self.allow_fixture_data: bool = os.getenv("ALLOW_FIXTURE_DATA") == "1"
        self.dev_auth_users: dict = json.loads(os.getenv("DEV_AUTH_USERS", "{}"))
        self.oidc_issuer: str | None = os.getenv("OIDC_ISSUER") or None
        self.oidc_roles: dict = json.loads(os.getenv("OIDC_ROLES", "{}"))
        self.replay_directory: str | None = os.getenv("REPLAY_DIRECTORY") or None
        self.realistic_replay_directory: str | None = (
            os.getenv("REALISTIC_REPLAY_DIRECTORY") or None
        )
        self.inference_context_directory: str | None = (
            os.getenv("INFERENCE_CONTEXT_DIRECTORY") or None
        )
        self.max_upload_bytes: int = 320 * 1024

        if not self.session_secret or len(self.session_secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 random characters")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton; called once per worker process."""
    return Settings()


# ---------------------------------------------------------------------------
# Database session factory (module-level singleton)
# ---------------------------------------------------------------------------

_engine = None
_session_factory = None


def _get_factory():
    """Lazy-initialise the SQLAlchemy engine and session factory once."""
    global _engine, _session_factory
    if _session_factory is None:
        settings = get_settings()
        _engine, _session_factory = database(settings.database_url)
    return _session_factory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped SQLAlchemy session.

    The session is committed on success and rolled back on any exception,
    preserving the same transaction semantics as the Flask factory() context
    manager.
    """
    factory = _get_factory()
    db = factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_rw() -> Generator[Session, None, None]:
    """Yields a session for write transactions (same as get_db but named for clarity)."""
    yield from get_db()


# ---------------------------------------------------------------------------
# Role hierarchy
# ---------------------------------------------------------------------------

ROLES = {"VIEWER": 1, "ANALYST": 2, "ADMIN": 3}


# ---------------------------------------------------------------------------
# Rate limiting (DB-backed, same implementation as Flask auth.py)
# ---------------------------------------------------------------------------

def _budget(db: Session, actor: str, limit: int, kind: str) -> None:
    """Check request budget for actor+kind; raises 429 if exceeded."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    instant = now()
    minute = int(instant.timestamp()) // 60
    key = hashlib.sha256(f"{actor}|{kind}|{minute}".encode()).hexdigest()
    db.execute(
        text("DELETE FROM rate_limits WHERE expires_at < :now"), {"now": instant}
    )
    stmt = (
        pg_insert(RateLimit)
        .values(key=key, count=1, expires_at=instant + timedelta(minutes=2))
        .on_conflict_do_update(
            index_elements=[RateLimit.key],
            set_={"count": RateLimit.count + 1},
        )
        .returning(RateLimit.count)
    )
    count = db.execute(stmt).scalar_one()
    db.commit()
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request budget exceeded; retry next minute",
        )


# ---------------------------------------------------------------------------
# Session and auth dependencies
# ---------------------------------------------------------------------------

def get_session_data(request: Request) -> dict:
    """Return the Starlette session dict (populated by SessionMiddleware)."""
    return request.session


def get_actor(request: Request) -> str:
    """Return the authenticated actor username, or raise 401."""
    actor = request.session.get("actor")
    if not actor:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return actor


def require_role(min_role: str):
    """Return a FastAPI dependency that enforces a minimum role.

    Usage:
        @router.get("/protected")
        async def endpoint(actor: str = Depends(require_role("ANALYST"))):
            ...
    """
    def dependency(request: Request) -> str:
        actor = request.session.get("actor")
        if not actor:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        role = request.session.get("role", "")
        if ROLES.get(role, 0) < ROLES.get(min_role, 99):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role",
            )
        return actor

    return dependency


def check_csrf(request: Request) -> None:
    """Dependency that validates the CSRF token for state-mutating methods."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    csrf_header = request.headers.get("X-CSRF-Token", "")
    csrf_session = request.session.get("csrf", "missing")
    if not secrets.compare_digest(csrf_header, csrf_session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token required",
        )


def require_analyst_csrf(request: Request) -> str:
    """Combined ANALYST role + CSRF dependency for mutating endpoints."""
    check_csrf(request)
    return require_role("ANALYST")(request)


def require_admin_csrf(request: Request) -> str:
    """Combined ADMIN role + CSRF dependency for mutating endpoints."""
    check_csrf(request)
    return require_role("ADMIN")(request)


# ---------------------------------------------------------------------------
# Active model
# ---------------------------------------------------------------------------

def get_active_model(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ModelVersion:
    """Fetch and validate the active model for this dataset.

    Raises 503 when:
    - No active model is registered.
    - The dataset is a fixture and fixture data is disabled.
    - The model does not implement the supported hour-window contract.
    """
    model = db.scalar(
        select(ModelVersion).where(
            ModelVersion.dataset_id == settings.dataset_id,
            ModelVersion.active,
        )
    )
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active model; ingest, train, and publish source-backed data first",
        )
    if model.report.get("is_fixture") and not settings.allow_fixture_data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fixture data is disabled",
        )
    contract = model.report.get("contract", {})
    if contract.get("window_seconds") != 3600:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Active model does not implement the supported closed-hour contract",
        )
    return model
