import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from rainstone.models import (
    CapacityRelationship,
    CostLine,
    CostRevision,
    DeploymentPolicy,
    ExecutionAttempt,
    GalaxyServerSession,
    Job,
    LifetimeAttempt,
    PriceVersion,
    Quality,
    ReportGeneration,
    ResourceLifetime,
    ResourceSegment,
)

CALCULATION_VERSION = "phase2b-v2"
SERVER_CALCULATION_VERSION = "galaxy-server-v1"
MINIMUM_BILLED_SECONDS = Decimal("60")


@dataclass(frozen=True)
class CalculatedLine:
    basis: str
    amount: Decimal | None
    quality: Quality
    reason: str
    billed_seconds: Decimal | None = None
    allocations: tuple[dict, ...] = ()


def _unavailable(reason: str, quality: Quality = Quality.partial) -> list[CalculatedLine]:
    return [
        CalculatedLine("additional", None, quality, reason),
        CalculatedLine("allocated", None, quality, reason),
    ]


def _windows(
    lifetime: ResourceLifetime, segments: Sequence[ResourceSegment]
) -> list[tuple[datetime, datetime]]:
    """Positive-duration accounting windows for one lifetime."""
    pairs: list[tuple[datetime, datetime]] = []
    for segment in segments:
        if segment.observed_start and segment.observed_end:
            pairs.append((segment.observed_start, segment.observed_end))
    if not pairs and lifetime.observed_start and lifetime.observed_end:
        pairs.append((lifetime.observed_start, lifetime.observed_end))
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(pairs):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _active_price(prices: Sequence[PriceVersion], at: datetime) -> PriceVersion | None:
    applicable = [
        price for price in prices if price.effective_from is None or price.effective_from <= at
    ]
    if not applicable:
        return None
    return max(
        applicable, key=lambda price: price.effective_from or datetime.min.replace(tzinfo=UTC)
    )


def _observed_seconds(windows: Sequence[tuple[datetime, datetime]]) -> Decimal:
    return sum(
        (Decimal(str((end - start).total_seconds())) for start, end in windows), Decimal("0")
    )


@dataclass(frozen=True)
class PricedWindows:
    """Priced time, split wherever an applicable price takes effect.

    `amount` covers only the priced parts. Time before the earliest applicable
    price is listed in `uncovered` and contributes nothing, because a later
    price is never applied to earlier time.
    """

    amount: Decimal
    observed_seconds: Decimal
    billed_seconds: Decimal
    allocations: tuple[dict, ...]
    uncovered: tuple[tuple[datetime, datetime], ...]
    earliest_price: datetime | None


def price_windows(
    windows: Sequence[tuple[datetime, datetime]], prices: Sequence[PriceVersion]
) -> PricedWindows:
    """Price positive-duration windows that are charged together.

    The provider minimum applies once to all of them, and its uplift is
    distributed proportionally across the observed time.
    """
    observed = _observed_seconds(windows)
    billed_seconds = max(MINIMUM_BILLED_SECONDS, observed)
    allocations: list[dict] = []
    uncovered: list[tuple[datetime, datetime]] = []
    amount = Decimal("0")
    for window_start, window_end in windows:
        boundaries = sorted(
            {
                value.effective_from
                for value in prices
                if value.effective_from and window_start < value.effective_from < window_end
            }
        )
        points = [window_start, *boundaries, window_end]
        for start, end in zip(points, points[1:], strict=False):
            active = _active_price(prices, start)
            if active is None:
                uncovered.append((start, end))
                continue
            segment_seconds = Decimal(str((end - start).total_seconds()))
            charged_seconds = segment_seconds * billed_seconds / observed
            segment_amount = charged_seconds / Decimal("3600") * active.hourly_rate
            amount += segment_amount
            allocations.append(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "observed_seconds": str(segment_seconds),
                    "charged_seconds": str(charged_seconds),
                    "hourly_rate": str(active.hourly_rate),
                    "amount": str(segment_amount),
                    "price_version_id": str(active.id) if active.id else None,
                }
            )
    return PricedWindows(
        amount=amount,
        observed_seconds=observed,
        billed_seconds=billed_seconds,
        allocations=tuple(allocations),
        uncovered=tuple(uncovered),
        earliest_price=min(
            (value.effective_from for value in prices if value.effective_from), default=None
        ),
    )


