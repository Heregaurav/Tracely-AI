"""Operational ingestion checkpoints; event staging remains disk-backed."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table("ingestion_jobs",sa.Column("id",sa.String(64),primary_key=True),sa.Column("dataset_id",sa.String(80),sa.ForeignKey("datasets.id"),nullable=False),sa.Column("source",sa.String(16),nullable=False),sa.Column("status",sa.String(16),nullable=False),sa.Column("checkpoint",postgresql.JSONB(),nullable=False),sa.Column("error",sa.Text()),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))


def downgrade():
    op.drop_table("ingestion_jobs")
