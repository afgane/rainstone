"""Durable user-selected Batch ceiling and best-effort threshold evaluation."""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from rainstone.batch_spend import BatchSpend, batch_spend, utcnow
from rainstone.config import Settings
from rainstone.models import GuardAudit, GuardNotification, SpendGuard, Tenant


class PolicyConflict(ValueError):
    pass


def margin(snapshot: BatchSpend, settings: Settings, now: datetime) -> Decimal:
    return max(Decimal("0.25"), snapshot.hourly_rate * (
        Decimal(settings.guard_reaction_seconds) + snapshot.data_age(now)
    ) / Decimal("3600"))


def audit(session: Session, guard: SpendGuard, action: str, actor: str, **details) -> None:
    session.add(GuardAudit(id=uuid.uuid4(), tenant_id=guard.tenant_id, revision=guard.revision,
                           occurred_at=utcnow(), actor=actor, action=action,
                           details={"enrollment": guard.enrollment, **jsonable_encoder(details)}))


def evaluate(session: Session, guard: SpendGuard, snapshot: BatchSpend,
             settings: Settings, now: datetime) -> None:
    if guard.amount is None or guard.enrollment != snapshot.enrollment:
        return
    if guard.triggered_at is None and snapshot.amount is not None and (
        snapshot.amount + margin(snapshot, settings, now) >= guard.amount
    ):
        guard.triggered_at = now
        guard.snapshot = jsonable_encoder(snapshot.payload(now))
        audit(session, guard, "triggered", "collector", snapshot=guard.snapshot,
              margin=str(margin(snapshot, settings, now)))


def set_policy(session: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID,
               revision: int, amount: Decimal | None, stop_jobs: bool,
               settings: Settings, actor: str) -> SpendGuard:
    # Lock the tenant even before the first policy exists. A concurrent writer
    # under REPEATABLE READ may get a serialization failure, returned as 409.
    session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    guard = session.get(SpendGuard, tenant_id)
    if (guard.revision if guard else 0) != revision:
        raise PolicyConflict("The limit changed. Reload it before saving again.")
    snapshot = batch_spend(session, tenant_id, owner_id)
    now = utcnow()
    if amount is not None:
        if snapshot.amount is None:
            raise ValueError("Batch cost is not available yet. Try again after collection.")
        if amount <= snapshot.amount:
            raise ValueError(f"Enter a limit greater than the ${snapshot.amount:.2f} already spent on Batch compute.")
        if guard and guard.triggered_at and guard.amount is not None and amount <= guard.amount:
            raise ValueError("Raise the limit or turn it off to resume Batch jobs.")
        if guard and guard.enrollment != snapshot.enrollment:
            raise PolicyConflict("The enrolled Galaxy source changed. Turn off the old limit before setting a new one.")
    if guard is None:
        guard = SpendGuard(tenant_id=tenant_id, owner_id=owner_id, enrollment=snapshot.enrollment,
                           revision=0, updated_at=now, snapshot={})
        session.add(guard)
    guard.owner_id = owner_id
    guard.enrollment = snapshot.enrollment
    guard.revision += 1
    guard.amount = amount
    guard.stop_jobs = stop_jobs if amount is not None else False
    guard.triggered_at = None
    guard.updated_at = now
    audit(session, guard, "disabled" if amount is None else "configured", actor,
          amount=str(amount) if amount is not None else None, stop_jobs=guard.stop_jobs)
    evaluate(session, guard, snapshot, settings, now)
    session.flush()
    return guard


def status(session: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID, settings: Settings) -> dict:
    now = utcnow()
    snapshot = batch_spend(session, tenant_id, owner_id)
    guard = session.get(SpendGuard, tenant_id)
    same_source = guard is None or guard.enrollment == snapshot.enrollment
    return {
        "revision": guard.revision if guard else 0,
        "limit": str(guard.amount) if guard and guard.amount is not None else None,
        "stop_jobs": guard.stop_jobs if guard else False,
        "triggered_at": guard.triggered_at if guard else None,
        "source_changed": not same_source,
        "margin": str(margin(snapshot, settings, now)),
        "snapshot": snapshot.payload(now),
        "stale": snapshot.observed_at is None or snapshot.data_age(now) > settings.guard_stale_seconds,
        "cancellations": [],
        "notifications": [{"condition": row.condition, "error": row.error}
                          for row in session.scalars(select(GuardNotification).where(
                              GuardNotification.tenant_id == tenant_id))],
    }


def evaluate_collected(session: Session, tenant_id: uuid.UUID, settings: Settings) -> SpendGuard | None:
    guard = session.scalar(select(SpendGuard).where(SpendGuard.tenant_id == tenant_id).with_for_update())
    if guard:
        evaluate(session, guard, batch_spend(session, tenant_id, guard.owner_id), settings, utcnow())
    return guard
