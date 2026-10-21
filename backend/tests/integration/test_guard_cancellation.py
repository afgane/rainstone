# ruff: noqa: F811
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

from rainstone.batch_spend import batch_spend
from rainstone.collector import batch_targets
from rainstone.config import Settings
from rainstone.galaxy_control import GalaxyControlError
from rainstone.guard_cancellation import reconcile_cancellations
from rainstone.models import GuardCancellation
from rainstone.spend_guard import set_policy
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
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
    galaxy.cancel_job.assert_called_once_with("encoded-job", "test-batch")
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    assert row.requested_at is not None and row.verified_at is not None
    assert row.cost_reconciled
    assert batch_spend(session, tenant.id, owner.id).amount == Decimal("2")
    session.expire_all()
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
    assert galaxy.cancel_job.call_count == 1


def test_partial_failure_retries_after_restart_and_waits_for_vm_deletion(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    galaxy, gcp = clients(spend_source)
    galaxy.cancel_job.side_effect = GalaxyControlError("Galaxy returned HTTP 503")
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
    row = session.scalar(select(GuardCancellation).where(GuardCancellation.tenant_id == tenant.id))
    assert row.error == "Galaxy returned HTTP 503"
    assert row.verified_at is None
    session.expire_all()
    row.retry_at = None
    session.commit()
    galaxy.cancel_job.side_effect = None
    gcp.list_batch_instances.return_value = [{"id": "still-running"}]
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
    assert row.verified_at is None
    assert row.error == "Waiting for Batch VM cleanup"
    row.retry_at = None
    session.commit()
    gcp.list_batch_instances.return_value = []
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
    assert row.verified_at is not None


def test_verified_cancellation_does_not_poll_expected_deleted_batch_record(spend_source):
    session, tenant, owner, job, resource = spend_source
    settings = configure(spend_source)
    assert batch_targets(session, tenant.id, settings)
    galaxy, gcp = clients(spend_source)
    reconcile_cancellations(session, tenant.id, settings, galaxy, gcp)
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
