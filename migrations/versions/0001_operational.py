"""Initial PostgreSQL operational schema.

Revision ID: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("datasets", sa.Column("id",sa.String(80),primary_key=True), sa.Column("provenance",postgresql.JSONB(),nullable=False),sa.Column("is_fixture",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("users",sa.Column("dataset_id",sa.String(80),sa.ForeignKey("datasets.id"),primary_key=True),sa.Column("user",sa.String(256),primary_key=True))
    op.create_table("daily_behaviors",sa.Column("dataset_id",sa.String(80),primary_key=True),sa.Column("user",sa.String(256),primary_key=True),sa.Column("relative_day",sa.Integer(),primary_key=True),sa.Column("feature_version",sa.String(80),primary_key=True),sa.Column("values",postgresql.JSONB(),nullable=False),sa.ForeignKeyConstraint(["dataset_id","user"],["users.dataset_id","users.user"]))
    op.create_table("model_versions",sa.Column("id",sa.String(80),primary_key=True),sa.Column("dataset_id",sa.String(80),sa.ForeignKey("datasets.id"),nullable=False),sa.Column("feature_version",sa.String(80),nullable=False),sa.Column("artifact_path",sa.Text(),nullable=False),sa.Column("artifact_sha256",sa.String(64),nullable=False),sa.Column("report",postgresql.JSONB(),nullable=False),sa.Column("active",sa.Boolean(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_model_versions_dataset_id","model_versions",["dataset_id"])
    op.create_index("one_active_model_per_dataset","model_versions",["dataset_id"],unique=True,postgresql_where=sa.text("active"))
    op.create_table("daily_risk_scores",sa.Column("id",sa.String(64),primary_key=True),sa.Column("dataset_id",sa.String(80),nullable=False),sa.Column("user",sa.String(256),nullable=False),sa.Column("relative_day",sa.Integer(),nullable=False),sa.Column("feature_version",sa.String(80),nullable=False),sa.Column("model_version",sa.String(80),sa.ForeignKey("model_versions.id"),nullable=False),sa.Column("risk_score",sa.Float(),nullable=False),sa.Column("risk_tier",sa.String(16),nullable=False),sa.Column("components",postgresql.JSONB(),nullable=False),sa.Column("explanation",postgresql.JSONB(),nullable=False),sa.ForeignKeyConstraint(["dataset_id","user","relative_day","feature_version"],["daily_behaviors.dataset_id","daily_behaviors.user","daily_behaviors.relative_day","daily_behaviors.feature_version"]),sa.UniqueConstraint("dataset_id","user","relative_day","model_version"),sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100"))
    for name,columns in [("scores_user_history",["dataset_id","user","relative_day"]),("scores_model_day",["model_version","relative_day"]),("scores_ranking",["dataset_id","model_version","risk_score"])]:
        op.create_index(name,"daily_risk_scores",columns)
    op.create_table("alerts",sa.Column("id",sa.String(64),primary_key=True),sa.Column("score_id",sa.String(64),sa.ForeignKey("daily_risk_scores.id"),nullable=False,unique=True),sa.Column("status",sa.String(16),nullable=False),sa.Column("severity",sa.String(16),nullable=False),sa.Column("version",sa.Integer(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("resolved_at",sa.DateTime(timezone=True)),sa.CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')"))
    op.create_index("alerts_worklist","alerts",["status","severity","created_at"])
    op.create_table("alert_events",sa.Column("id",sa.String(32),primary_key=True),sa.Column("alert_id",sa.String(64),sa.ForeignKey("alerts.id"),nullable=False),sa.Column("actor",sa.String(256),nullable=False),sa.Column("previous_status",sa.String(16),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_alert_events_alert_id","alert_events",["alert_id"])
    op.create_table("audit_logs",sa.Column("id",sa.String(32),primary_key=True),sa.Column("actor",sa.String(256),nullable=False),sa.Column("action",sa.String(80),nullable=False),sa.Column("target",sa.String(256),nullable=False),sa.Column("details",postgresql.JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_audit_logs_created_at","audit_logs",["created_at"])
    op.create_table("training_jobs",sa.Column("id",sa.String(32),primary_key=True),sa.Column("dataset_id",sa.String(80),sa.ForeignKey("datasets.id"),nullable=False),sa.Column("actor",sa.String(256),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("progress",sa.Integer(),nullable=False),sa.Column("config",postgresql.JSONB(),nullable=False),sa.Column("result",postgresql.JSONB()),sa.Column("error",sa.Text()),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("started_at",sa.DateTime(timezone=True)),sa.Column("finished_at",sa.DateTime(timezone=True)),sa.Column("heartbeat_at",sa.DateTime(timezone=True)),sa.CheckConstraint("status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')"))
    op.create_index("ix_training_jobs_status","training_jobs",["status"])
    op.create_index("one_pending_training_per_dataset","training_jobs",["dataset_id"],unique=True,postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"))
    op.create_table("relationships",sa.Column("dataset_id",sa.String(80),primary_key=True),sa.Column("user",sa.String(256),primary_key=True),sa.Column("relative_day",sa.Integer(),primary_key=True),sa.Column("source_computer",sa.String(256),primary_key=True),sa.Column("destination_computer",sa.String(256),primary_key=True),sa.Column("weight",sa.Integer(),nullable=False),sa.ForeignKeyConstraint(["dataset_id","user"],["users.dataset_id","users.user"]))


def downgrade():
    for name in ("relationships","training_jobs","audit_logs","alert_events","alerts","daily_risk_scores","model_versions","daily_behaviors","users","datasets"):
        op.drop_table(name)
