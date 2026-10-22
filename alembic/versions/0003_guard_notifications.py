"""Record Galaxy broadcast identities and retry progress.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guard_notification",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("condition", sa.String(40), primary_key=True),
        sa.Column("notification_id", sa.String(100)),
        sa.Column("error", sa.String(200)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("guard_notification")
