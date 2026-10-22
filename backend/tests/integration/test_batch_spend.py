import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rainstone.batch_spend import batch_spend
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import (
    CapacityRelationship,
    CostLine,
    ExecutionAttempt,
    IngestionState,
    Job,
    LifetimeAttempt,
    Owner,
    PriceVersion,
    ResourceLifetime,
    Tenant,
)
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
                                    observed_start=START, timing_method="provider_billable", facts={})
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
