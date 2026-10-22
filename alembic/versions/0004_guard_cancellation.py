"""Persist cancellation intent, evidence and cleanup verification.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "guard_cancellation",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("galaxy_id", sa.String(100), nullable=False),
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("project", sa.String(200), nullable=False),
        sa.Column("location", sa.String(100), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("error", sa.String(200)),
        sa.Column("evidence", sa.JSON, nullable=False),
        sa.Column("cost_reconciled", sa.Boolean, nullable=False),
        sa.UniqueConstraint("tenant_id", "job_id", "external_id"),
    )
    op.create_table(
        "guard_control_status",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("error", sa.String(200)),
        sa.Column("retry_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("guard_control_status")
    op.drop_table("guard_cancellation")