def calculate_lifetime(
    lifetime: ResourceLifetime,
    segments: Sequence[ResourceSegment],
    price: PriceVersion | Sequence[PriceVersion] | None,
    *,
    shared_job_count: int = 1,
) -> list[CalculatedLine]:
    """Price one chargeable resource lifetime once per basis.

    The provider minimum applies to the lifetime, not to each attempt or each
    daily bucket, and its uplift is distributed proportionally across the
    observed positive-duration windows.
    """
    relationship = lifetime.capacity_relationship
    if relationship == CapacityRelationship.existing:
        return [
            CalculatedLine(
                "additional",
                Decimal("0"),
                Quality.known_zero,
                "Uses declared baseline capacity under the unchanged size and uptime assumption.",
            ),
            CalculatedLine(
                "allocated",
                None,
                Quality.unpriced,
                "Allocated cost is unavailable because this catalog has no valid baseline allocation policy.",
            ),
        ]
    if relationship == CapacityRelationship.unknown:
        return [
            CalculatedLine(
                "additional", None, Quality.partial, "Execution resource relationship is unknown."
            ),
            CalculatedLine("allocated", None, Quality.partial, "Resource allocation evidence is incomplete."),
        ]
    if shared_job_count > 1:
        return _unavailable(
            "More than one Galaxy job used this resource; an explicit allocation policy and "
            "occupancy coverage are required before charging it.",
        )
    windows = _windows(lifetime, segments)
    if not windows:
        return _unavailable("Resource lifetime is incomplete.")
    prices = list(price) if isinstance(price, Sequence) else ([price] if price is not None else [])
    if not prices:
        return _unavailable("No applicable machine price was found.", Quality.unpriced)
    if _observed_seconds(windows) <= 0:
        return _unavailable("Resource lifetime is not positive.")
    priced = price_windows(windows, prices)
    if priced.uncovered:
        return _unavailable(
            "No published price covers this machine and region when it ran: the "
            f"earliest takes effect {priced.earliest_price.isoformat()}, and a later price is "
            "never applied to earlier work.",
            Quality.unpriced,
        )
    amount, billed_seconds, allocations = priced.amount, priced.billed_seconds, priced.allocations
    quality = Quality.complete if lifetime.timing_method == "provider_billable" else Quality.approximate
    reason = (
        "Dedicated VM compute from provider billable lifetime."
        if quality == Quality.complete
        else "Dedicated VM compute from observed lifecycle proxy; excludes disk, network, "
        "discounts, credits, and taxes."
    )
    return [
        CalculatedLine("additional", amount, quality, reason, billed_seconds, allocations),
        CalculatedLine("allocated", amount, quality, reason, billed_seconds, allocations),
    ]


STOPPED_SERVER_STATES = {"STOPPED", "SUSPENDED", "TERMINATED"}


@dataclass(frozen=True)
class ServerSessionCost:
    """The Galaxy server's hourly rate and its compute since the current launch.

    The rate can be known when the total is not. `known_subtotal` is set only
    when part of the session is priced and part is not.
    """

    rate: PriceVersion | None
    rate_unavailable_reason: str | None
    cutoff: datetime | None
    completeness: str
    total: Decimal | None = None
    known_subtotal: Decimal | None = None
    unavailable_reason: str | None = None
    elapsed_seconds: Decimal | None = None
    billed_seconds: Decimal | None = None
    allocations: tuple[dict, ...] = ()


def _shape_label(server: GalaxyServerSession) -> str:
    return (
        f"{server.machine_type or 'an unknown machine type'} "
        f"({server.purchase_model or 'unknown purchase model'}) in "
        f"{server.region or 'an unknown region'}"
    )


def _server_rate(
    server: GalaxyServerSession, prices: Sequence[PriceVersion], at: datetime
) -> tuple[PriceVersion | None, str | None]:
    if server.shape_conflict:
        return None, f"The server's shape is uncertain: {server.shape_conflict}."
    if not (server.machine_type and server.purchase_model and server.region):
        return None, f"The server is {_shape_label(server)}, which cannot be priced."
    if not prices:
        return None, f"The price catalog has no rate for {_shape_label(server)}."
    active = _active_price(prices, at)
    if active is None:
        earliest = min(value.effective_from for value in prices if value.effective_from)
        return None, (
            f"The earliest published rate for {_shape_label(server)} takes effect "
            f"{earliest.isoformat()}."
        )
    return active, None


