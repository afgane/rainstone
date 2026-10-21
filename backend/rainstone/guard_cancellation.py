"""Galaxy-mediated stops with durable intent and read-only provider verification."""

import time
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from rainstone.adapters.contracts import NormalizedLifetime, ObservationBatch
from rainstone.adapters.gcp_batch import BatchCollector, BatchTarget, _lifecycle_bounds
from rainstone.batch_spend import batch_spend, utcnow
from rainstone.config import Settings
from rainstone.costing import calculate_tenant
from rainstone.galaxy_control import GalaxyControl, GalaxyControlError, retry_delay
from rainstone.ingestion import apply_batch, upsert_lifetime
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


def resources_for(session: Session, row: GuardCancellation) -> list[ResourceLifetime]:
    return list(session.scalars(select(ResourceLifetime).join(LifetimeAttempt).join(
        ExecutionAttempt, ExecutionAttempt.id == LifetimeAttempt.attempt_id,
    ).where(ResourceLifetime.tenant_id == row.tenant_id, ExecutionAttempt.job_id == row.job_id,
            ExecutionAttempt.runner == "gcp_batch", ExecutionAttempt.external_id.in_([
                row.external_id, f"projects/{row.project}/locations/{row.location}/jobs/{row.external_id.rsplit('/', 1)[-1]}",
            ]))).unique())


def preserve(session: Session, row: GuardCancellation, gcp) -> None:
    target = BatchTarget(session.get(Job, row.job_id).source_id, row.external_id.rsplit("/", 1)[-1],
                         row.project, row.location, active=True)
    # Acquisition failures must never prevent the selected cancellation.
    try:
        gcp.deadline = time.monotonic() + 3
        payload = gcp.get_batch_job(row.project, row.location, target.external_id)
        if payload:
            row.evidence = {**row.evidence, "batch_uid": payload.get("uid")}
        observer = BatchCollector(gcp, lambda: [target], budget_seconds=3)
        attempts, gaps = observer._collect_target(target, utcnow())
    except Exception:  # noqa: BLE001 - observation is best effort; control continues
        row.evidence = {**row.evidence, "preservation_incomplete": True}
        return
    finally:
        gcp.deadline = None
    try:
        with session.begin_nested():
            apply_batch(session, row.tenant_id, ObservationBatch(source="guard_evidence", observed_at=utcnow(),
                                                                attempts=tuple(attempts), gaps=tuple(gaps)))
            calculate_tenant(session, row.tenant_id, reason="before guard cancellation")
        row.evidence = {**row.evidence, "preserved_at": utcnow().isoformat()}
    except Exception:  # noqa: BLE001 - roll back observation without losing control intent
        row.evidence = {**row.evidence, "preservation_incomplete": True}


def verify_cleanup(session: Session, row: GuardCancellation, gcp) -> bool:
    now = utcnow()
    job = gcp.get_batch_job(row.project, row.location, row.external_id.rsplit("/", 1)[-1])
    uid = row.evidence.get("batch_uid") or (job or {}).get("uid")
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
    calculate_tenant(session, row.tenant_id, reason="guard cleanup evidence")
    return True


def reconcile_cancellations(session: Session, tenant_id, settings: Settings, client: GalaxyControl, gcp) -> None:
    guard = session.get(SpendGuard, tenant_id)
    if guard is None:
        return
    active = guard.amount is not None and guard.triggered_at and guard.stop_jobs
    snapshot = batch_spend(session, tenant_id, guard.owner_id)
    if guard.enrollment != snapshot.enrollment:
        return
    now = utcnow()
    scan = session.get(GuardControlStatus, tenant_id)
    if scan is None:
        scan = GuardControlStatus(tenant_id=tenant_id, attempts=0)
        session.add(scan)
    if not active:
        scan.error, scan.retry_at, scan.attempts = None, None, 0
    if active and (scan.retry_at is None or scan.retry_at <= now):
        owner = session.get(Owner, guard.owner_id)
        try:
            encoded_owner = client.owner_id(owner.label)
            candidates = client.outstanding_batch_jobs()
        except GalaxyControlError as error:
            scan.attempts += 1
            scan.error = str(error)
            scan.retry_at = now + timedelta(seconds=retry_delay(scan.attempts))
            audit(session, guard, "cancellation_scan_failed", "collector", error=str(error))
            session.commit()
            candidates = []
        else:
            scan.checked_at = now
            scan.error, scan.retry_at, scan.attempts = None, None, 0
        for item in candidates:
            if item.get("job_runner_name") != "gcp_batch" or str(item.get("user_id")) != encoded_owner:
                continue
            external = item.get("external_id")
            if not external:
                continue
            full_name = f"projects/{settings.gcp_project}/locations/{settings.gcp_location}/jobs/{external.rsplit('/', 1)[-1]}"
            matches = list(session.scalars(select(Job).join(ExecutionAttempt).where(
                Job.tenant_id == tenant_id, Job.owner_id == guard.owner_id,
                ExecutionAttempt.runner == "gcp_batch",
                ExecutionAttempt.external_id.in_([external, full_name]),
            )).unique())
            if len(matches) != 1:
                continue
            job = matches[0]
            existing = session.scalar(select(GuardCancellation).where(
                GuardCancellation.tenant_id == tenant_id, GuardCancellation.job_id == job.id,
                GuardCancellation.external_id == external,
            ))
            if existing is None:
                session.add(GuardCancellation(id=uuid.uuid4(), tenant_id=tenant_id, job_id=job.id,
                                               revision=guard.revision, galaxy_id=item["id"], external_id=external,
                                               project=settings.gcp_project, location=settings.gcp_location,
                                               attempts=0, evidence={}))
        session.commit()
    rows = list(session.scalars(select(GuardCancellation).where(
        GuardCancellation.tenant_id == tenant_id,
    ).order_by(GuardCancellation.attempts, GuardCancellation.id)))
    deadline = time.monotonic() + 20
    processed = 0
    for row in rows:
        if row.verified_at and row.cost_reconciled or row.retry_at and row.retry_at > now:
            continue
        if processed >= 5 or time.monotonic() >= deadline:
            break
        processed += 1
        try:
            if row.requested_at is None:
                with session.begin_nested():
                    preserve(session, row, gcp)
                row.requested_at = now
                audit(session, guard, "cancellation_requested", "collector", job_id=str(row.job_id), external_id=row.external_id)
                session.commit()
            # Serialize the destructive call with policy changes and recheck
            # current source/policy after preserving evidence and committing intent.
            current = session.scalar(select(SpendGuard).where(SpendGuard.tenant_id == tenant_id).with_for_update())
            current_snapshot = batch_spend(session, tenant_id, current.owner_id)
            if (not row.verified_at and current.amount is not None and current.triggered_at and current.stop_jobs
                    and current.enrollment == current_snapshot.enrollment):
                client.cancel_job(row.galaxy_id, row.external_id)
            session.commit()
            gcp.deadline = time.monotonic() + 5
            complete = verify_cleanup(session, row, gcp)
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
            session.commit()
        except Exception as error:  # noqa: BLE001 - keep other targets and accounting alive
            session.rollback()
            row = session.get(GuardCancellation, row.id)
            row.attempts += 1
            row.error = str(error) if isinstance(error, GalaxyControlError) else "Batch cleanup could not be verified"
            row.retry_at = utcnow() + timedelta(seconds=retry_delay(row.attempts))
            audit(session, guard, "cancellation_retry", "collector", job_id=str(row.job_id), error=row.error)
            session.commit()
        finally:
            gcp.deadline = None
