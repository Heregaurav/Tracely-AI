"""Persist deterministic frozen-model replay runs separately from labels."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('replay_runs',sa.Column('id',sa.String(64),primary_key=True),sa.Column('dataset_id',sa.String(80),sa.ForeignKey('datasets.id'),nullable=False),sa.Column('model_version',sa.String(80),sa.ForeignKey('model_versions.id'),nullable=False),sa.Column('actor',sa.String(256),nullable=False),sa.Column('inputs_sha256',sa.String(64),nullable=False),sa.Column('predictions',postgresql.JSONB(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_replay_runs_dataset_id','replay_runs',['dataset_id'])


def downgrade():
    op.drop_index('ix_replay_runs_dataset_id',table_name='replay_runs');op.drop_table('replay_runs')
