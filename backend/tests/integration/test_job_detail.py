"""A job's detail reports its whole job: timing, resources, executions and measured use."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import ExecutionAttempt, JobMetric, Tenant
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .conftest import headers

GIB = 1024**3
# Job 13 ran on its own Batch VM for one second, asking for 1 vCPU and 18 GiB.
BATCH_JOB = "13"
SERVER_JOB = "9"
RETRIED_ON_ONE_VM = "28"
RUNNING_JOB = "24"
QUEUED_JOB = "25"


def job_id(client, source_id: str, user: str = "alice", admin: bool = False) -> str:
    items = client.get(
        "/api/jobs?basis=additional&limit=200", headers=headers(user, admin)
    ).json()["items"]
    return next(item["id"] for item in items if item["source_id"] == source_id)


def detail(client, source_id: str, query: str = "", user: str = "alice", admin: bool = False) -> dict:
    identifier = job_id(client, source_id, user, admin)
    response = client.get(f"/api/jobs/{identifier}?basis=additional{query}", headers=headers(user, admin))
    assert response.status_code == 200, response.text
    return response.json()


def recalculate() -> None:
    with Session(engine) as session:
        for tenant_id in session.scalars(select(Tenant.id)).all():
            calculate_tenant(session, tenant_id, reason="job detail test")
        session.commit()


@pytest.fixture()
def metrics(client):
    """Record metrics for one of alice's jobs for the length of a test."""
    recorded: list[uuid.UUID] = []

    def record(source_id: str, values: dict[tuple[str, str], int]) -> None:
        identifier = uuid.UUID(job_id(client, source_id))
        with Session(engine) as session:
            for (plugin, name), value in values.items():
                row = JobMetric(
                    id=uuid.uuid4(), job_id=identifier, plugin=plugin, name=name, numeric_value=Decimal(value)
                )
                session.add(row)
                recorded.append(row.id)
            session.commit()

    yield record
    with Session(engine) as session:
        session.execute(delete(JobMetric).where(JobMetric.id.in_(recorded)))
        session.commit()


def test_a_job_reports_its_whole_execution_timing(client) -> None:
    result = detail(client, BATCH_JOB)
    assert result["duration_seconds"] == 1
    assert result["duration_running"] is False
    assert result["duration_cutoff"] is None
    assert result["started_at"].startswith("2026-09-19T13:31:50")
    assert result["finished_at"].startswith("2026-09-19T13:31:51")
    # Submitted at 13:30:40; the wait is not called queue time.
    assert result["before_start_seconds"] == 70
    assert result["timing_issue"] is None
    assert [attempt["duration_seconds"] for attempt in result["attempts"]] == [1]


def test_measured_use_is_compared_with_the_request_of_one_execution(client, metrics) -> None:
    metrics(BATCH_JOB, {
        ("cgroup", "cpu.stat.usage_usec"): 500_000, ("cgroup", "memory.peak"): 9 * GIB,
        ("core", "galaxy_slots"): 1,
    })
    use = detail(client, BATCH_JOB)["resource_use"]
    assert use["measurement_scope"] == "single_execution"
    assert Decimal(use["cpu"]["average_cores"]) == Decimal("0.5")
    assert Decimal(use["cpu"]["request_fraction"]) == Decimal("0.5")
    assert Decimal(use["memory"]["request_fraction"]) == Decimal("0.5")
    assert {(metric["name"], metric["unit"]) for metric in use["metrics"]} == {
        ("cpu.stat.usage_usec", "microseconds"), ("memory.peak", "bytes"), ("galaxy_slots", "slots"),
    }


def test_a_machine_reports_its_published_size_apart_from_what_the_job_requested(client) -> None:
    [resource] = detail(client, BATCH_JOB)["resources"]
    assert resource["machine_type"] == "n2-highmem-4"
    assert resource["machine_capacity"] == {
        "vcpu": "4", "memory_mib": "32768", "gpu": None, "source": "published_machine_shape"
    }
    assert Decimal(resource["requested_vcpu"]) == 1


