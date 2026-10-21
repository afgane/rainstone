"""Record Galaxy broadcast identities and retry progress.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
from rainstone.models import GuardNotification

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    GuardNotification.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    GuardNotification.__table__.drop(op.get_bind(), checkfirst=True)
