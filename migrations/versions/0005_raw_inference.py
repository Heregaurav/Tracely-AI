"""Separate imported inference streams/alerts from immutable benchmark scores."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('inference_runs',sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('dataset_id',sa.String(80),sa.ForeignKey('datasets.id'),nullable=False),
        sa.Column('model_version',sa.String(80),sa.ForeignKey('model_versions.id'),nullable=False),
        sa.Column('parent_id',sa.String(64),sa.ForeignKey('inference_runs.id')),
        sa.Column('context_token',sa.String(64),nullable=False),sa.Column('coverage_start',sa.String(40),nullable=False),sa.Column('coverage_end',sa.String(40),nullable=False),
        sa.Column('actor',sa.String(256),nullable=False),sa.Column('input_sha256',sa.String(64),nullable=False),
        sa.Column('provenance',JSONB(),nullable=False),sa.Column('events',JSONB(),nullable=False),sa.Column('features',JSONB(),nullable=False),sa.Column('predictions',JSONB(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_inference_runs_dataset_id','inference_runs',['dataset_id'])
    op.create_index('inference_stream_history','inference_runs',['dataset_id','model_version','created_at'])
    op.create_table('inference_alerts',sa.Column('id',sa.String(64),primary_key=True),sa.Column('run_id',sa.String(64),sa.ForeignKey('inference_runs.id'),nullable=False),sa.Column('window_id',sa.String(64),nullable=False),sa.Column('severity',sa.String(16),nullable=False),sa.Column('status',sa.String(16),nullable=False),sa.Column('version',sa.Integer(),nullable=False),sa.UniqueConstraint('run_id','window_id'),sa.CheckConstraint("status IN ('OPEN','IN_PROGRESS','RESOLVED')"))
    op.create_index('ix_inference_alerts_run_id','inference_alerts',['run_id'])


def downgrade():
    op.drop_table('inference_alerts');op.drop_table('inference_runs')
