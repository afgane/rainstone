"""Deployment-scoped Batch estimates, independent of reporting filters."""

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from rainstone.costing import _active_price, _applicable_prices, calculate_lifetime
from rainstone.models import (
    CapacityRelationship,
    CostLine,
    ExecutionAttempt,
    IngestionState,
    Job,
    LifetimeAttempt,
    ObservationGap,
    ReportGeneration,
    ResourceLifetime,
    ResourceSegment,
    SourceBinding,
)

ZERO = Decimal("0")


@dataclass(frozen=True)
class RunningResource:
    hourly_rate: Decimal
    observed_at: datetime | None


@dataclass(frozen=True)
class BatchSpend:
    amount: Decimal | None
    running: tuple[RunningResource, ...]
    observed_at: datetime | None
    coverage_start: datetime | None
    generation: str
    enrollment: str | None
    incomplete_jobs: int
    unpriced_running_resources: int
    gaps: int

    @property
    def hourly_rate(self) -> Decimal:
        return sum((resource.hourly_rate for resource in self.running), ZERO)

    def data_age(self, now: datetime) -> Decimal:
        return _age(self.observed_at, now)

    def exposure(self, now: datetime, reaction_seconds: int) -> Decimal:
        """Cost each running VM may add before the guard's action takes effect.

        Each VM counts from its own last observation, so one stale VM widens
        the margin by its own rate rather than holding back every other VM.
        """
        return sum((resource.hourly_rate * (Decimal(reaction_seconds) + _age(resource.observed_at, now))
                    / Decimal("3600") for resource in self.running), ZERO)

    def payload(self, now: datetime) -> dict:
        return {
            "amount": str(self.amount) if self.amount is not None else None,
            "hourly_rate": str(self.hourly_rate), "observed_at": self.observed_at,
            "coverage_start": self.coverage_start, "generation": self.generation,
            "enrollment": self.enrollment, "data_age_seconds": str(self.data_age(now)),
            "incomplete_jobs": self.incomplete_jobs,
            "unpriced_running_resources": self.unpriced_running_resources, "gaps": self.gaps,
        }


def _age(observed_at: datetime | None, now: datetime) -> Decimal:
    return Decimal(str(max(0, (now - observed_at).total_seconds()))) if observed_at else ZERO


def enrollment(session: Session, tenant_id: uuid.UUID) -> str | None:
    binding = session.scalar(select(SourceBinding).where(SourceBinding.tenant_id == tenant_id))
    return str(binding.enrollment_uuid) if binding else None


