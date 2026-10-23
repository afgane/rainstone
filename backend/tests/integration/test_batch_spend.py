import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rainstone import reporting
from rainstone.auth import Identity
from rainstone.batch_spend import batch_spend
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import (
    CapacityRelationship,
    CostLine,
    ExecutionAttempt,
    IngestionState,
    Invocation,
    InvocationJob,
    Job,
    LifetimeAttempt,
    Owner,
    PriceVersion,
    ResourceLifetime,
    Tenant,
)
from rainstone.overview import cost_timeline
from rainstone.report_query import ReportQuery
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

START = datetime(2026, 9, 20, tzinfo=UTC)


@pytest.fixture()
def spend_source():
    with Session(engine) as session:
        tenant = Tenant(id=uuid.uuid4(), slug=str(uuid.uuid4()), display_name="Guard test")
        session.add(tenant)
        session.flush()
        owner = Owner(id=uuid.uuid4(), tenant_id=tenant.id, source_id="owner", label="Owner")
        session.add(owner)
        session.flush()
        job = Job(id=uuid.uuid4(), tenant_id=tenant.id, owner_id=owner.id, source_id="1",
                  tool_id="cat1", state="running", runner="gcp_batch", created_at=START, updated_at=START)
        session.add(job)
        session.flush()
        session.add(IngestionState(id=uuid.uuid4(), tenant_id=tenant.id, source="gcp_batch",
                                   status="ok", last_success_at=START + timedelta(hours=1)))
        resource = ResourceLifetime(id=uuid.uuid4(), tenant_id=tenant.id, provider="gcp",
                                    resource_key="test-vm", resource_uid="1", region="test", project="test-project", zone="test-a",
                                    machine_type="test-vm", purchase_model="on_demand",
                                    capacity_relationship=CapacityRelationship.dedicated,
                                    observed_start=START, timing_method="provider_billable",
                                    facts={"observed_at": (START + timedelta(hours=1)).isoformat()})
        session.add(resource)
        price_id = uuid.uuid4()
        session.add(PriceVersion(id=price_id, catalog_id=str(uuid.uuid4()), provider="gcp",
                                 region="test", machine_type="test-vm", purchase_model="on_demand",
                                 currency="USD", hourly_rate=Decimal("2"), observed_at=START,
                                 effective_from=START, provenance={}))
        session.flush()
        for index, outcome in enumerate(("failed", "running")):
            attempt = ExecutionAttempt(id=uuid.uuid4(), job_id=job.id, source_attempt_id=str(index),
                                       runner="gcp_batch", outcome=outcome, external_id="test-batch")
            session.add(attempt)
            session.flush()
            session.add(LifetimeAttempt(lifetime_id=resource.id, attempt_id=attempt.id))
        session.flush()
        yield session, tenant, owner, job, resource
        session.rollback()
        session.execute(delete(Tenant).where(Tenant.id == tenant.id))
        session.execute(delete(PriceVersion).where(PriceVersion.id == price_id))
        session.commit()


def test_active_accrual_deduplicates_retries_and_reconciles_when_closed(spend_source):
    session, tenant, owner, job, resource = spend_source
    snapshot = batch_spend(session, tenant.id, owner.id)
    assert snapshot.amount == Decimal("2")
    assert snapshot.hourly_rate == Decimal("2")
    assert snapshot.coverage_start == START
    assert snapshot.data_age(START + timedelta(hours=2)) == Decimal("3600")
    assert resource.observed_end is None
    resource.observed_end = START + timedelta(hours=1)
    job.state = "error"
    session.flush()
    # The collector commits closed facts with their recalculated cost lines.
    calculate_tenant(session, tenant.id)
    closed = batch_spend(session, tenant.id, owner.id)
    line = session.scalar(select(CostLine).where(CostLine.job_id == job.id, CostLine.basis == "additional"))
    assert closed.amount == line.amount == snapshot.amount
    assert closed.hourly_rate == 0


def test_unpriced_resource_stays_unknown_and_does_not_become_zero(spend_source):
    session, tenant, owner, job, resource = spend_source
    resource.machine_type = "unknown"
    session.flush()
    snapshot = batch_spend(session, tenant.id, owner.id)
    assert snapshot.amount is None
    assert snapshot.incomplete_jobs == 1
    assert snapshot.unpriced_running_resources == 1


def test_missing_vm_observation_is_not_replaced_by_another_targets_success(spend_source):
    session, tenant, owner, job, resource = spend_source
    resource.facts = {}
    session.flush()
    calculate_tenant(session, tenant.id)
    assert batch_spend(session, tenant.id, owner.id).amount is None
    line = session.scalar(select(CostLine).where(CostLine.job_id == job.id, CostLine.basis == "additional"))
    assert line.amount is None


def test_scope_excludes_other_owners_tenants_and_local_work(spend_source):
    session, tenant, owner, job, resource = spend_source
    assert batch_spend(session, uuid.uuid4(), owner.id).amount == 0
    assert batch_spend(session, tenant.id, uuid.uuid4()).amount == 0
    for attempt in job.attempts:
        attempt.runner = "k8s"
    job.runner = "k8s"
    session.flush()
    assert batch_spend(session, tenant.id, owner.id).amount == 0


