import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rainstone.api.schemas import JobDetailResponse
from rainstone.auth import Identity
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import (
    CapacityRelationship,
    CostLine,
    ExecutionAttempt,
    Job,
    LifetimeAttempt,
    Owner,
    ResourceLifetime,
    Tenant,
)
from rainstone.report_query import ReportQuery
from rainstone.reporting import export_csv, job_detail, list_jobs, tools
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

START = datetime(2026, 9, 19, 12, tzinfo=UTC)


@pytest.fixture
def observed_job():
    tenant_id, owner_id, job_id, attempt_id, lifetime_id = [uuid.uuid4() for _ in range(5)]
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, slug=f"phases-{tenant_id}", display_name="Phases", capabilities={}))
        session.flush()
        session.add(Owner(id=owner_id, tenant_id=tenant_id, source_id="owner", label="Owner"))
        session.flush()
        session.add(Job(id=job_id, tenant_id=tenant_id, owner_id=owner_id, source_id="1",
                        tool_id="phase-tool", state="ok", runner="gcp_batch",
                        created_at=START, updated_at=START + timedelta(seconds=30)))
        session.flush()
        session.add(ExecutionAttempt(id=attempt_id, job_id=job_id, source_attempt_id="batch-1", runner="gcp_batch",
                                     outcome="ok", tool_started_at=START + timedelta(seconds=5),
                                     tool_finished_at=START + timedelta(seconds=20)))
        session.add(ResourceLifetime(id=lifetime_id, tenant_id=tenant_id, provider="gcp",
                                     resource_key="gce:phase-test", resource_uid="phase-test", region="us-central1",
                                     machine_type="n2-highmem-4", purchase_model="on_demand",
                                     capacity_relationship=CapacityRelationship.dedicated,
                                     timing_method="compute_insert_complete_to_delete_request",
                                     observed_start=START, observed_end=START + timedelta(seconds=30), facts={}))
        session.flush()
        session.add(LifetimeAttempt(lifetime_id=lifetime_id, attempt_id=attempt_id))
        calculate_tenant(session, tenant_id)
        session.commit()
    identity = Identity(tenant_id=tenant_id, owner_id=owner_id, source_id="owner", label="Owner", is_admin=False)
    yield identity, job_id, attempt_id, lifetime_id
    with Session(engine) as session:
        session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        session.commit()


def test_stored_phases_reconcile_exactly_and_are_not_priced_at_report_time(observed_job, monkeypatch):
    from rainstone import costing

    identity, job_id, _, _ = observed_job
    query = ReportQuery()
    def forbidden(*args, **kwargs):
        raise AssertionError("Report tried to price a resource")
    monkeypatch.setattr(costing, "price_windows", forbidden)
    with Session(engine) as session:
        result = job_detail(session, identity, job_id, query)
        assert JobDetailResponse.model_validate(result).full_phase_totals
        [resource] = result["resources"]
        assert result["full_phase_totals"] == result["phase_totals"]
        assert sum(Decimal(phase["amount"]) for phase in resource["phases"]) == Decimal(resource["amount"])
        assert sum(Decimal(phase["amount"]) for phase in result["full_phase_totals"]) == Decimal(result["full_job_amount"])
        line = session.scalar(select(CostLine).where(CostLine.job_id == job_id, CostLine.basis == "additional"))
        assert sum(Decimal(a["amount"]) for a in line.details["allocations"]) == line.amount
        assert result["revision_id"]
        assert resource["amount"] is not None


def test_period_totals_csv_and_full_costs_use_the_same_stored_allocations(observed_job):
    identity, job_id, _, _ = observed_job
    query = ReportQuery(from_time=START + timedelta(seconds=10), to_time=START + timedelta(seconds=15))
    with Session(engine) as session:
        result = job_detail(session, identity, job_id, query)
        assert [phase["phase"] for phase in result["phase_totals"]] == ["execution"]
        assert Decimal(result["phase_totals"][0]["amount"]) == Decimal(result["interval_amount"])
        assert Decimal(result["full_job_amount"]) > Decimal(result["interval_amount"])
        [row] = list_jobs(session, identity, query)["items"]
        assert row["phase_totals"] == result["phase_totals"]
        [exported] = list(csv.DictReader(io.StringIO("".join(export_csv(session, identity, query)))))
        assert Decimal(exported["execution_amount_exact"]) == Decimal(result["interval_amount"])
        assert exported["provisioning_amount_exact"] == ""
        assert exported["execution_complete"] == "True"


def test_tool_overhead_is_cost_weighted_and_excludes_missing_phase_evidence(observed_job):
    identity, job_id, attempt_id, _ = observed_job
    with Session(engine) as session:
        result = tools(session, identity, ReportQuery())["items"][0]
        overhead = result["statistics"]["overhead"]
        assert overhead["sample_count"] == 1
        assert overhead["excluded_count"] == 0
        assert abs(Decimal(overhead["share"]) - Decimal("0.5")) < Decimal("1e-9")
        attempt = session.get(ExecutionAttempt, attempt_id)
        attempt.tool_finished_at = None
        calculate_tenant(session, identity.tenant_id)
        session.commit()
        result = tools(session, identity, ReportQuery())["items"][0]
        assert result["statistics"]["overhead"]["sample_count"] == 0
        assert result["statistics"]["overhead"]["share"] is None
        [phase] = job_detail(session, identity, job_id, ReportQuery())["resources"][0]["phases"]
        assert phase["phase"] == "unattributed"
        assert phase["reason"]