def batch_spend(session: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> BatchSpend:
    """Price each attributable VM once, through its last observation, not now.

    Closed lifetimes use the stored cost lines, so the total reconciles with
    reports and stays cheap on a long history. Only running VMs are priced
    here. An observation never advances because a browser or evaluator reads
    it; during acquisition failures only the guard's margin grows.
    """
    owned = and_(Job.tenant_id == tenant_id, Job.owner_id == owner_id)
    batch_attempt = and_(ExecutionAttempt.job_id == Job.id, ExecutionAttempt.runner == "gcp_batch")
    created = dict(session.execute(select(Job.id, Job.created_at).where(
        owned, or_(Job.runner == "gcp_batch", exists().where(batch_attempt)),
    )).all())
    batch_jobs = set(created)
    chargeable = (select(LifetimeAttempt.lifetime_id)
                  .join(ExecutionAttempt, ExecutionAttempt.id == LifetimeAttempt.attempt_id)
                  .join(Job, Job.id == ExecutionAttempt.job_id)
                  .where(owned, ExecutionAttempt.runner == "gcp_batch"))
    links = session.execute(
        select(ResourceLifetime.id, ResourceLifetime.observed_end.is_(None), Job.id)
        .join(LifetimeAttempt, LifetimeAttempt.lifetime_id == ResourceLifetime.id)
        .join(ExecutionAttempt, ExecutionAttempt.id == LifetimeAttempt.attempt_id)
        .join(Job, Job.id == ExecutionAttempt.job_id)
        .where(owned, ExecutionAttempt.runner == "gcp_batch", ResourceLifetime.tenant_id == tenant_id,
               ResourceLifetime.provider == "gcp",
               ResourceLifetime.capacity_relationship == CapacityRelationship.dedicated)
    ).all()
    jobs_of: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    active_ids: set[uuid.UUID] = set()
    for lifetime_id, active, job_id in links:
        jobs_of[lifetime_id].add(job_id)
        if active:
            active_ids.add(lifetime_id)
    incomplete = batch_jobs - {job_id for jobs in jobs_of.values() for job_id in jobs}
    total, priced = ZERO, 0

    closed_ids = set(jobs_of) - active_ids
    lines: dict[uuid.UUID, list[Decimal | None]] = defaultdict(list)
    if closed_ids:
        for lifetime_id, amount in session.execute(
            select(CostLine.lifetime_id, CostLine.amount)
            .join(Job, Job.id == CostLine.job_id)
            .join(ResourceLifetime, ResourceLifetime.id == CostLine.lifetime_id)
            .where(owned, CostLine.basis == "additional", CostLine.lifetime_id.in_(chargeable),
                   ResourceLifetime.observed_end.is_not(None), ResourceLifetime.tenant_id == tenant_id)
        ):
            if lifetime_id in closed_ids:
                lines[lifetime_id].append(amount)
    for lifetime_id in closed_ids:
        amounts = lines.get(lifetime_id)
        # A missing line means the calculation has not caught up; unknown.
        if not amounts or any(amount is None for amount in amounts):
            incomplete |= jobs_of[lifetime_id]
        else:
            total += sum(amounts, ZERO)
            priced += 1

    state = session.scalar(select(IngestionState).where(
        IngestionState.tenant_id == tenant_id, IngestionState.source == "gcp_batch",
    ))
    fallback = state.last_success_at if state else None
    observations = [fallback] if fallback else []
    running: list[RunningResource] = []
    unpriced = 0
    active = list(session.scalars(select(ResourceLifetime).where(ResourceLifetime.id.in_(active_ids)))) \
        if active_ids else []
    segments_of: dict[uuid.UUID, list[ResourceSegment]] = defaultdict(list)
    if active:
        for segment in session.scalars(select(ResourceSegment).where(ResourceSegment.lifetime_id.in_(active_ids))):
            segments_of[segment.lifetime_id].append(segment)
    for resource in active:
        recorded = resource.facts.get("observed_at")
        observed = datetime.fromisoformat(recorded) if recorded else fallback
        if observed:
            observations.append(observed)
        prices = _applicable_prices(session, resource)
        price = _active_price(prices, observed) if observed else None
        if price:
            running.append(RunningResource(price.hourly_rate, observed))
        else:
            unpriced += 1
        # A shallow pricing view keeps provisional endpoints out of source facts.
        view = SimpleNamespace(**{column.name: getattr(resource, column.name)
                                  for column in ResourceLifetime.__table__.columns})
        segments = segments_of[resource.id]
        if observed:
            view.observed_end = observed
            segments = [SimpleNamespace(observed_start=segment.observed_start,
                                        observed_end=segment.observed_end or observed) for segment in segments]
        line = calculate_lifetime(view, segments, prices)[0]
        if line.amount is None:
            incomplete |= jobs_of[resource.id]
        else:
            total += line.amount
            priced += 1

    cutoff = min(observations) if observations else None
    marker = session.get(ReportGeneration, tenant_id)
    rate = sum((resource.hourly_rate for resource in running), ZERO)
    digest = hashlib.sha256(f"{marker.generation if marker else 0}:{cutoff}:{total}:{rate}".encode()).hexdigest()
    starts = [start for start in created.values() if start]
    if jobs_of:
        first = session.scalar(select(func.min(ResourceLifetime.observed_start)).where(
            ResourceLifetime.id.in_(chargeable), ResourceLifetime.tenant_id == tenant_id,
            ResourceLifetime.provider == "gcp",
            ResourceLifetime.capacity_relationship == CapacityRelationship.dedicated,
        ))
        if first:
            starts.append(first)
    gaps = session.scalar(select(func.count(ObservationGap.id)).where(
        ObservationGap.tenant_id == tenant_id, ObservationGap.source == "gcp_batch",
    ))
    return BatchSpend(
        amount=total if priced or not batch_jobs else None, running=tuple(running),
        observed_at=cutoff, coverage_start=min(starts) if starts else None,
        generation=digest, enrollment=enrollment(session, tenant_id),
        incomplete_jobs=len(incomplete), unpriced_running_resources=unpriced, gaps=gaps or 0,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
