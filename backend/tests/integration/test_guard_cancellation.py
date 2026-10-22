# ruff: noqa: F811
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

from rainstone.batch_spend import batch_spend
from rainstone.collector import batch_targets
from rainstone.config import Settings
from rainstone.galaxy_control import GalaxyControlError
from rainstone.guard_cancellation import reconcile_cancellations
from rainstone.models import ExecutionAttempt, GuardAudit, GuardCancellation, Job, SpendGuard
from rainstone.spend_guard import set_policy, status
from sqlalchemy import select

from .test_batch_spend import START, spend_source  # noqa: F401


def clients(source):
    session, tenant, owner, job, resource = source
    galaxy = Mock()
    galaxy.owner_id.return_value = owner.source_id
    candidate = {"id": "encoded-job", "decoded_job_id": job.source_id, "user_id": owner.source_id,
                 "job_runner_name": "gcp_batch", "external_id": "test-batch"}
    galaxy.outstanding_batch_jobs.return_value = [candidate,
        {**candidate, "user_id": "another-owner", "id": "other-owner"},
        {**candidate, "job_runner_name": "k8s", "id": "local-job"},
        {**candidate, "external_id": "uncollected", "id": "uncollected"}]
    gcp = Mock()
    gcp.get_batch_job.return_value = None
    gcp.list_batch_instances.return_value = []
    gcp.get_instance.return_value = None
    gcp.instance_lifecycle_entries.return_value = [{"method": "v1.compute.instances.delete",
        "timestamp": (START + timedelta(hours=1)).isoformat(), "operation": {"first": True}}]
    return galaxy, gcp


def reconcile(source, settings, galaxy, gcp):
    session, tenant, owner, job, resource = source
    guard = session.get(SpendGuard, tenant.id)
    reconcile_cancellations(session, guard, batch_spend(session, tenant.id, owner.id), settings, galaxy, gcp)


def configure(source):
    session, tenant, owner, job, resource = source
    settings = Settings(guard_enabled=True, gcp_project="test-project", gcp_location="test-region")
    set_policy(session, tenant.id, owner.id, 0, Decimal("2.10"), True, settings, "owner")
    session.commit()
    return settings


def test_cancellation_is_scoped_and_cleanup_reconciles_resource_cost(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    galaxy, gcp = clients(spend_source)
    reconcile(spend_source, settings, galaxy, gcp)
    galaxy.cancel_job.assert_called_once_with("encoded-job", "test-batch")
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    assert row.requested_at is not None and row.verified_at is not None
    assert row.cost_reconciled
    assert batch_spend(session, tenant.id, owner.id).amount == Decimal("2")
    session.expire_all()
    reconcile(spend_source, settings, galaxy, gcp)
    assert galaxy.cancel_job.call_count == 1


def test_partial_failure_retries_after_restart_and_waits_for_vm_deletion(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    galaxy, gcp = clients(spend_source)
    galaxy.cancel_job.side_effect = GalaxyControlError("Galaxy returned HTTP 503")
    reconcile(spend_source, settings, galaxy, gcp)
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    assert row.error == "Galaxy returned HTTP 503"
    assert row.verified_at is None
    session.expire_all()
    row.retry_at = None
    session.commit()
    galaxy.cancel_job.side_effect = None
    gcp.list_batch_instances.return_value = [{"id": "still-running"}]
    reconcile(spend_source, settings, galaxy, gcp)
    assert row.verified_at is None
    assert row.error == "Waiting for Batch VM cleanup"
    row.retry_at = None
    session.commit()
    gcp.list_batch_instances.return_value = []
    reconcile(spend_source, settings, galaxy, gcp)
    assert row.verified_at is not None


def test_verified_cancellation_does_not_poll_expected_deleted_batch_record(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    assert batch_targets(session, tenant.id, settings)
    galaxy, gcp = clients(spend_source)
    reconcile(spend_source, settings, galaxy, gcp)
    assert not batch_targets(session, tenant.id, settings)
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    row.cost_reconciled = False
    session.flush()
    assert batch_targets(session, tenant.id, settings)
    row.cost_reconciled = True
    row.verified_at = None
    session.flush()
    assert batch_targets(session, tenant.id, settings)
    row.verified_at = START
    row.project = "another-project"
    session.flush()
    assert batch_targets(session, tenant.id, settings)


def test_every_stop_is_sent_before_any_cleanup_check(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    galaxy, gcp = clients(spend_source)
    candidates = []
    for index in range(150):
        other = Job(id=uuid.uuid4(), tenant_id=tenant.id, owner_id=owner.id, source_id=f"bulk-{index}",
                    tool_id="cat1", state="running", runner="gcp_batch", created_at=START, updated_at=START)
        session.add(other)
        session.flush()
        session.add(ExecutionAttempt(id=uuid.uuid4(), job_id=other.id, source_attempt_id="0", runner="gcp_batch",
                                     outcome="running", external_id=f"bulk-{index}"))
        candidates.append({"id": f"encoded-{index}", "user_id": owner.source_id,
                           "job_runner_name": "gcp_batch", "external_id": f"bulk-{index}"})
    session.commit()
    galaxy.outstanding_batch_jobs.side_effect = lambda offset, limit: candidates[offset:offset + limit]
    calls = []
    galaxy.cancel_job.side_effect = lambda *args: calls.append("stop") or True
    gcp.get_batch_job.side_effect = lambda *args: calls.append("verify")
    reconcile(spend_source, settings, galaxy, gcp)
    assert calls.count("stop") == 150
    assert "verify" in calls and calls.index("verify") > max(
        index for index, call in enumerate(calls) if call == "stop")


def test_resuming_abandons_stops_that_were_never_sent(spend_source, monkeypatch):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    session.add(GuardCancellation(id=uuid.uuid4(), tenant_id=tenant.id, job_id=job.id, revision=1,
                                  galaxy_id="encoded-job", external_id="test-batch", project="test-project",
                                  location="test-region", attempts=0, evidence={}))
    # Keep the fixture's observation fresh so raising the limit resumes.
    monkeypatch.setattr("rainstone.spend_guard.utcnow", lambda: START + timedelta(hours=1))
    set_policy(session, tenant.id, owner.id, 1, Decimal("100"), True, settings, "owner")
    session.commit()
    galaxy, gcp = clients(spend_source)
    reconcile(spend_source, settings, galaxy, gcp)
    galaxy.cancel_job.assert_not_called()
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    assert row.requested_at is None and row.error is None
    assert not session.scalar(select(GuardAudit).where(GuardAudit.tenant_id == tenant.id,
                                                       GuardAudit.action == "cancellation_requested"))
    assert status(session, tenant.id, owner.id, settings)["cancellations"] == []