def calculate_server_session(
    server: GalaxyServerSession, prices: Sequence[PriceVersion]
) -> ServerSessionCost:
    """Price `[launch_at, cutoff]` for the current session only.

    The cutoff is the last successful observation, or the provider's stop time
    once the session has ended, so the total never accrues past what was
    observed. Earlier sessions are not part of it, and no job's baseline
    occupancy is added to it.
    """
    cutoff = server.ended_at or server.observed_at
    rate, rate_reason = _server_rate(server, prices, cutoff)

    def unavailable(reason: str) -> ServerSessionCost:
        return ServerSessionCost(
            rate=rate, rate_unavailable_reason=rate_reason, cutoff=cutoff,
            completeness="unavailable", unavailable_reason=reason,
        )

    if server.launch_at is None:
        return unavailable(server.launch_unavailable_reason or "Launch time unavailable.")
    if server.shape_conflict:
        return unavailable(
            f"The shape this session was identified with is contradicted: "
            f"{server.shape_conflict}. The total is unavailable until a new session is observed."
        )
    if server.state in STOPPED_SERVER_STATES and server.ended_at is None:
        return unavailable(
            f"The server is {server.state.lower()} and the provider did not report when this "
            "session ended."
        )
    if cutoff <= server.launch_at:
        return unavailable("No running time has been observed since this launch yet.")
    if not prices or not (server.machine_type and server.purchase_model and server.region):
        return unavailable(rate_reason or "No applicable machine price was found.")
    priced = price_windows([(server.launch_at, cutoff)], prices)
    common = {
        "rate": rate, "rate_unavailable_reason": rate_reason, "cutoff": cutoff,
        "elapsed_seconds": priced.observed_seconds, "billed_seconds": priced.billed_seconds,
        "allocations": priced.allocations,
    }
    if not priced.uncovered:
        return ServerSessionCost(**common, completeness="complete", total=priced.amount)
    unpriced_until = max(end for _, end in priced.uncovered)
    reason = (
        f"No published rate for {_shape_label(server)} covers this session from "
        f"{server.launch_at.isoformat()} until {unpriced_until.isoformat()}; a later rate is "
        "never applied to earlier time."
    )
    if not priced.allocations:
        return ServerSessionCost(**common, completeness="unavailable", unavailable_reason=reason)
    return ServerSessionCost(
        **common, completeness="partial", known_subtotal=priced.amount, unavailable_reason=reason
    )


# Change detection runs in the database: hashing every fact row in Python cost
# a multiple of the job count on each request. These are change markers, not
# security digests, so md5 of the row text is sufficient.
FINGERPRINT = text("""
    WITH parts AS (
        SELECT md5(t::text) AS h FROM tenant t WHERE t.id = :tenant
        UNION ALL SELECT md5(t::text) FROM owner t WHERE t.tenant_id = :tenant
        UNION ALL SELECT md5(t::text) FROM job t WHERE t.tenant_id = :tenant
        UNION ALL SELECT md5(t::text)
                    FROM execution_attempt t
                    JOIN job j ON j.id = t.job_id
                   WHERE j.tenant_id = :tenant
        UNION ALL SELECT md5(t::text) FROM resource_lifetime t WHERE t.tenant_id = :tenant
        UNION ALL SELECT md5(t::text)
                    FROM resource_segment t
                    JOIN resource_lifetime l ON l.id = t.lifetime_id
                   WHERE l.tenant_id = :tenant
        UNION ALL SELECT md5(t::text)
                    FROM lifetime_attempt t
                    JOIN resource_lifetime l ON l.id = t.lifetime_id
                   WHERE l.tenant_id = :tenant
        UNION ALL SELECT md5(t::text) FROM deployment_policy t WHERE t.tenant_id = :tenant
        UNION ALL SELECT md5(t::text) FROM price_version t
        UNION ALL SELECT md5(t::text) FROM invocation t WHERE t.tenant_id = :tenant
        UNION ALL SELECT md5(t::text)
                    FROM invocation_job t
                    JOIN invocation i ON i.id = t.invocation_id
                   WHERE i.tenant_id = :tenant
        UNION ALL SELECT md5(t::text)
                    FROM infrastructure_interval t
                   WHERE t.tenant_id = :tenant
    )
    SELECT coalesce(md5(string_agg(h, '' ORDER BY h)), 'empty') AS digest FROM parts
""")