def test_resource_observation_limits_freshness_even_when_other_targets_advance(spend_source):
    session, tenant, owner, job, resource = spend_source
    resource.facts = {"observed_at": (START + timedelta(minutes=30)).isoformat()}
    session.flush()
    snapshot = batch_spend(session, tenant.id, owner.id)
    assert snapshot.amount == Decimal("1")
    assert snapshot.observed_at == START + timedelta(minutes=30)


def test_closed_lifetime_awaiting_calculation_is_unknown_not_zero(spend_source):
    session, tenant, owner, job, resource = spend_source
    resource.observed_end = START + timedelta(hours=1)
    session.flush()
    snapshot = batch_spend(session, tenant.id, owner.id)
    assert snapshot.amount is None
    assert snapshot.incomplete_jobs == 1


def test_running_vm_accrues_to_its_own_observation(spend_source):
    session, tenant, owner, job, resource = spend_source
    second = ResourceLifetime(id=uuid.uuid4(), tenant_id=tenant.id, provider="gcp", resource_key="second-vm",
                              resource_uid="2", region="test", project="test-project", zone="test-a",
                              machine_type="test-vm", purchase_model="on_demand",
                              capacity_relationship=CapacityRelationship.dedicated, observed_start=START,
                              timing_method="provider_billable",
                              facts={"observed_at": (START + timedelta(hours=1)).isoformat()})
    session.add(second)
    session.flush()
    session.add(LifetimeAttempt(lifetime_id=second.id, attempt_id=job.attempts[0].id))
    resource.facts = {"observed_at": (START + timedelta(minutes=30)).isoformat()}
    session.flush()
    snapshot = batch_spend(session, tenant.id, owner.id)
    # One stale VM no longer holds the other back to its observation.
    assert snapshot.amount == Decimal("3")
    assert snapshot.observed_at == START + timedelta(minutes=30)
    assert snapshot.hourly_rate == Decimal("4")


def test_running_costs_reconcile_with_reports_at_the_recorded_cutoff(spend_source):
    session, tenant, owner, job, resource = spend_source
    identity = Identity(tenant.id, owner.id, owner.source_id, owner.label, False)
    invocation = Invocation(id=uuid.uuid4(), tenant_id=tenant.id, owner_id=owner.id, source_id="run",
                            workflow_name="Running workflow", state="scheduled", created_at=START)
    session.add(invocation)
    session.flush()
    session.add(InvocationJob(invocation_id=invocation.id, job_id=job.id, step_key="0"))
    resource.facts = {"observed_at": (START + timedelta(hours=1)).isoformat()}
    session.flush()
    calculate_tenant(session, tenant.id)
    snapshot = batch_spend(session, tenant.id, owner.id)
    query = ReportQuery(from_time=START, to_time=START + timedelta(hours=4))
    report = reporting.summary(session, identity, query)
    jobs = reporting.list_jobs(session, identity, query)
    daily = reporting.daily(session, identity, query)
    assert snapshot.amount == Decimal(report["amount"]) == Decimal("2")
    assert Decimal(jobs["items"][0]["amount"]) == snapshot.amount
    assert sum(Decimal(item["amount"]) for item in daily["items"]) == snapshot.amount
    assert report["in_progress_job_count"] == 1
    assert jobs["items"][0]["quality"] == "partial"
    chart = cost_timeline(session, identity, query)
    assert sum(Decimal(bucket["amount"]) for bucket in chart["buckets"]) == snapshot.amount
    run = reporting.invocations(session, identity, query)["items"][0]
    assert Decimal(run["amount"]) == Decimal(run["run_total"]) == snapshot.amount
    exported = list(csv.DictReader(io.StringIO("".join(reporting.export_csv(session, identity, query)))))
    assert Decimal(exported[0]["amount_exact"]) == snapshot.amount

    # A narrower reporting window still slices the recorded amount correctly.
    half = query.model_copy(update={"from_time": START + timedelta(minutes=30)})
    assert Decimal(reporting.summary(session, identity, half)["amount"]) == Decimal("1")

    # Later reads and a source-wide success do not advance this VM's cutoff.
    state = session.scalar(select(IngestionState).where(IngestionState.tenant_id == tenant.id))
    state.last_success_at = START + timedelta(hours=3)
    session.flush()
    calculate_tenant(session, tenant.id)
    assert Decimal(reporting.summary(session, identity, query)["amount"]) == snapshot.amount
    assert batch_spend(session, tenant.id, owner.id).amount == snapshot.amount

    # Fresh observations grow both totals; closing replaces the provisional
    # amount rather than adding it again. Retry links never multiply the VM.
    resource.facts = {"observed_at": (START + timedelta(hours=2)).isoformat()}
    session.flush()
    calculate_tenant(session, tenant.id)
    assert Decimal(reporting.summary(session, identity, query)["amount"]) == Decimal("4")
    assert batch_spend(session, tenant.id, owner.id).amount == Decimal("4")
    resource.observed_end = START + timedelta(hours=2)
    session.flush()
    calculate_tenant(session, tenant.id)
    assert Decimal(reporting.summary(session, identity, query)["amount"]) == Decimal("4")
    assert batch_spend(session, tenant.id, owner.id).amount == Decimal("4")