def test_phase_resources_respect_owner_scope(observed_job):
    identity, job_id, _, _ = observed_job
    stranger = Identity(tenant_id=identity.tenant_id, owner_id=uuid.uuid4(), source_id="stranger", label="Stranger", is_admin=False)
    with Session(engine) as session:
        assert job_detail(session, stranger, job_id, ReportQuery()) is None
        assert not list_jobs(session, stranger, ReportQuery())["items"]


def test_persisted_phases_reconcile_across_a_price_change(observed_job):
    from rainstone.models import PriceVersion

    identity, job_id, _, lifetime_id = observed_job
    ids = [uuid.uuid4(), uuid.uuid4()]
    shape = f"phase-test-{uuid.uuid4()}"
    try:
        with Session(engine) as session:
            lifetime = session.get(ResourceLifetime, lifetime_id)
            lifetime.machine_type = shape
            session.add_all([
                PriceVersion(id=identifier, catalog_id=f"test-phases-{identifier}", provider="gcp", region="us-central1",
                             machine_type=shape, purchase_model="on_demand", currency="USD", hourly_rate=rate,
                             observed_at=START, effective_from=effective, provenance={})
                for identifier, rate, effective in [
                    (ids[0], Decimal("0.12"), None), (ids[1], Decimal("0.24"), START + timedelta(seconds=15)),
                ]
            ])
            calculate_tenant(session, identity.tenant_id)
            session.commit()
            result = job_detail(session, identity, job_id, ReportQuery())
            [resource] = result["resources"]
            assert sum(Decimal(phase["amount"]) for phase in resource["phases"]) == Decimal(resource["amount"])
            assert Decimal(resource["amount"]) == Decimal("0.003")
            phases = {phase["phase"]: phase for phase in resource["phases"]}
            assert Decimal(phases["execution"]["charged_seconds"]) == 30
            line = session.scalar(select(CostLine).where(CostLine.job_id == job_id, CostLine.basis == "additional"))
            assert len({a["price_version_id"] for a in line.details["allocations"]}) == 2
    finally:
        with Session(engine) as session:
            session.execute(delete(PriceVersion).where(PriceVersion.id.in_(ids)))
            session.commit()


def test_phase_totals_keep_known_subtotals_explicit_when_another_resource_is_unpriced(observed_job):
    identity, job_id, attempt_id, _ = observed_job
    with Session(engine) as session:
        lifetime_id = uuid.uuid4()
        session.add(ResourceLifetime(id=lifetime_id, tenant_id=identity.tenant_id, provider="gcp",
                                     resource_key="gce:unpriced-phase-test", resource_uid="unpriced-phase-test",
                                     region="us-central1", machine_type="unpriced-test-shape",
                                     purchase_model="on_demand", capacity_relationship=CapacityRelationship.dedicated,
                                     timing_method="compute_insert_complete_to_delete_request",
                                     observed_start=START, observed_end=START + timedelta(seconds=30), facts={}))
        session.flush()
        session.add(LifetimeAttempt(lifetime_id=lifetime_id, attempt_id=attempt_id))
        calculate_tenant(session, identity.tenant_id)
        session.commit()
        result = job_detail(session, identity, job_id, ReportQuery())
        assert len(result["resources"]) == 2
        assert all(phase["resource_count"] == 2 and phase["incomplete_resource_count"] == 1
                   and not phase["complete"] and phase["amount"] is not None
                   for phase in result["full_phase_totals"])
        assert tools(session, identity, ReportQuery())["items"][0]["statistics"]["overhead"]["sample_count"] == 0


def test_an_older_calculation_is_rebuilt_without_new_observations(observed_job):
    from rainstone.models import CostRevision

    identity, job_id, _, _ = observed_job
    with Session(engine) as session:
        revision = session.get(CostRevision, identity.tenant_id)
        previous_id = revision.id
        revision.calculation_version = "phase2b-v2"
        for line in session.scalars(select(CostLine).where(CostLine.job_id == job_id)):
            line.details = {key: value for key, value in line.details.items() if key != "phases"}
        session.commit()
        revision = calculate_tenant(session, identity.tenant_id)
        assert revision.id != previous_id
        session.commit()
        assert job_detail(session, identity, job_id, ReportQuery())["resources"][0]["phases"]


def test_calculated_phases_and_allocations_are_stored_without_recomputation(observed_job):
    from rainstone.costing import applicable_prices, calculate_lifetime

    identity, job_id, attempt_id, lifetime_id = observed_job
    with Session(engine) as session:
        lifetime = session.get(ResourceLifetime, lifetime_id)
        attempt = session.get(ExecutionAttempt, attempt_id)
        prices = applicable_prices(session, provider=lifetime.provider, region=lifetime.region,
                                   machine_type=lifetime.machine_type, purchase_model=lifetime.purchase_model)
        calculated = calculate_lifetime(lifetime, [], prices, attempts=[attempt])
        stored = {line.basis: line for line in session.scalars(select(CostLine).where(CostLine.job_id == job_id))}
        for line in calculated:
            assert stored[line.basis].amount == line.amount
            assert stored[line.basis].details["allocations"] == list(line.allocations)
            assert stored[line.basis].details["phases"] == list(line.phases)
