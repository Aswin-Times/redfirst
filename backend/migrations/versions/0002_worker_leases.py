"""worker ownership leases

Adds investigations.worker_id and investigations.lease_expires_at so several workers can run
safely: a run is recovered only after its owner's lease expires (M9, audit finding D5).
Existing rows get NULL in both columns; an in-progress row with no lease is treated as expired.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('investigations') as batch:
        batch.add_column(sa.Column('worker_id', sa.String(length=100), nullable=True))
        batch.add_column(sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('investigations') as batch:
        batch.drop_column('lease_expires_at')
        batch.drop_column('worker_id')
