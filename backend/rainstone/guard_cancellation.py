"""Galaxy-mediated stops with durable intent and read-only provider verification.

Each pass sends every pending stop before checking any cleanup, so one slow
verification never delays stopping the remaining VMs. Batch records are
not exported before stopping: collection has observed the running jobs, and
Compute lifecycle evidence still bounds each VM after Galaxy deletes them.
"""

import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rainstone.adapters.contracts import NormalizedLifetime
from rainstone.adapters.gcp_batch import _lifecycle_bounds
from rainstone.batch_spend import BatchSpend, enrollment, utcnow
from rainstone.config import Settings
from rainstone.costing import calculate_tenant
from rainstone.galaxy_control import GalaxyControl, GalaxyControlError, retry_delay
from rainstone.ingestion import upsert_lifetime
from rainstone.models import (
    ExecutionAttempt,
    GuardCancellation,
    GuardControlStatus,
    Job,
    LifetimeAttempt,
    Owner,
    ResourceLifetime,
    SpendGuard,
)
from rainstone.spend_guard import audit

PAGE_SIZE = 100


def resources_for(session: Session, row: GuardCancellation) -> list[ResourceLifetime]:
    return list(session.scalars(select(ResourceLifetime).join(LifetimeAttempt).join(
        ExecutionAttempt, ExecutionAttempt.id == LifetimeAttempt.attempt_id,
    ).where(ResourceLifetime.tenant_id == row.tenant_id, ExecutionAttempt.job_id == row.job_id,
            ExecutionAttempt.runner == "gcp_batch", ExecutionAttempt.external_id.in_([
                row.external_id, f"projects/{row.project}/locations/{row.location}/jobs/{row.external_id.rsplit('/', 1)[-1]}",
            ]))).unique())


def verify_cleanup(session: Session, row: GuardCancellation, gcp) -> bool:
    """Record final VM evidence once cleanup is complete; the caller recalculates."""
    now = utcnow()
    job = gcp.get_batch_job(row.project, row.location, row.external_id.rsplit("/", 1)[-1])
    if job and job.get("uid") and not row.evidence.get("batch_uid"):
        row.evidence = {**row.evidence, "batch_uid": job["uid"]}
    uid = row.evidence.get("batch_uid")
    # Even a deleted job can leave VMs cleaning up. Provider labels also find
    # VMs that were still provisioning when the last task observation ran.
    instances = gcp.list_batch_instances(row.project, row.external_id.rsplit("/", 1)[-1], uid)
    terminal = (job or {}).get("status", {}).get("state") in {"SUCCEEDED", "FAILED", "CANCELLED"}
    if (job is not None and not terminal) or instances:
        return False
    resources = resources_for(session, row)
    for resource in resources:
        if not resource.zone or gcp.get_instance(row.project, resource.zone, resource.resource_uid) is not None:
            return False
    reconciled = True
    for resource in resources:
        end_method = resource.facts.get("observed_end_timing_method", resource.timing_method)
        if resource.observed_end and end_method in {"provider_billable", "compute_instance_timestamps", "compute_insert_complete_to_delete_request"}:
            continue
        bounds = {}
        try:
            bounds = _lifecycle_bounds(gcp.instance_lifecycle_entries(
                row.project, resource.resource_uid, after=resource.observed_start - timedelta(hours=1)
                if resource.observed_start else None, before=now + timedelta(minutes=1),
            ))
        except Exception:  # noqa: BLE001 - verified absence still bounds the estimate
            pass
        actual_end = bounds.get("delete_requested")
        reconciled &= actual_end is not None
        if resource.observed_end and not actual_end:
            continue
        end = actual_end or now
        normalized = NormalizedLifetime(**{name: getattr(resource, name) for name in (
            "provider", "resource_key", "resource_uid", "capacity_relationship", "project", "zone", "region",
            "machine_type", "purchase_model", "observed_start", "requested_vcpu", "requested_memory_mib",
        )}, observed_end=end, timing_method="compute_insert_complete_to_delete_request" if actual_end else "compute_absence_after_cancellation",
            facts={"observed_end_upper_bound": actual_end is None, "cleanup_observed_at": now.isoformat()})
        upsert_lifetime(session, row.tenant_id, normalized)
    row.cost_reconciled = reconciled
    return True


def stopping(session: Session, guard: SpendGuard) -> bool:
    return bool(guard.amount is not None and guard.triggered_at and guard.stop_jobs
                and guard.enrollment == enrollment(session, guard.tenant_id))


def scan(session: Session, guard: SpendGuard, settings: Settings, client: GalaxyControl,
         deadline: float) -> None:
    """Record every outstanding Batch job of this deployment for the current revision."""
    owner = session.get(Owner, guard.owner_id)
    encoded_owner = client.owner_id(owner.label)
    offset = 0
    while time.monotonic() < deadline:
        page = client.outstanding_batch_jobs(offset, PAGE_SIZE)
        for item in page:
            record(session, guard, settings, item, encoded_owner)
        if len(page) < PAGE_SIZE:
            return
        offset += PAGE_SIZE


