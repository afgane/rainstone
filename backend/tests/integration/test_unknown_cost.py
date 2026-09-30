"""A day whose jobs all lack a known cost is unknown, never zero, in every report that draws days."""

import json
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.ingestion import ingest_fixture
from rainstone.models import Tenant
from sqlalchemy import select
from sqlalchemy.orm import Session

SLUG = "unknown-cost"
HEADERS = {
    "X-Rainstone-Tenant": SLUG, "X-Rainstone-User": "admin", "X-Rainstone-Admin": "true",
}
WINDOW = {"from": "2026-06-01T00:00:00Z", "to": "2026-06-10T00:00:00Z", "timezone": "UTC"}
# No price anywhere covers this machine, so the work it ran is unpriced.
UNPRICED_MACHINE = "zz-unpriced-machine"


def job_on(template: dict, number: int, day: str, machine: str) -> dict:
    job = deepcopy(template)
    job["source_id"] = str(9000 + number)
    job["owner_source_id"] = "admin"
    job["created_at"] = f"{day}T10:00:00Z"
    job["updated_at"] = f"{day}T10:30:00Z"
    attempt = job["attempts"][0]
    attempt["source_attempt_id"] = f"attempt-{number}"
    attempt["external_id"] = f"unknown-cost-{number}"
    attempt["tool_started_at"] = f"{day}T10:05:00Z"
    attempt["tool_finished_at"] = f"{day}T10:25:00Z"
    lifetime = attempt["lifetimes"][0]
    lifetime["resource_uid"] = f"vm-{number}"
    lifetime["resource_key"] = f"vm-unknown-cost-{number}"
    lifetime["machine_type"] = machine
    lifetime["observed_start"] = f"{day}T10:04:00Z"
    lifetime["observed_end"] = f"{day}T10:26:00Z"
    return job


@pytest.fixture(scope="module")
def tenant_client(tmp_path_factory):
    demo = json.loads(Path("fixtures/runs-demo.json").read_text())
    template = next(
        job for job in demo["jobs"]
        if job["state"] == "ok" and job["attempts"][0]["lifetimes"]
        and job["attempts"][0]["lifetimes"][0]["capacity_relationship"] == "dedicated"
    )
    fixture = {
        "schema_version": demo["schema_version"], "fixture_id": "unknown-cost-v1",
        "observed_at": "2026-06-30T00:00:00Z",
        "tenant": {
            "slug": SLUG, "display_name": "Unknown cost demonstration", "source_version": "test",
            "base_url": "https://example.invalid/galaxy", "capabilities": {"fixture": True},
        },
        "owners": [{"source_id": "admin", "label": "Admin", "is_admin": True}],
        "policies": [], "prices": [], "invocations": [], "infrastructure_intervals": [],
        "jobs": [
            # 2 June has only work nothing can price; 3 June has priced work too.
            job_on(template, 1, "2026-06-02", UNPRICED_MACHINE),
            job_on(template, 2, "2026-06-03", UNPRICED_MACHINE),
            job_on(template, 3, "2026-06-03", "n2-standard-2"),
        ],
    }
    path = tmp_path_factory.mktemp("fixtures") / "unknown-cost.json"
    path.write_text(json.dumps(fixture))
    with Session(engine) as session:
        ingest_fixture(session, path)
        tenant = session.scalar(select(Tenant).where(Tenant.slug == SLUG))
        calculate_tenant(session, tenant.id, reason="unknown cost demonstration")
        session.commit()
    from rainstone.main import app
    yield TestClient(app)
    with Session(engine) as session:
        session.delete(session.scalar(select(Tenant).where(Tenant.slug == SLUG)))
        session.commit()


def get(client, path: str, **params) -> dict:
    response = client.get(f"/api/{path}", params={**WINDOW, **params}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_day_with_no_known_cost_is_null_in_the_daily_report(tenant_client) -> None:
    days = {item["date"]: item for item in get(tenant_client, "daily")["items"]}
    assert days["2026-06-02"]["amount"] is None
    assert days["2026-06-02"]["incomplete_count"] == 1
    assert days["2026-06-02"]["job_count"] == 1
    # The known part of a mixed day is reported beside what is missing.
    assert Decimal(days["2026-06-03"]["amount"]) > 0
    assert days["2026-06-03"]["incomplete_count"] == 1


def test_an_observed_zero_stays_a_zero(tenant_client) -> None:
    # A zero is only ever reported where it was observed; the unknown day above is not one.
    days = get(tenant_client, "daily")["items"]
    assert all(item["amount"] is None or Decimal(item["amount"]) >= 0 for item in days)


def test_the_timeline_says_the_same_about_each_day(tenant_client) -> None:
    columns = {b["from"][:10]: b["amount"] for b in get(tenant_client, "timeline", bucket="day")["buckets"]}
    days = {item["date"]: item["amount"] for item in get(tenant_client, "daily")["items"]}
    assert columns.keys() == days.keys()
    assert columns["2026-06-02"] is None
    for day, amount in days.items():
        if amount is None:
            assert columns[day] is None
        else:
            assert abs(Decimal(columns[day]) - Decimal(amount)) < Decimal("1e-9")


def test_the_summary_counts_the_unpriced_jobs_rather_than_the_day(tenant_client) -> None:
    summary = get(tenant_client, "summary")
    assert summary["unpriced_job_count"] == 2
    assert Decimal(summary["amount"]) > 0


def test_a_chart_axis_is_written_like_its_columns(tenant_client) -> None:
    result = get(tenant_client, "timeline", bucket="day")
    last = result["buckets"][-1]
    for moment in (result["axis"]["from"], result["axis"]["to"], last["to"]):
        assert moment.endswith("Z")
        datetime.fromisoformat(moment.replace("Z", "+00:00"))
    assert result["axis"]["to"] >= last["to"]
