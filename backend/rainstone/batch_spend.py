"""Deployment-scoped Batch estimates, independent of reporting filters."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from rainstone.costing import _active_price, _applicable_prices, calculate_lifetime
from rainstone.models import (
    CapacityRelationship,
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
class BatchSpend:
    amount: Decimal | None
    hourly_rate: Decimal
    observed_at: datetime | None
    coverage_start: datetime | None
    generation: str
    enrollment: str | None
    incomplete_jobs: int
    unpriced_running_resources: int
    gaps: int

    def data_age(self, now: datetime) -> Decimal:
        return Decimal(str(max(0, (now - self.observed_at).total_seconds()))) if self.observed_at else ZERO

    def payload(self, now: datetime) -> dict:
        return {
            "amount": str(self.amount) if self.amount is not None else None,
            "hourly_rate": str(self.hourly_rate), "observed_at": self.observed_at,
            "coverage_start": self.coverage_start, "generation": self.generation,
            "enrollment": self.enrollment, "data_age_seconds": str(self.data_age(now)),
            "incomplete_jobs": self.incomplete_jobs,
            "unpriced_running_resources": self.unpriced_running_resources, "gaps": self.gaps,
        }


def batch_spend(session: Session, tenant_id: uuid.UUID, owner_id: uuid.UUID) -> BatchSpend:
    """Price each attributable VM once, through the last observation, not now.

    An observation cutoff never advances because a browser or evaluator reads
    it. During acquisition failures only the guard's data-age margin grows.
    """
    jobs = list(session.scalars(select(Job).where(Job.tenant_id == tenant_id, Job.owner_id == owner_id)))
    job_ids = {job.id for job in jobs}
    attempts = list(session.scalars(select(ExecutionAttempt).where(
        ExecutionAttempt.job_id.in_(job_ids), ExecutionAttempt.runner == "gcp_batch",
    )))
    batch_jobs = {attempt.job_id for attempt in attempts} | {job.id for job in jobs if job.runner == "gcp_batch"}
    links = list(session.execute(select(LifetimeAttempt.lifetime_id, ExecutionAttempt.job_id).join(
        ExecutionAttempt, ExecutionAttempt.id == LifetimeAttempt.attempt_id,
    ).where(ExecutionAttempt.id.in_([attempt.id for attempt in attempts]))))
    resources = list(session.scalars(select(ResourceLifetime).where(
        ResourceLifetime.id.in_({link.lifetime_id for link in links}),
        ResourceLifetime.tenant_id == tenant_id, ResourceLifetime.provider == "gcp",
        ResourceLifetime.capacity_relationship == CapacityRelationship.dedicated,
    )))
    state = session.scalar(select(IngestionState).where(
        IngestionState.tenant_id == tenant_id, IngestionState.source == "gcp_batch",
    ))
    cutoffs = [state.last_success_at] if state and state.last_success_at else []
    for resource in resources:
        observed = resource.facts.get("observed_at")
        if resource.observed_end is None and observed:
            cutoffs.append(datetime.fromisoformat(observed))
    cutoff = min(cutoffs) if cutoffs else None
    total, burn = ZERO, ZERO
    incomplete = batch_jobs - {link.job_id for link in links if link.lifetime_id in {r.id for r in resources}}
    unpriced = 0
    priced = 0
    for resource in resources:
        segments = list(session.scalars(select(ResourceSegment).where(ResourceSegment.lifetime_id == resource.id)))
        active = resource.observed_end is None
        prices = _applicable_prices(session, resource)
        current_price = _active_price(prices, cutoff) if cutoff else None
        if active:
            if current_price:
                burn += current_price.hourly_rate
            else:
                unpriced += 1
        # A shallow pricing view keeps provisional endpoints out of source facts.
        view = SimpleNamespace(**{column.name: getattr(resource, column.name)
                                  for column in ResourceLifetime.__table__.columns})
        if active and cutoff:
            view.observed_end = cutoff
            segments = [SimpleNamespace(observed_start=s.observed_start,
                                        observed_end=s.observed_end or cutoff) for s in segments]
        line = calculate_lifetime(view, segments, prices)[0]
        if line.amount is None:
            incomplete.update(link.job_id for link in links if link.lifetime_id == resource.id)
        else:
            total += line.amount
            priced += 1
    binding = session.scalar(select(SourceBinding).where(SourceBinding.tenant_id == tenant_id))
    marker = session.get(ReportGeneration, tenant_id)
    digest = hashlib.sha256(f"{marker.generation if marker else 0}:{cutoff}:{total}:{burn}".encode()).hexdigest()
    starts = [job.created_at for job in jobs if job.id in batch_jobs]
    starts += [resource.observed_start for resource in resources if resource.observed_start]
    gaps = len(list(session.scalars(select(ObservationGap.id).where(
        ObservationGap.tenant_id == tenant_id, ObservationGap.source == "gcp_batch",
    ))))
    return BatchSpend(
        amount=total if priced or not batch_jobs else None, hourly_rate=burn,
        observed_at=cutoff, coverage_start=min(starts) if starts else None,
        generation=digest, enrollment=str(binding.enrollment_uuid) if binding else None,
        incomplete_jobs=len(incomplete), unpriced_running_resources=unpriced, gaps=gaps,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