def record(session: Session, guard: SpendGuard, settings: Settings, item: dict, encoded_owner: str) -> None:
    if item.get("job_runner_name") != "gcp_batch" or str(item.get("user_id")) != encoded_owner:
        return
    external = item.get("external_id")
    if not external:
        return
    full_name = f"projects/{settings.gcp_project}/locations/{settings.gcp_location}/jobs/{external.rsplit('/', 1)[-1]}"
    matches = list(session.scalars(select(Job).join(ExecutionAttempt).where(
        Job.tenant_id == guard.tenant_id, Job.owner_id == guard.owner_id,
        ExecutionAttempt.runner == "gcp_batch",
        ExecutionAttempt.external_id.in_([external, full_name]),
    )).unique())
    if len(matches) != 1:
        return
    job = matches[0]
    existing = session.scalar(select(GuardCancellation).where(
        GuardCancellation.tenant_id == guard.tenant_id, GuardCancellation.job_id == job.id,
        GuardCancellation.external_id == external,
    ))
    if existing is None:
        session.add(GuardCancellation(id=uuid.uuid4(), tenant_id=guard.tenant_id, job_id=job.id,
                                      revision=guard.revision, galaxy_id=item["id"], external_id=external,
                                      project=settings.gcp_project, location=settings.gcp_location,
                                      attempts=0, evidence={}))
    elif existing.requested_at is None and existing.revision != guard.revision:
        # Left unsent when an earlier trigger was resumed; adopt it.
        existing.revision, existing.galaxy_id = guard.revision, item["id"]
        existing.error, existing.retry_at, existing.attempts = None, None, 0


def send_stops(session: Session, guard: SpendGuard, client: GalaxyControl, now: datetime, deadline: float) -> None:
    pending = list(session.scalars(select(GuardCancellation).where(
        GuardCancellation.tenant_id == guard.tenant_id, GuardCancellation.revision == guard.revision,
        GuardCancellation.verified_at.is_(None),
    ).order_by(GuardCancellation.attempts, GuardCancellation.id)))
    pending = [row for row in pending if not row.evidence.get("stop_sent_at")
               and not (row.retry_at and row.retry_at > now)]
    for row in pending:
        if row.requested_at is None:
            row.requested_at = now
            audit(session, guard, "cancellation_requested", "collector",
                  job_id=str(row.job_id), external_id=row.external_id)
    # Intent is durable before any destructive call.
    session.commit()
    for row in pending:
        if time.monotonic() >= deadline:
            return
        # Serialize each destructive call with policy changes.
        current = session.scalar(select(SpendGuard).where(SpendGuard.tenant_id == guard.tenant_id).with_for_update())
        if not stopping(session, current) or current.revision != row.revision:
            session.commit()
            return
        try:
            sent = client.cancel_job(row.galaxy_id, row.external_id)
            row.evidence = {**row.evidence, "stop_sent_at": utcnow().isoformat(),
                            **({} if sent else {"stop_not_needed": True})}
            row.error, row.retry_at = None, None
        except GalaxyControlError as error:
            row.attempts += 1
            row.error = str(error)
            row.retry_at = utcnow() + timedelta(seconds=retry_delay(row.attempts))
            audit(session, guard, "cancellation_retry", "collector", job_id=str(row.job_id), error=row.error)
        session.commit()


def verify(session: Session, guard: SpendGuard, gcp, now: datetime, deadline: float) -> None:
    rows = list(session.scalars(select(GuardCancellation).where(
        GuardCancellation.tenant_id == guard.tenant_id, GuardCancellation.requested_at.is_not(None),
    ).order_by(GuardCancellation.attempts, GuardCancellation.id)))
    rows = [row for row in rows if row.evidence.get("stop_sent_at")
            and not (row.verified_at and row.cost_reconciled)
            and not (row.retry_at and row.retry_at > now)]
    checked = False
    for row in rows:
        if time.monotonic() >= deadline:
            break
        try:
            gcp.deadline = min(deadline, time.monotonic() + 5)
            with session.begin_nested():
                complete = verify_cleanup(session, row, gcp)
            checked = True
            if complete:
                if row.verified_at is None:
                    row.verified_at = utcnow()
                    audit(session, guard, "cleanup_verified", "collector", job_id=str(row.job_id))
                row.error = None
                row.retry_at = utcnow() + timedelta(seconds=900) if not row.cost_reconciled else None
            else:
                row.error = "Waiting for Batch VM cleanup"
                row.retry_at = utcnow() + timedelta(seconds=retry_delay(row.attempts + 1))
            row.attempts += 1
        except Exception:  # noqa: BLE001 - keep other targets and accounting alive
            row.attempts += 1
            row.error = "Batch cleanup could not be verified"
            row.retry_at = utcnow() + timedelta(seconds=retry_delay(row.attempts))
            audit(session, guard, "cancellation_retry", "collector", job_id=str(row.job_id), error=row.error)
        finally:
            gcp.deadline = None
    if checked:
        calculate_tenant(session, guard.tenant_id, reason="guard cleanup evidence")
    session.commit()


def reconcile_cancellations(session: Session, guard: SpendGuard, snapshot: BatchSpend, settings: Settings,
                            client: GalaxyControl, gcp, *, deadline: float | None = None) -> None:
    if guard.enrollment != snapshot.enrollment:
        return
    deadline = deadline or time.monotonic() + settings.guard_control_budget_seconds
    now = utcnow()
    status = session.get(GuardControlStatus, guard.tenant_id)
    if status is None:
        status = GuardControlStatus(tenant_id=guard.tenant_id, attempts=0)
        session.add(status)
    active = stopping(session, guard)
    if not active:
        status.error, status.retry_at, status.attempts = None, None, 0
    if active and (status.retry_at is None or status.retry_at <= now):
        try:
            scan(session, guard, settings, client, deadline)
            status.checked_at = now
            status.error, status.retry_at, status.attempts = None, None, 0
        except GalaxyControlError as error:
            status.attempts += 1
            status.error = str(error)
            status.retry_at = now + timedelta(seconds=retry_delay(status.attempts))
            audit(session, guard, "cancellation_scan_failed", "collector", error=str(error))
        session.commit()
    if active:
        send_stops(session, guard, client, now, deadline)
    verify(session, guard, gcp, now, deadline)