def test_missing_measurements_are_not_zero(client) -> None:
    use = detail(client, BATCH_JOB)["resource_use"]
    assert use["cpu"]["status"] == use["memory"]["status"] == "not_recorded"
    assert use["cpu"]["request_fraction"] is None and use["memory"]["peak_bytes"] is None
    assert use["cpu"]["requested_vcpu"] is not None
    assert use["metrics"] == []


def test_a_galaxy_servers_counters_are_not_reported_as_the_jobs(client, metrics) -> None:
    metrics(SERVER_JOB, {("cgroup", "cpu.stat.usage_usec"): 5_000_000, ("cgroup", "memory.peak"): GIB})
    use = detail(client, SERVER_JOB)["resource_use"]
    assert use["measurement_scope"] == "unestablished"
    assert use["scope_reason"] == "galaxy_server"
    assert use["cpu"]["cpu_seconds"] is None and use["memory"]["peak_bytes"] is None


def test_a_job_counter_is_not_matched_to_a_retry(client, metrics) -> None:
    metrics(RETRIED_ON_ONE_VM, {("cgroup", "cpu.stat.usage_usec"): 5_000_000})
    result = detail(client, RETRIED_ON_ONE_VM)
    assert result["resource_use"]["cpu"]["reason"] == "several_executions"
    assert result["resource_use"]["cpu"]["average_cores"] is None
    # The retries' shared VM is one resource, charged once, shared by both.
    assert len(result["resources"]) == 1
    assert {len(attempt["amount_shared_with_attempts"]) for attempt in result["attempts"]} == {1}


def test_a_running_job_is_timed_to_the_snapshot_and_has_no_average(client, metrics) -> None:
    metrics(RUNNING_JOB, {("cgroup", "cpu.stat.usage_usec"): 5_000_000})
    result = detail(client, RUNNING_JOB)
    assert result["duration_running"] is True
    assert result["finished_at"] is None
    assert result["duration_cutoff"] is not None
    assert result["resource_use"]["cpu"]["reason"] == "running"


def test_a_job_that_has_not_started_has_no_execution_timing(client) -> None:
    result = detail(client, QUEUED_JOB, user="bob")
    assert result["started_at"] is None
    assert result["duration_seconds"] is None and result["before_start_seconds"] is None
    assert result["resource_use"]["scope_reason"] == "no_execution"


def test_the_headline_and_its_evidence_stay_whole_when_a_period_holds_part_of_a_job(client) -> None:
    whole = detail(client, BATCH_JOB)
    part = detail(client, BATCH_JOB, "&from=2026-09-19T13:32:00Z&to=2026-09-19T14:00:00Z")
    assert part["full_job_amount"] == whole["full_job_amount"]
    assert Decimal(part["interval_amount"]) < Decimal(part["full_job_amount"])
    assert part["resources"] == whole["resources"]
    assert part["attempts"] == whole["attempts"]
    assert Decimal(part["resources"][0]["amount"]) == Decimal(part["full_job_amount"])
    assert part["full_quality"] == whole["full_quality"]


def test_a_job_outside_the_viewers_scope_is_not_found(client) -> None:
    identifier = job_id(client, BATCH_JOB)
    assert client.get(f"/api/jobs/{identifier}", headers=headers("bob")).status_code == 404


def test_a_finish_recorded_before_its_start_leaves_the_timing_unavailable(client) -> None:
    identifier = job_id(client, BATCH_JOB)
    with Session(engine) as session:
        attempt = session.scalar(select(ExecutionAttempt).where(ExecutionAttempt.job_id == uuid.UUID(identifier)))
        attempt_id, finished = attempt.id, attempt.tool_finished_at
        attempt.tool_finished_at = attempt.tool_started_at - timedelta(seconds=30)
        session.commit()
    recalculate()
    try:
        result = detail(client, BATCH_JOB)
    finally:
        with Session(engine) as session:
            session.get(ExecutionAttempt, attempt_id).tool_finished_at = finished
            session.commit()
        recalculate()
    assert result["timing_issue"] == "finished_before_started"
    assert result["duration_seconds"] is None and result["before_start_seconds"] is None
    assert result["attempts"][0]["duration_seconds"] is None
