"""Operational state; raw events remain immutable Parquet."""
from datetime import datetime, timezone
import uuid

from sqlalchemy import (JSON, BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def identifier():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    provenance: Mapped[dict] = mapped_column(JSONB)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Principal(Base):
    __tablename__ = "users"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), primary_key=True)


class DailyBehavior(Base):
    __tablename__ = "daily_behaviors"
    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), primary_key=True)
    relative_day: Mapped[int] = mapped_column(Integer, primary_key=True)
    feature_version: Mapped[str] = mapped_column(String(80), primary_key=True)
    values: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (ForeignKeyConstraint(["dataset_id", "user"], ["users.dataset_id", "users.user"]),)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    feature_version: Mapped[str] = mapped_column(String(80))
    artifact_path: Mapped[str] = mapped_column(Text)
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    report: Mapped[dict] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("one_active_model_per_dataset", "dataset_id", unique=True, postgresql_where=text("active")),)


class DailyScore(Base):
    __tablename__ = "daily_risk_scores"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(80))
    user: Mapped[str] = mapped_column(String(256))
    relative_day: Mapped[int] = mapped_column(Integer)
    feature_version: Mapped[str] = mapped_column(String(80))
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    risk_score: Mapped[float] = mapped_column(Float)
    risk_tier: Mapped[str] = mapped_column(String(16))
    components: Mapped[dict] = mapped_column(JSONB)
    explanation: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(["dataset_id", "user", "relative_day", "feature_version"],
                             ["daily_behaviors.dataset_id", "daily_behaviors.user", "daily_behaviors.relative_day", "daily_behaviors.feature_version"]),
        UniqueConstraint("dataset_id", "user", "relative_day", "model_version"),
        CheckConstraint("risk_score >= 0 AND risk_score <= 100"),
        Index("scores_user_history", "dataset_id", "user", "relative_day"),
        Index("scores_model_day", "model_version", "relative_day"),
        Index("scores_ranking", "dataset_id", "model_version", "risk_score"),
    )


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    score_id: Mapped[str] = mapped_column(ForeignKey("daily_risk_scores.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    severity: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')"),
                      Index("alerts_worklist", "status", "severity", "created_at"))


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    actor: Mapped[str] = mapped_column(String(256))
    previous_status: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    actor: Mapped[str] = mapped_column(String(256))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(256))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class TrainingJob(Base):
    __tablename__ = "training_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=identifier)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    actor: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    config: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("one_pending_training_per_dataset", "dataset_id", unique=True,
                          postgresql_where=text("status IN ('QUEUED','RUNNING')")),
                      CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')"))


class Relationship(Base):
    __tablename__ = "relationships"
    dataset_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user: Mapped[str] = mapped_column(String(256), primary_key=True)
    relative_day: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_computer: Mapped[str] = mapped_column(String(256), primary_key=True)
    destination_computer: Mapped[str] = mapped_column(String(256), primary_key=True)
    weight: Mapped[int] = mapped_column(Integer)
    __table_args__ = (ForeignKeyConstraint(["dataset_id", "user"], ["users.dataset_id", "users.user"]),)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    checkpoint: Mapped[dict] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReplayRun(Base):
    __tablename__ = "replay_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    actor: Mapped[str] = mapped_column(String(256))
    inputs_sha256: Mapped[str] = mapped_column(String(64))
    predictions: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InferenceRun(Base):
    __tablename__ = "inference_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    model_version: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("inference_runs.id"))
    context_token: Mapped[str] = mapped_column(String(64))
    coverage_start: Mapped[str] = mapped_column(String(40))
    coverage_end: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(256))
    input_sha256: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[dict] = mapped_column(JSONB)
    events: Mapped[list] = mapped_column(JSONB)
    features: Mapped[list] = mapped_column(JSONB)
    predictions: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (Index("inference_stream_history", "dataset_id", "model_version", "created_at"),)


class InferenceAlert(Base):
    __tablename__ = "inference_alerts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("inference_runs.id"), index=True)
    window_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (UniqueConstraint("run_id","window_id"),CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')"))


class StoredAsset(Base):
    __tablename__ = "stored_assets"
    asset_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
