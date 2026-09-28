"""The Galaxy server's current running session.

Revision ID: 0002
Revises: 0001

Revision 0001 creates every table the models declare, so on a new database
this table already exists and only its triggers are added here.

The session row is a report fact, so writes to it advance the report
generation like every other fact table. The collector rewrites its last
observation time every minute, though, and treating that heartbeat as a fact
change would mark every pinned report stale once a minute. Updates therefore
advance the generation only when something other than `observed_at` changed.
"""

from rainstone.models import GalaxyServerSession

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLE = "galaxy_server_session"
FACT_COLUMNS = (
    "tenant_id", "provider", "resource_uid", "name", "project", "zone", "region",
    "machine_type", "purchase_model", "state", "descriptor_source", "session_key",
    "launch_at", "launch_source", "launch_unavailable_reason", "ended_at",
    "shape_conflict", "first_observed_at",
)
_DIRECT = "SELECT c.tenant_id FROM changed c JOIN tenant t ON t.id = c.tenant_id"
_CHANGED_FACTS = (
    "SELECT c.tenant_id FROM changed c JOIN tenant t ON t.id = c.tenant_id "
    "LEFT JOIN previous p ON p.id = c.id "
    "WHERE p.id IS NULL OR "
    f"ROW({', '.join('p.' + name for name in FACT_COLUMNS)}) IS DISTINCT FROM "
    f"ROW({', '.join('c.' + name for name in FACT_COLUMNS)})"
)
TRIGGERS = (
    ("insert", "INSERT", "NEW TABLE AS changed", _DIRECT),
    ("update", "UPDATE", "OLD TABLE AS previous NEW TABLE AS changed", _CHANGED_FACTS),
    ("delete", "DELETE", "OLD TABLE AS changed", _DIRECT),
)


def upgrade() -> None:
    GalaxyServerSession.__table__.create(bind=op.get_bind(), checkfirst=True)
    for suffix, operation, transitions, source in TRIGGERS:
        name = f"rainstone_generation_{TABLE}_{suffix}"
        op.execute(f"DROP TRIGGER IF EXISTS {name} ON {TABLE}")
        quoted = source.replace("'", "''")
        op.execute(f"""
            CREATE TRIGGER {name}
            AFTER {operation} ON {TABLE}
            REFERENCING {transitions}
            FOR EACH STATEMENT
            EXECUTE FUNCTION rainstone_advance_report_generation('{quoted}')
        """)


def downgrade() -> None:
    for suffix, _, _, _ in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS rainstone_generation_{TABLE}_{suffix} ON {TABLE}")
    GalaxyServerSession.__table__.drop(bind=op.get_bind(), checkfirst=True)
