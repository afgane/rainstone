"""Durable Batch spend policy and audit trail.

Revision ID: 0002
Revises: 0001

Tables are defined here as they were at this revision, not imported from the
models, so later model changes cannot alter what this migration creates.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spend_guard",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("owner.id"), nullable=False),
        sa.Column("enrollment", sa.String(100)),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("amount", sa.Numeric(24, 12)),
        sa.Column("stop_jobs", sa.Boolean, nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
    )
    op.create_table(
        "guard_audit",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenant.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
    )
    op.create_index("ix_guard_audit_tenant_time", "guard_audit", ["tenant_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("guard_audit")
    op.drop_table("spend_guard")
