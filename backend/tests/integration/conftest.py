import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
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


@pytest.fixture(scope="session", autouse=True)
def seeded_database(tmp_path_factory) -> None:
    demonstration = json.loads(Path("fixtures/runs-demo.json").read_text())
    demonstration["tenant"] = {
        **demonstration["tenant"], "slug": RUNS_TENANT, "display_name": "Workflow runs demonstration",
    }
    runs_path = tmp_path_factory.mktemp("fixtures") / "runs-demo.json"
    runs_path.write_text(json.dumps(demonstration))
    with Session(engine) as session:
        ingest_fixture(session, Path("fixtures/phase1.json"))
        ingest_fixture(session, runs_path)


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
