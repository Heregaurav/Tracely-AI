"""Database-shared request budgets across API workers."""
from alembic import op
import sqlalchemy as sa
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("rate_limits",sa.Column("key",sa.String(64),primary_key=True),sa.Column("count",sa.Integer(),nullable=False),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False))
    op.create_index("ix_rate_limits_expires_at","rate_limits",["expires_at"])


def downgrade():
    op.drop_table("rate_limits")