def report_fingerprint(session: Session, tenant_id: uuid.UUID) -> str:
    """Hash the mutable facts that can change a tenant report.

    This identifies *identical* facts, so a replay that rewrites the same
    values reuses its calculation revision. Request-time staleness uses the
    cheaper generation marker below. Raw job metrics are deliberately absent:
    they reach reports only through the attempts, lifetimes and job resource
    hints hashed here.
    """
    session.flush()
    return session.execute(FINGERPRINT, {"tenant": tenant_id}).scalar_one()


def current_generation(session: Session, tenant_id: uuid.UUID) -> int:
    """The tenant's report-generation marker, advanced by database triggers.

    Reporting requests only read it; the marker row is created when the tenant
    is, so a missing row means no facts have been recorded yet.
    """
    session.flush()
    row = session.get(ReportGeneration, tenant_id)
    if row is None:
        return 0
    session.refresh(row)
    return row.generation


def _ensure_generation(session: Session, tenant_id: uuid.UUID) -> int:
    row = session.get(ReportGeneration, tenant_id)
    if row is None:
        row = ReportGeneration(tenant_id=tenant_id, generation=1, updated_at=datetime.now(UTC))
        session.add(row)
        session.flush()
    return current_generation(session, tenant_id)


def applicable_prices(
    session: Session,
    *,
    provider: str,
    region: str | None,
    machine_type: str | None,
    purchase_model: str | None,
) -> list[PriceVersion]:
    """Every price for one shape; only those in effect at a given time apply.

    Prices that take effect later are kept so unpriced work can say that its
    shape is priced, just not for when it ran.
    """
    statement = select(PriceVersion).where(
        PriceVersion.provider == provider,
        PriceVersion.region == region,
        PriceVersion.machine_type == machine_type,
        PriceVersion.purchase_model == purchase_model,
    )
    return list(session.scalars(statement.order_by(PriceVersion.effective_from.asc().nullsfirst())))


def _applicable_prices(session: Session, lifetime: ResourceLifetime) -> list[PriceVersion]:
    return applicable_prices(
        session,
        provider=lifetime.provider,
        region=lifetime.region,
        machine_type=lifetime.machine_type,
        purchase_model=lifetime.purchase_model,
    )


def calculate_tenant(
    session: Session, tenant_id: uuid.UUID, reason: str = "collection"
) -> CostRevision:
    """Bring the tenant's one calculation up to date with its facts.

    Cost lines are updated in place: only lines whose values changed are
    written, and lines for work that no longer has a charge are removed. The
    calculation's `id` changes with any recalculation, so a report pinned to
    the previous calculation sees that it is stale.
    """
    session.flush()
    generation = _ensure_generation(session, tenant_id)
    current = session.get(CostRevision, tenant_id)
    same_version = current is not None and current.calculation_version == CALCULATION_VERSION
    if same_version and current.facts_generation == generation:
        return current
    digest = report_fingerprint(session, tenant_id)
    if same_version and current.input_digest == digest:
        # Replaying identical facts keeps the same calculation; only its marker
        # moves forward, because the rewrite advanced the generation.
        current.facts_generation = generation
        session.flush()
        return current

    _write_lines(session, tenant_id, _calculate_lines(session, tenant_id))
    if current is None:
        current = CostRevision(tenant_id=tenant_id)
        session.add(current)
    current.id = uuid.uuid4()
    current.calculation_version = CALCULATION_VERSION
    current.input_digest = digest
    current.facts_generation = generation
    current.reason = reason
    current.created_at = datetime.now(UTC)
    session.flush()
    return current


LineKey = tuple[uuid.UUID, uuid.UUID, str, str]
LINE_FIELDS = (
    "attempt_id", "amount", "currency", "quality", "reason", "price_version_id",
    "policy_id", "details",
)
# The scale of `cost_line.amount`. PostgreSQL rounds half away from zero on
# store, so rounding the same way first lets a stored amount compare equal to
# its unchanged recalculation instead of being rewritten every time.
AMOUNT_SCALE = Decimal("1e-12")


