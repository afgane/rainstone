import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from rainstone.auth import Identity, current_identity
from rainstone.db import engine
from rainstone.main import app
from rainstone.models import (
    CapacityRelationship,
    ExecutionAttempt,
    GalaxyServerSession,
    Job,
    LifetimeAttempt,
    Owner,
    ResourceLifetime,
    Tenant,
)
from rainstone.server_activity import activity
from sqlalchemy import delete
from sqlalchemy.orm import Session

START = datetime(2026, 10, 1, tzinfo=UTC)
END = START + timedelta(hours=1)


@pytest.fixture()
def scope():
    tenant_id, other_tenant = uuid.uuid4(), uuid.uuid4()
    alice, bob, outside = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session:
        session.add_all([
            Tenant(id=tenant_id, slug=f"activity-{tenant_id}", display_name="Activity", capabilities={}),
            Tenant(id=other_tenant, slug=f"activity-{other_tenant}", display_name="Other", capabilities={}),
        ])
        session.flush()
        session.add_all([
            Owner(id=alice, tenant_id=tenant_id, source_id="alice", label="Alice"),
            Owner(id=bob, tenant_id=tenant_id, source_id="bob", label="Bob"),
            Owner(id=outside, tenant_id=other_tenant, source_id="outside", label="Outside"),
        ])
        session.add(GalaxyServerSession(
            id=uuid.uuid4(), tenant_id=tenant_id, provider="gcp", resource_uid="vm-1",
            name="galaxy", machine_type="t2d-standard-8", state="RUNNING",
            descriptor_source="configured descriptor", session_key="vm-1:start", launch_at=START,
            first_observed_at=START, observed_at=END,
        ))
        session.flush()

        def add_job(source, runner, left, right, *, owner=alice, uid="vm-1", verified=False, state="ok"):
            job_id, attempt_id, lifetime_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            job_tenant = other_tenant if owner == outside else tenant_id
            session.add(Job(
                id=job_id, tenant_id=job_tenant, owner_id=owner, source_id=source,
                tool_id="tool", state=state, runner=runner, created_at=START - timedelta(hours=1), updated_at=END,
            ))
            session.flush()
            session.add(ExecutionAttempt(
                id=attempt_id, job_id=job_id, source_attempt_id="attempt", runner=runner, outcome=state,
                tool_started_at=START + timedelta(minutes=left) if left is not None else None,
                tool_finished_at=START + timedelta(minutes=right) if right is not None else None,
            ))
            session.add(ResourceLifetime(
                id=lifetime_id, tenant_id=job_tenant, provider="gcp", resource_key=source, resource_uid=uid,
                capacity_relationship=CapacityRelationship.existing, facts={"verified_vm_identity": verified},
            ))
            session.flush()
            session.add(LifetimeAttempt(lifetime_id=lifetime_id, attempt_id=attempt_id))

        add_job("local", "local", -10, 10)
        add_job("k8s", "kubernetes", 5, 20, uid="configured-node-alias")
        add_job("batch", "gcp_batch", 6, 9)
        add_job("other-vm", "kubernetes", 15, 16, uid="other-vm", verified=True)
        add_job("bad-clock", "local", 20, 19)
        add_job("missing-finish", "local", 1, None)
        add_job("running", "local", 22, None, state="running")
        add_job("bob", "local", 30, 40, owner=bob)
        add_job("outside", "local", 30, 40, owner=outside)
        add_job("missing-start", "local", None, 10)
        session.commit()
    launch = {"launch_at": START.isoformat(), "as_of": END.isoformat(), "resource_uid": "vm-1"}
    yield Identity(tenant_id, alice, "alice", "Alice", False, can_view_infrastructure=True), launch
    with Session(engine) as session:
        session.execute(delete(Tenant).where(Tenant.id.in_((tenant_id, other_tenant))))
        session.commit()


def test_only_visible_server_executions_are_clipped_to_the_session(scope) -> None:
    viewer, launch = scope
    with Session(engine) as session:
        result = activity(session, viewer, launch)
        assert result["job_count"] == 3
        assert [row["source_id"] for row in result["intervals"]] == ["local", "k8s", "running"]
        assert result["intervals"][0]["from"] == START
        assert result["intervals"][-1]["to"] == END
        assert result["intervals"][-1]["running"] is True
        assert activity(session, replace(viewer, is_admin=True), launch)["job_count"] == 4


def test_long_sessions_use_steps_and_dense_sessions_bound_the_response(scope, monkeypatch) -> None:
    from rainstone import server_activity

    viewer, launch = scope
    with Session(engine) as session:
        result = activity(session, viewer, {**launch, "as_of": (START + timedelta(days=8)).isoformat()})
        assert result["kind"] == "steps"
        assert result["intervals"] == []
        assert max(row["count"] for row in result["steps"]) == 2
        monkeypatch.setattr(server_activity, "MAX_STEPS", 2)
        hidden = activity(session, viewer, launch)
        assert hidden["kind"] == "hidden"
        assert hidden["job_count"] == 3
        assert hidden["intervals"] == hidden["steps"] == []


def test_the_activity_response_ignores_report_filters_without_widening_authorization(scope, client, monkeypatch):
    viewer, _ = scope
    monkeypatch.setitem(app.dependency_overrides, current_identity, lambda: viewer)
    response = client.get("/api/infrastructure?search=nothing&owner=bob&from=2020-01-01T00:00:00Z")
    assert response.status_code == 200
    result = response.json()["activity"]
    assert result["job_count"] == 3
    assert result["from"] == START.isoformat().replace("+00:00", "Z")
    assert {row["source_id"] for row in result["intervals"]} == {"local", "k8s", "running"}
    assert result == client.get("/api/infrastructure").json()["activity"]


def test_an_unknown_session_start_has_no_invented_domain(scope) -> None:
    viewer, launch = scope
    with Session(engine) as session:
        assert activity(session, viewer, {**launch, "launch_at": None}) is None
