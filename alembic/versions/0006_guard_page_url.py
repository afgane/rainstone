"""Record the limit page URL the browser used, for Galaxy notifications.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spend_guard", sa.Column("page_url", sa.String(2000)))


def downgrade() -> None:
    op.drop_column("spend_guard", "page_url")
