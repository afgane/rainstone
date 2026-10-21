"""Durable Batch spend policy and audit trail.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
from rainstone.models import GuardAudit, SpendGuard

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (SpendGuard.__table__, GuardAudit.__table__):
        table.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in (GuardAudit.__table__, SpendGuard.__table__):
        table.drop(op.get_bind(), checkfirst=True)
