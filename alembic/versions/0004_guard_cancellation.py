"""Persist cancellation intent, evidence and cleanup verification.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
from rainstone.models import GuardCancellation, GuardControlStatus

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (GuardCancellation.__table__, GuardControlStatus.__table__):
        table.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in (GuardControlStatus.__table__, GuardCancellation.__table__):
        table.drop(op.get_bind(), checkfirst=True)
