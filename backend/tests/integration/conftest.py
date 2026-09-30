import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rainstone import costing
from rainstone.catalog import import_catalog, load_file
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.ingestion import ingest_fixture
from rainstone.main import app
from rainstone.models import Tenant
from sqlalchemy import select
from sqlalchemy.orm import Session

# The generated demonstration runs load into a tenant of their own, so the
# scenarios the phase 1 fixture pins down keep meaning exactly what they say.
RUNS_TENANT = "runs-demo"


# The demonstration fixtures end at this instant, with some jobs still running on VMs that have not
# stopped. Work like that is costed up to the time of the calculation, so on any later day the real
# clock would add days of cost the fixtures never describe, and every dated expectation would drift.
FIXTURE_NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


@pytest.fixture(scope="session", autouse=True)
def fixture_clock():
    patch = pytest.MonkeyPatch()
    patch.setattr(costing, "utcnow", lambda: FIXTURE_NOW)
    yield
    patch.undo()


@pytest.fixture(scope="session", autouse=True)
def seeded_database(tmp_path_factory, fixture_clock) -> None:
    demonstration = json.loads(Path("fixtures/runs-demo.json").read_text())
    demonstration["tenant"] = {
        **demonstration["tenant"], "slug": RUNS_TENANT, "display_name": "Workflow runs demonstration",
    }
    runs_path = tmp_path_factory.mktemp("fixtures") / "runs-demo.json"
    runs_path.write_text(json.dumps(demonstration))
    with Session(engine) as session:
        ingest_fixture(session, Path("fixtures/phase1.json"))
        ingest_fixture(session, runs_path)
        # A running service has its bundled price catalog imported before it reports anything.
        import_catalog(session, load_file(Path("catalog/gcp-2026-09-19.json")))
        for tenant_id in session.scalars(select(Tenant.id)).all():
            calculate_tenant(session, tenant_id, reason="bundled price catalog")
        session.commit()


@pytest.fixture(autouse=True)
def recalculated_after_fact_changes():
    """Recalculate between tests, as the collector does after every batch.

    Report facts advance a generation marker, so a test that writes facts
    directly leaves pinned snapshots stale until something recalculates. Doing
    that here keeps the suite order-independent without weakening the staleness
    contract each test asserts.
    """
    yield
    with Session(engine) as session:
        for tenant_id in session.scalars(select(Tenant.id)).all():
            calculate_tenant(session, tenant_id, reason="test recalculation")
        session.commit()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def headers(user: str, admin: bool = False) -> dict[str, str]:
    result = {"X-Rainstone-Tenant": "anvil-demo", "X-Rainstone-User": user}
    if admin:
        result["X-Rainstone-Admin"] = "true"
    return result


def run_headers(user: str = "admin", admin: bool = True) -> dict[str, str]:
    """Identity in the generated demonstration tenant; administrators see every run."""
    return {**headers(user, admin), "X-Rainstone-Tenant": RUNS_TENANT}