def _stored_amount(amount: Decimal | None) -> Decimal | None:
    return None if amount is None else amount.quantize(AMOUNT_SCALE, rounding=ROUND_HALF_UP)


def _calculate_lines(session: Session, tenant_id: uuid.UUID) -> dict[LineKey, dict]:
    """Every cost line the tenant's facts call for, keyed by what it charges."""
    policy = session.scalar(
        select(DeploymentPolicy)
        .where(DeploymentPolicy.tenant_id == tenant_id)
        .order_by(DeploymentPolicy.effective_from.desc())
    )
    lifetimes = list(
        session.scalars(
            select(ResourceLifetime)
            .where(ResourceLifetime.tenant_id == tenant_id)
            .order_by(ResourceLifetime.resource_key)
        )
    )
    calculated: dict[LineKey, dict] = {}
    for lifetime in lifetimes:
        segments = list(
            session.scalars(
                select(ResourceSegment)
                .where(ResourceSegment.lifetime_id == lifetime.id)
                .order_by(ResourceSegment.source_segment_id)
            )
        )
        links = list(
            session.execute(
                select(LifetimeAttempt, ExecutionAttempt, Job)
                .join(ExecutionAttempt, LifetimeAttempt.attempt_id == ExecutionAttempt.id)
                .join(Job, ExecutionAttempt.job_id == Job.id)
                .where(LifetimeAttempt.lifetime_id == lifetime.id)
                .order_by(Job.source_id, ExecutionAttempt.source_attempt_id)
            ).all()
        )
        if not links:
            continue
        jobs = {job.id: job for _, _, job in links}
        prices = _applicable_prices(session, lifetime)
        lines = calculate_lifetime(lifetime, segments, prices, shared_job_count=len(jobs))
        for job_id in jobs:
            attempts = [
                attempt for _, attempt, attempt_job in links if attempt_job.id == job_id
            ]
            for line in lines:
                used_price_ids = {
                    allocation["price_version_id"]
                    for allocation in line.allocations
                    if allocation["price_version_id"]
                }
                single_price = (
                    next((value for value in prices if str(value.id) in used_price_ids), None)
                    if len(used_price_ids) == 1
                    else None
                )
                calculated[(lifetime.id, job_id, line.basis, "compute")] = {
                    # A charge shared by retries belongs to the lifetime, not
                    # to one attempt row.
                    "attempt_id": attempts[0].id if len(attempts) == 1 else None,
                    "amount": _stored_amount(line.amount),
                    "currency": prices[0].currency if prices else "USD",
                    "quality": line.quality,
                    "reason": line.reason,
                    "price_version_id": (
                        single_price.id if single_price and line.amount is not None else None
                    ),
                    "policy_id": policy.id if policy else None,
                    "details": {
                        "resource_key": lifetime.resource_key,
                        "resource_uid": lifetime.resource_uid,
                        "machine_type": lifetime.machine_type,
                        "timing_method": lifetime.timing_method,
                        "billed_seconds": str(line.billed_seconds) if line.billed_seconds else None,
                        "hourly_rate": str(single_price.hourly_rate) if single_price else None,
                        "shared_attempt_ids": [str(attempt.id) for attempt in attempts],
                        "shared_attempt_count": len(attempts),
                        "shared_job_count": len(jobs),
                        "allocations": list(line.allocations),
                    },
                }
    return calculated


def _write_lines(
    session: Session, tenant_id: uuid.UUID, calculated: dict[LineKey, dict]
) -> None:
    stored = {
        (line.lifetime_id, line.job_id, line.basis, line.component): line
        for line in session.scalars(
            select(CostLine).join(Job, CostLine.job_id == Job.id).where(Job.tenant_id == tenant_id)
        )
    }
    for key, values in calculated.items():
        line = stored.pop(key, None)
        if line is None:
            lifetime_id, job_id, basis, component = key
            session.add(CostLine(
                id=uuid.uuid4(), lifetime_id=lifetime_id, job_id=job_id, basis=basis,
                component=component, **values,
            ))
            continue
        for name in LINE_FIELDS:
            if getattr(line, name) != values[name]:
                setattr(line, name, values[name])
    for line in stored.values():
        session.delete(line)
