"""FastAPI dependency injection.

Provides reusable dependencies for database sessions, settings and the active ML model.  Replaces Flask's g, the
factory closure, scope(), and require() decorator from the old service.py.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Generator

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import ModelVersion
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
        self.app_env: str = os.getenv("APP_ENV", "production")
        self.dataset_id: str = os.getenv("DATASET_ID", "spedia-v2")
        self.frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:8000")
        self.feature_path: str = os.getenv(
            "FEATURE_PATH", "data/spedia/features-temporal/features.parquet"
        )
        self.artifact_root: str = os.getenv("ARTIFACT_ROOT", "data/artifacts")
        self.allow_fixture_data: bool = os.getenv("ALLOW_FIXTURE_DATA") == "1"
        self.replay_directory: str | None = os.getenv("REPLAY_DIRECTORY") or None
        self.realistic_replay_directory: str | None = (
            os.getenv("REALISTIC_REPLAY_DIRECTORY") or None
        )
        self.inference_context_directory: str | None = (
            os.getenv("INFERENCE_CONTEXT_DIRECTORY") or None
        )
        self.max_upload_bytes: int = 320 * 1024



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
# Public request attribution
# ---------------------------------------------------------------------------

def get_actor() -> str:
    """Attribute unauthenticated actions without implying a verified identity."""
    return "public"


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
