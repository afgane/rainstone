import csv
import hashlib
import io
import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rainstone.adapters.contracts import GALAXY_RECORD_ATTEMPT_ID
from rainstone.auth import Identity
from rainstone.catalog import price_list
from rainstone.costing import (
    SERVER_CALCULATION_VERSION,
    applicable_prices,
    calculate_server_session,
    current_generation,
)
from rainstone.ingestion import PENDING_ATTEMPT_LIMIT
from rainstone.job_use import job_resource_use
from rainstone.machine_shapes import machine_capacity
from rainstone.models import (
    CostLine,
    CostRevision,
    ExecutionAttempt,
    GalaxyServerSession,
    InfrastructureInterval,
    IngestionState,
    Invocation,
    InvocationJob,
    Job,
    JobMetric,
    LifetimeAttempt,
    ObservationGap,
    Owner,
    PriceVersion,
    Quality,
    ResourceLifetime,
    Tenant,
)
from rainstone.report_query import ReportQuery, RunReportQuery, as_run_query

ZERO = Decimal("0")
SORT_FIELDS = {"created_at", "source_id", "tool_id", "state", "runner", "owner", "amount"}
RUNNING_STATES = {"new", "queued", "running", "paused", "resubmitted"}
# Queued work can already hold provider capacity, so it may be accruing cost.
EXECUTING_STATES = {"queued", "running", "resubmitted"}
UNSTARTED_STATES = {"new", "paused"}
# Record-level qualities beyond the stored line qualities: a job without cost
# lines is unavailable when it finished and not started when it never ran.
UNAVAILABLE = "unavailable"
NOT_STARTED = "not_started"
COLLECTING = "collecting"
INCOMPLETE_QUALITIES = {
    Quality.partial.value, Quality.unpriced.value, Quality.in_progress.value,
    UNAVAILABLE, NOT_STARTED, COLLECTING,
}


def tool_display_name(tool_id: str) -> str:
    """A readable name derived from the full tool identity.

    Galaxy's database records the tool ID, not its display name, so this is an
    honest fallback rather than the tool's own label. The full identity is
    always carried alongside it, because two different tools can share a short
    name.
    """
    if "/" not in tool_id:
        return tool_id.replace("_", " ")
    parts = [part for part in tool_id.split("/") if part]
    # Tool Shed IDs end with `<repo>/<tool>/<version>`; the tool segment reads
    # best, and a repeated segment adds nothing.
    name = parts[-2] if len(parts) >= 2 else parts[-1]
    return name.replace("_", " ")


def tool_family_key(tool_id: str, tool_version: str | None) -> str:
    """The identity every version of one tool shares.

    A Tool Shed ID is `<shed>/repos/<owner>/<repository>/<tool>/<version>`;
    only that terminal version is removed, and only when the job's recorded
    version confirms it is one. Any other ID is its own family, because a
    readable name alone cannot tell two different tools apart.
    """
    parts = tool_id.split("/")
    if (
        len(parts) == 6 and parts[1] == "repos" and all(parts)
        and (tool_version is None or parts[5] == tool_version)
    ):
        return "/".join(parts[:5])
    return tool_id


def _revision(session: Session, identity: Identity, requested: str | None) -> CostRevision | None:
    if requested:
        try:
            requested_id = uuid.UUID(requested)
        except ValueError as exc:
            raise HTTPException(422, "Invalid calculation revision") from exc
    revision = session.get(CostRevision, identity.tenant_id)
    if requested and (revision is None or revision.id != requested_id):
        raise HTTPException(
            409,
            "This snapshot is stale because report facts changed; refresh to select the latest revision",
        )
    if revision and revision.facts_generation != current_generation(session, identity.tenant_id):
        raise HTTPException(
            409,
            "This snapshot is stale because reporting facts changed; refresh to recalculate costs",
        )
    return revision


def validate_snapshot(session: Session, identity: Identity, query: ReportQuery) -> None:
    """Fail before a streaming response starts if its requested snapshot is stale."""
    _revision(session, identity, query.revision)


def _evidence_pending(job: Job, as_of: datetime | None) -> bool:
    """Finished so recently that its provider evidence may still be on its way.

    Evidence for a finished job can arrive up to a day later; it waits that
    long for its Galaxy job too.
    """
    return bool(as_of and job.updated_at and as_of - job.updated_at < PENDING_ATTEMPT_LIMIT)


def _quality(lines: list[CostLine], state: str | None = None, *, collecting: bool = False) -> str:
    if not lines:
        if state in EXECUTING_STATES:
            return Quality.in_progress.value
        if state in UNSTARTED_STATES:
            return NOT_STARTED
        return COLLECTING if collecting else UNAVAILABLE
    qualities = {line.quality for line in lines}
    if Quality.partial in qualities:
        return Quality.partial.value
    if Quality.unpriced in qualities:
        return Quality.unpriced.value
    if any(line.amount is None for line in lines):
        return Quality.partial.value
    if Quality.approximate in qualities:
        return Quality.approximate.value
    if qualities == {Quality.known_zero}:
        return Quality.known_zero.value
    return Quality.complete.value


def _missing_evidence_reason(
    job: Job, attempts: list[ExecutionAttempt], *, collecting: bool = False
) -> str:
    if job.state in EXECUTING_STATES:
        return "Awaiting execution evidence for work that is still running."
    if job.state == "paused":
        return "Paused before running; no execution was recorded."
    if job.state == "new":
        return "Not started yet; no execution was recorded."
    if collecting:
        return (
            "This job finished recently and the evidence of where it ran has not arrived yet. "
            "It usually takes a few minutes; the cost appears once it does."
        )
    if any(attempt.tool_started_at for attempt in attempts):
        return (
            "Galaxy recorded when this ran but no evidence of where it ran was collected, so its "
            "cost is unavailable. Recalculating alone will not recover it."
        )
    return (
        "No execution evidence was collected for this job, so its cost is unavailable. "
        "Recalculating alone will not recover it."
    )


UNCOSTED_ATTEMPT_REASON = (
    "An attempt of this job has no resource evidence, so its cost is missing from this amount."
)


def _attempt_in_period(attempt: ExecutionAttempt, query: ReportQuery, completed_mode: bool) -> bool:
    """Whether an attempt's own timing, when it has any, falls inside the report period.

    Untimed attempts cannot be placed, so they are treated as inside: excluding
    them would let a missing cost disappear from every period at once.
    """
    if completed_mode or attempt.tool_started_at is None:
        return True
    end = attempt.tool_finished_at or attempt.tool_started_at
    return _slice_fraction(attempt.tool_started_at, max(end, attempt.tool_started_at), query) > 0


def _executions(
    attempts: list[ExecutionAttempt], with_resources: set[uuid.UUID]
) -> tuple[list[ExecutionAttempt], list[ExecutionAttempt], str]:
    """Reconcile observations into logical execution attempts.

    Returns the first attempt of each task, its repeats, and which evidence the
    reconciliation rests on. Galaxy's record of a job describes one of the
    provider-observed executions whenever those exist, unless it carries a
    resource of its own. Parallel tasks of one submission are not repeats; a
    later ordinal of the same task, or a later submission of it, is.
    """
    provider = [a for a in attempts if a.source_attempt_id != GALAXY_RECORD_ATTEMPT_ID]
    galaxy = [a for a in attempts if a.source_attempt_id == GALAXY_RECORD_ATTEMPT_ID]
    if provider:
        logical = provider + [a for a in galaxy if a.id in with_resources]
        evidence = "provider"
    else:
        logical = galaxy
        evidence = "galaxy_record" if galaxy else "none"
    tasks: dict[int | None, list[ExecutionAttempt]] = defaultdict(list)
    for attempt in logical:
        tasks[attempt.task_index].append(attempt)
    first: list[ExecutionAttempt] = []
    repeats: list[ExecutionAttempt] = []
    for group in tasks.values():
        group.sort(key=lambda a: (
            a.tool_started_at is None, a.tool_started_at or datetime.min.replace(tzinfo=UTC),
            a.attempt_ordinal or 0, a.source_attempt_id,
        ))
        first.append(group[0])
        repeats.extend(group[1:])
    return first, repeats, evidence


def _line_slices(
    line: CostLine, lifetime: ResourceLifetime, as_of: datetime
) -> list[tuple[datetime, datetime, Decimal | None]]:
    allocations = (line.details or {}).get("allocations") or []
    if allocations:
        amounts = [Decimal(value["amount"]) for value in allocations]
        if line.amount is not None:
            rounded = [value.quantize(Decimal("0.000000000001")) for value in amounts[:-1]]
            amounts = [*rounded, line.amount - sum(rounded, ZERO)]
        return [
            (datetime.fromisoformat(value["start"]), datetime.fromisoformat(value["end"]), amount)
            for value, amount in zip(allocations, amounts, strict=True)
        ]
    if lifetime.observed_start:
        end = lifetime.observed_end or as_of
        if end >= lifetime.observed_start:
            return [(lifetime.observed_start, end, line.amount)]
    return []


def _slice_fraction(start: datetime, end: datetime, query: ReportQuery) -> Decimal:
    if start == end:
        # An instant has no duration to apportion; it belongs to the half-open
        # interval that contains it, whole.
        inside = (not query.from_time or start >= query.from_time) and (
            not query.to_time or start < query.to_time
        )
        return Decimal("1") if inside else ZERO
    lower, upper = query.from_time or start, query.to_time or end
    overlap = max(0.0, (min(end, upper) - max(start, lower)).total_seconds())
    return Decimal(str(overlap)) / Decimal(str((end - start).total_seconds()))


def _authorized_invocations(session: Session, identity: Identity):
    statement = select(Invocation).where(Invocation.tenant_id == identity.tenant_id)
    if not identity.is_admin:
        statement = statement.where(Invocation.owner_id == identity.owner_id)
    return list(session.scalars(statement))


def _workflow_job_ids(session: Session, identity: Identity, query: ReportQuery) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Resolve workflow filters to authorized, ownership-consistent memberships."""
    invocations = _authorized_invocations(session, identity)
    selected = invocations
    if query.invocation_id:
        try:
            requested = uuid.UUID(query.invocation_id)
            selected = [inv for inv in selected if inv.id == requested]
        except ValueError:
            selected = [inv for inv in selected if inv.source_id == query.invocation_id]
    if query.workflow_id:
        selected = [inv for inv in selected if (inv.workflow_id or inv.source_id) == query.workflow_id]
    if query.search:
        term = query.search.casefold()
        selected = [inv for inv in selected if term in (
            f"{inv.source_id} {inv.workflow_id or ''} {inv.workflow_name} {inv.workflow_version or ''}".casefold()
        )]
    invocation_ids = {inv.id for inv in selected}
    if not invocation_ids:
        return set(), set()
    # A malformed cross-owner membership cannot expand a viewer's authorized cohort.
    rows = session.execute(
        select(InvocationJob.job_id, InvocationJob.invocation_id)
        .join(Invocation, InvocationJob.invocation_id == Invocation.id)
        .join(Job, InvocationJob.job_id == Job.id)
        .where(
            InvocationJob.invocation_id.in_(invocation_ids),
            Job.tenant_id == identity.tenant_id,
            Job.owner_id == Invocation.owner_id,
        )
    )
    return {row.job_id for row in rows}, invocation_ids


@dataclass
class _JobFacts:
    """What a report loads about its jobs before any period is applied.

    A request that needs both a period's records and the whole-job records
    loads these once and builds each set from them.
    """

    revision: CostRevision | None
    workflow_jobs: set[uuid.UUID]
    jobs: list
    line_map: dict[uuid.UUID, list[tuple[CostLine, ResourceLifetime]]]
    attempt_map: dict[uuid.UUID, list[ExecutionAttempt]]
    lifetime_attempts: dict[uuid.UUID, list[ExecutionAttempt]]
    as_of: datetime


def _columns(model, *left_out: str) -> list:
    return [column for column in model.__table__.c if column.name not in left_out]


def _load_job_facts(
    session: Session,
    identity: Identity,
    query: ReportQuery,
    *,
    candidate_offset: int | None = None,
    candidate_limit: int | None = None,
    candidate_count: list[int] | None = None,
    within_runs: bool = False,
    lifetime_facts: bool = False,
    only_job: uuid.UUID | None = None,
) -> _JobFacts:
    """Load the jobs a report needs and what costs them.

    Facts are read as plain rows, not ORM entities: a report reads tens of
    thousands of them and never changes one, and row objects cost a fraction of
    an entity's identity tracking. Related rows are fetched through the same
    job filter as a subquery, so no request carries a list of job IDs.
    `within_runs` narrows the jobs to those a workflow run contains and
    `only_job` to one job, on top of every authorization condition. Free-form
    evidence columns that no report total reads stay in the database;
    `lifetime_facts` brings back a resource's, which a job's detail shows.
    """
    revision = _revision(session, identity, query.revision)
    as_of = revision.created_at if revision else datetime.now(UTC)
    workflow_jobs: set[uuid.UUID] = set()
    if query.search or query.invocation_id or query.workflow_id:
        workflow_jobs, _ = _workflow_job_ids(session, identity, query)
    conditions = [Job.tenant_id == identity.tenant_id]
    if not identity.is_admin:
        conditions.append(Job.owner_id == identity.owner_id)
    if only_job is not None:
        conditions.append(Job.id == only_job)
    if query.owner:
        if not identity.is_admin and query.owner != identity.source_id:
            return _JobFacts(revision, workflow_jobs, [], {}, {}, {}, as_of)
        conditions.append(Owner.source_id == query.owner)
    if query.search:
        term = f"%{query.search}%"
        # The displayed tool name is part of the ID with underscores read as
        # spaces, so matching that spelling finds every name the page shows.
        job_match = (
            Job.source_id.ilike(term) | Job.tool_id.ilike(term)
            | func.replace(Job.tool_id, "_", " ").ilike(term)
            | func.coalesce(Job.tool_version, "").ilike(term) | Owner.label.ilike(term)
        )
        if workflow_jobs:
            job_match = job_match | Job.id.in_(workflow_jobs)
        conditions.append(job_match)
    for column, value in (
        (Job.tool_id, query.tool_id), (Job.tool_version, query.tool_version),
        (Job.state, query.state), (Job.runner, query.runner),
        (Job.destination, query.destination),
    ):
        if value:
            conditions.append(column == value)
    if query.tool_key:
        # A coarse match the records then confirm exactly per job.
        conditions.append(
            (Job.tool_id == query.tool_key)
            | Job.tool_id.startswith(f"{query.tool_key}/", autoescape=True)
        )
    if within_runs:
        in_a_run = (
            select(InvocationJob.job_id)
            .join(Invocation, InvocationJob.invocation_id == Invocation.id)
            .where(Invocation.tenant_id == identity.tenant_id)
        )
        if not identity.is_admin:
            in_a_run = in_a_run.where(Invocation.owner_id == identity.owner_id)
        conditions.append(Job.id.in_(in_a_run))
    joined = Job.__table__.join(Owner.__table__, Job.owner_id == Owner.id)
    statement = select(
        *_columns(Job, "resource_hints"), Owner.label.label("owner_label"),
        Owner.source_id.label("owner_source_id"),
    ).select_from(joined).where(*conditions)
    if candidate_offset is not None and candidate_limit is not None:
        sort_columns = {
            "created_at": Job.created_at, "source_id": Job.source_id, "tool_id": Job.tool_id,
            "state": Job.state, "runner": Job.runner, "owner": Owner.label,
        }
        column = sort_columns.get(query.sort, Job.created_at)
        order = column.asc().nullslast() if query.direction == "asc" else column.desc().nullslast()
        statement = statement.order_by(order, Job.id).offset(candidate_offset).limit(candidate_limit)
    jobs = session.execute(statement).all()
    if candidate_count is not None:
        candidate_count.append(len(jobs))
    if candidate_limit is not None:
        scope = [job.id for job in jobs]
    else:
        scope = select(Job.id).select_from(joined).where(*conditions)
    line_map: dict[uuid.UUID, list[tuple]] = defaultdict(list)
    attempt_map: dict[uuid.UUID, list] = defaultdict(list)
    lifetime_attempts: dict[uuid.UUID, list] = defaultdict(list)
    if jobs:
        attempts_by_id = {}
        for attempt in session.execute(
            select(*_columns(ExecutionAttempt, "facts"))
            .where(ExecutionAttempt.job_id.in_(scope))
            .order_by(ExecutionAttempt.source_attempt_id)
        ):
            attempt_map[attempt.job_id].append(attempt)
            attempts_by_id[attempt.id] = attempt
        for lifetime_id, attempt_id in session.execute(
            select(LifetimeAttempt.lifetime_id, LifetimeAttempt.attempt_id)
            .join(ExecutionAttempt, LifetimeAttempt.attempt_id == ExecutionAttempt.id)
            .where(ExecutionAttempt.job_id.in_(scope))
        ):
            lifetime_attempts[lifetime_id].append(attempts_by_id[attempt_id])
    if revision and jobs:
        lines = session.execute(
            select(*CostLine.__table__.c).where(
                CostLine.basis == query.basis, CostLine.job_id.in_(scope)
            )
        ).all()
        lifetimes = {
            lifetime.id: lifetime for lifetime in session.execute(
                select(*_columns(ResourceLifetime, *(() if lifetime_facts else ("facts",)))).where(ResourceLifetime.id.in_(
                    select(CostLine.lifetime_id).where(
                        CostLine.basis == query.basis, CostLine.job_id.in_(scope)
                    )
                ))
            )
        }
        for line in lines:
            line_map[line.job_id].append((line, lifetimes[line.lifetime_id]))
    return _JobFacts(revision, workflow_jobs, jobs, line_map, attempt_map, lifetime_attempts, as_of)


def _base_records(
    session: Session,
    identity: Identity,
    query: ReportQuery,
    *,
    candidate_offset: int | None = None,
    candidate_limit: int | None = None,
    candidate_count: list[int] | None = None,
    undated: list[dict] | None = None,
    lifetime_facts: bool = False,
) -> tuple[list[dict], CostRevision | None]:
    """Report records for the query, one per authorized job.

    Under a date filter, a job whose cost cannot be placed in time belongs to no
    period: it is left out of the result and appended to `undated`, so period
    totals, counts and rankings never absorb it.
    """
    facts = _load_job_facts(
        session, identity, query, candidate_offset=candidate_offset,
        candidate_limit=candidate_limit, candidate_count=candidate_count,
        lifetime_facts=lifetime_facts,
    )
    return _records_from_facts(facts, query, undated), facts.revision


def _records_from_facts(
    facts: _JobFacts, query: ReportQuery, undated: list[dict] | None = None
) -> list[dict]:
    workflow_jobs, jobs = facts.workflow_jobs, facts.jobs
    line_map, attempt_map = facts.line_map, facts.attempt_map
    lifetime_attempts = facts.lifetime_attempts
    invocation_jobs: set[uuid.UUID] | None = None
    if query.invocation_id or query.workflow_id:
        invocation_jobs = workflow_jobs

    resourced_attempts = {
        attempt.id for users in lifetime_attempts.values() for attempt in users
    }
    as_of = facts.as_of
    dated = bool(query.from_time or query.to_time)
    records: list[dict] = []
    for job in jobs:
        if invocation_jobs is not None and job.id not in invocation_jobs:
            continue
        pairs = line_map[job.id]
        attempts = attempt_map[job.id]
        lines = [pair[0] for pair in pairs]
        collecting = not lines and _evidence_pending(job, as_of)
        quality = _quality(lines, job.state, collecting=collecting)
        first, repeats, attempt_evidence = _executions(attempts, resourced_attempts)
        repeat_ids = {attempt.id for attempt in repeats}
        completions = [
            attempt.tool_finished_at for attempt in attempts
            if attempt.outcome == "ok" and attempt.tool_finished_at
        ]
        completed_at = max(completions) if completions else None
        completed_mode = query.mode == "completed"
        if completed_mode and (
            not completed_at or (query.from_time and completed_at < query.from_time)
            or (query.to_time and completed_at >= query.to_time)
        ):
            continue
        known_amounts: list[Decimal] = []
        unattributed = ZERO
        capacities: set[str] = set()
        interval_hit = False
        has_timing = False
        repeat_amount = ZERO
        repeat_shared_amount = ZERO
        repeat_incomplete = False
        for line, lifetime in pairs:
            capacities.add(lifetime.capacity_relationship.value)
            slices = _line_slices(line, lifetime, as_of)
            has_timing = has_timing or bool(slices)
            if not slices and line.amount is not None:
                unattributed += line.amount
            line_hit = False
            line_amount: Decimal | None = None
            for start, end, slice_amount in slices:
                fraction = _slice_fraction(start, end, query)
                if fraction > 0:
                    line_hit = True
                    if slice_amount is not None:
                        line_amount = (line_amount or ZERO) + slice_amount * min(fraction, Decimal("1"))
            if completed_mode:
                line_hit, line_amount = True, line.amount
            interval_hit = interval_hit or line_hit
            if line_amount is not None:
                known_amounts.append(line_amount)
            users = {
                attempt.id for attempt in lifetime_attempts.get(lifetime.id, [])
                if attempt.job_id == job.id
            }
            if not line_hit or not users & repeat_ids:
                continue
            if line_amount is None:
                repeat_incomplete = True
            elif users <= repeat_ids:
                repeat_amount += line_amount
            else:
                # One resource served the first attempt and a repeat; its
                # charge cannot be divided between them without a policy.
                repeat_shared_amount += line_amount
                repeat_incomplete = True
        if dated and not completed_mode and has_timing and not interval_hit:
            continue
        # An execution with no resource evidence has a cost this job's lines
        # cannot include, however complete the lines themselves are.
        costed = {
            attempt.id for _, lifetime in pairs
            for attempt in lifetime_attempts.get(lifetime.id, []) if attempt.job_id == job.id
        }
        uncosted = [
            attempt for attempt in [*first, *repeats]
            if attempt.id not in costed and _attempt_in_period(attempt, query, completed_mode)
        ]
        if lines and uncosted and quality != Quality.unpriced.value:
            quality = Quality.partial.value
        if any(attempt.id in repeat_ids for attempt in uncosted):
            repeat_incomplete = True
        amount = sum(known_amounts, ZERO) if known_amounts else None
        if any(line.amount is not None for line in lines) and amount is None and not dated:
            amount = ZERO
        if query.tool_id and job.tool_id != query.tool_id:
            continue
        if query.tool_version and job.tool_version != query.tool_version:
            continue
        if query.tool_key and tool_family_key(job.tool_id, job.tool_version) != query.tool_key:
            continue
        if query.state and job.state != query.state:
            continue
        if query.runner and job.runner != query.runner:
            continue
        if query.destination and job.destination != query.destination:
            continue
        if query.capacity and query.capacity not in capacities:
            continue
        if query.quality and quality != query.quality:
            continue
        if query.min_cost is not None and (amount is None or amount < query.min_cost):
            continue
        if query.max_cost is not None and (amount is None or amount > query.max_cost):
            continue
        record = {
            "id": str(job.id), "source_id": job.source_id, "tool_id": job.tool_id,
            "tool_name": tool_display_name(job.tool_id),
            "tool_key": tool_family_key(job.tool_id, job.tool_version),
            "tool_version": job.tool_version, "owner": job.owner_label, "owner_id": job.owner_source_id,
            "state": job.state, "runner": job.runner, "destination": job.destination,
            "created_at": job.created_at, "updated_at": job.updated_at, "amount": amount,
            "currency": "USD", "quality": quality,
            "reason": " | ".join(sorted(
                {line.reason for line in lines} | ({UNCOSTED_ATTEMPT_REASON} if lines and uncosted else set())
            )) or _missing_evidence_reason(job, attempts, collecting=collecting),
            "cost_lines": len(lines),
            "attempt_count": len(first) + len(repeats),
            "repeat_attempt_count": len(repeats),
            "attempt_evidence": attempt_evidence,
            "observation_count": len(attempts),
            "repeat_amount": repeat_amount,
            "repeat_shared_amount": repeat_shared_amount,
            "repeat_amount_complete": not repeat_incomplete,
            "capacities": sorted(capacities),
            "unattributed_amount": unattributed,
            "temporally_unattributed": not has_timing,
            "completed_at": completed_at,
            "full_amount": sum((line.amount for line in lines if line.amount is not None), ZERO)
            if any(line.amount is not None for line in lines) else None,
            "job": job, "pairs": pairs, "attempts": attempts,
            "lifetime_attempts": lifetime_attempts,
        }
        if dated and not completed_mode and not has_timing:
            if undated is not None:
                undated.append(record)
            continue
        records.append(record)
    return records


def _window(query: ReportQuery, records: list[dict]) -> dict:
    starts = [
        lifetime.observed_start
        for record in records for _, lifetime in record["pairs"]
        if lifetime.observed_start
    ]
    ends = [
        lifetime.observed_end
        for record in records for _, lifetime in record["pairs"]
        if lifetime.observed_end
    ]
    lower = query.from_time or (min(starts) if starts else None)
    upper = query.to_time or (max(ends) if ends else None)
    return {
        "from": lower.isoformat() if lower else None, "to": upper.isoformat() if upper else None,
        "timezone": query.timezone, "semantics": "[from, to)", "mode": query.mode,
    }


def _undated_meta(query: ReportQuery, undated: list[dict] | None) -> dict | None:
    """Evidence no period can hold, reported beside a dated result, never in it."""
    if not (query.from_time or query.to_time) or query.mode == "completed" or undated is None:
        return None
    known = [r["full_amount"] for r in undated if r["full_amount"] is not None]
    return {
        "job_count": len(undated),
        "amount": _money(sum(known, ZERO)) if known else None,
        "incomplete": sum(r["quality"] in INCOMPLETE_QUALITIES for r in undated),
    }


def _meta(
    session: Session, identity: Identity, query: ReportQuery, revision, records: list[dict],
    undated: list[dict] | None = None,
) -> dict:
    priced = [r for r in records if r["amount"] is not None]
    return {
        "basis": query.basis, "currency": "USD",
        "applied_filters": query.model_dump(
            mode="json",
            exclude={
                "limit", "offset", "undated_offset", "sort", "direction", "run_sort", "bucket",
            },
        ),
        "observation_window": _window(query, records),
        "revision_id": str(revision.id) if revision else None,
        "calculation_version": revision.calculation_version if revision else None,
        "as_of": revision.created_at.isoformat() if revision else None,
        "priced_subtotal": _money(sum((r["amount"] for r in priced), ZERO)) if priced else None,
        "coverage": {
            "jobs": len(records), "priced": len(priced),
            "incomplete": sum(r["quality"] in INCOMPLETE_QUALITIES for r in records),
            "known_zero": sum(r["quality"] == "known_zero" for r in records),
            "temporally_unattributed": sum(r["temporally_unattributed"] for r in records),
        },
        "undated": _undated_meta(query, undated),
        "price_list": price_list(session),
    }


def _public(record: dict) -> dict:
    return {
        key: _money(value) if isinstance(value, Decimal) else value
        for key, value in record.items()
        if key not in {
            "job", "pairs", "attempts", "lifetime_attempts", "full_amount",
            "repeat_amount", "repeat_shared_amount", "repeat_amount_complete",
        }
    }


def _repeated_work(records: list[dict]) -> dict:
    """Failed and repeated work, each already part of the period total.

    "Jobs that repeated" is the whole cost of any job with a repeat attempt;
    "repeat attempts" is only what the repeats themselves used. A resource
    shared by a first attempt and its repeat belongs to neither alone, so it is
    reported separately and leaves the attributable subtotal incomplete.
    """
    failed = [r for r in records if r["state"] in {"error", "failed"}]
    repeated = [r for r in records if r["repeat_attempt_count"]]
    return {
        "failed_spend": _money(sum((r["amount"] or ZERO for r in failed), ZERO)),
        "failed_job_count": len(failed),
        "failed_incomplete_job_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in failed),
        "repeated_job_spend": _money(sum((r["amount"] or ZERO for r in repeated), ZERO)),
        "repeated_job_count": len(repeated),
        "repeat_attempt_spend": _money(sum((r["repeat_amount"] for r in repeated), ZERO)),
        "repeat_attempt_shared_spend": _money(sum((r["repeat_shared_amount"] for r in repeated), ZERO)),
        "repeat_attempt_spend_complete": all(r["repeat_amount_complete"] for r in repeated),
    }


def _imported_snapshot(capabilities: dict) -> dict | None:
    """Real facts restored from a capture, which are neither live nor synthetic.

    The loader that restores a capture records its manifest here; only the
    fields a report needs to describe the capture are passed on.
    """
    manifest = capabilities.get("imported_snapshot")
    if not isinstance(manifest, dict):
        return None
    return {
        key: manifest.get(key)
        for key in ("captured_at", "source_cutoffs", "snapshot_digest", "label")
    }


def summary(session: Session, identity: Identity, query: ReportQuery) -> dict:
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    meta = _meta(session, identity, query, revision, records, undated)
    tenant = session.get(Tenant, identity.tenant_id)
    capabilities = tenant.capabilities or {}
    demo = bool(capabilities.get("demo", True))
    imported = _imported_snapshot(capabilities)
    demo_period = None
    if demo or imported:
        # Fixture and imported data have a fixed date range; saying when it is
        # beats leaving a first-time user with an empty period and no
        # explanation.
        window = session.execute(
            select(
                func.min(ResourceLifetime.observed_start),
                func.max(ResourceLifetime.observed_end),
            ).where(ResourceLifetime.tenant_id == identity.tenant_id)
        ).first()
        if window and window[0] and window[1]:
            demo_period = {"from": window[0].isoformat(), "to": window[1].isoformat()}
    infra = infrastructure(
        session, identity, query, revision=revision, snapshot_validated=True
    ) if identity.can_view_infrastructure else None
    launch = infra["current_launch"] if infra else None
    return {
        **meta, "amount": meta["priced_subtotal"], "job_count": len(records),
        "priced_job_count": meta["coverage"]["priced"],
        "unpriced_job_count": meta["coverage"]["incomplete"],
        "known_zero_job_count": meta["coverage"]["known_zero"],
        **_repeated_work(records),
        "baseline_infrastructure_amount": infra["amount"] if infra else None,
        "baseline_infrastructure_observed": infra["observed_coverage"] if infra else None,
        "current_launch": launch,
        "can_view_infrastructure": identity.can_view_infrastructure,
        "demo": demo,
        "demo_period": demo_period,
        "imported_snapshot": imported,
    }


def _sorted(records: list[dict], query: ReportQuery) -> list[dict]:
    known = [r for r in records if r[query.sort] is not None]
    missing = [r for r in records if r[query.sort] is None]
    known.sort(key=lambda r: (r[query.sort], r["id"]), reverse=query.direction == "desc")
    return known + sorted(missing, key=lambda r: r["id"])


WORKFLOW_ORIGIN = "workflow"
INDIVIDUAL_ORIGIN = "individual"
UNKNOWN_ORIGIN = "unknown"


@dataclass
class JobOrigin:
    """What the record says about where a job came from."""

    kind: str
    # The root runs that hold the job, earliest first; empty unless `kind` is a workflow.
    runs: list[Invocation]


def job_origins(session: Session, identity: Identity, jobs: list) -> dict[uuid.UUID, JobOrigin]:
    """Whether a recorded workflow run contains each job, decided as Overview decides it.

    A job is part of a workflow when an authorized root run holds it through
    ownership-consistent memberships, as `_invocation_job_sets` builds them.
    It is individual only when nothing recorded says otherwise. A membership
    that cannot be traced to a run the viewer may see, or a run of the job's
    owner that was still adding jobs when it was submitted, leaves the origin
    unknown rather than claiming the job was launched on its own.
    """
    if not jobs:
        return {}
    by_id = {inv.id: inv for inv in _authorized_invocations(session, identity)}

    def root_of(invocation_id: uuid.UUID) -> Invocation | None:
        seen: set[uuid.UUID] = set()
        current = by_id.get(invocation_id)
        while current is not None and current.id not in seen:
            if current.parent_id is None:
                return current
            seen.add(current.id)
            current = by_id.get(current.parent_id)
        return None

    ids = [job.id for job in jobs]
    held: dict[uuid.UUID, dict[uuid.UUID, Invocation]] = defaultdict(dict)
    linked: set[uuid.UUID] = set()
    for invocation_id, job_id, consistent in session.execute(
        select(InvocationJob.invocation_id, InvocationJob.job_id, Job.owner_id == Invocation.owner_id)
        .join(Invocation, InvocationJob.invocation_id == Invocation.id)
        .join(Job, InvocationJob.job_id == Job.id)
        .where(InvocationJob.job_id.in_(ids), Invocation.tenant_id == identity.tenant_id)
    ):
        linked.add(job_id)
        root = root_of(invocation_id) if consistent else None
        if root is not None:
            held[job_id][root.id] = root
    unsettled: dict[uuid.UUID, datetime] = {}
    for inv in by_id.values():
        if not inv.membership_settled:
            earliest = unsettled.get(inv.owner_id)
            unsettled[inv.owner_id] = inv.created_at if earliest is None else min(earliest, inv.created_at)
    origins = {}
    for job in jobs:
        pending = unsettled.get(job.owner_id)
        if job.id in held:
            runs = sorted(held[job.id].values(), key=lambda inv: (inv.created_at, inv.id))
            origins[job.id] = JobOrigin(WORKFLOW_ORIGIN, runs)
        elif job.id in linked or (pending is not None and pending <= job.created_at):
            origins[job.id] = JobOrigin(UNKNOWN_ORIGIN, [])
        else:
            origins[job.id] = JobOrigin(INDIVIDUAL_ORIGIN, [])
    return origins


def _job_summaries(session: Session, identity: Identity, records: list[dict], as_of: datetime) -> list[dict]:
    """Public rows with the facts a job list states beside each cost, read in bulk."""
    origins = job_origins(session, identity, [record["job"] for record in records])
    rows = []
    for record in records:
        resourced = {
            attempt.id for users in record["lifetime_attempts"].values() for attempt in users
        }
        span = _execution_span(record, resourced, as_of)
        origin = origins[record["job"].id]
        first = origin.runs[0] if origin.runs else None
        rows.append({
            **_public(record), "origin": origin.kind,
            # The run the job is named under, and how many other runs also hold it.
            "origin_run": {"id": str(first.id), "workflow_name": first.workflow_name} if first else None,
            "origin_run_count": len(origin.runs),
            "duration_seconds": span["duration_seconds"], "duration_running": span["duration_running"],
        })
    return rows


def list_jobs(session: Session, identity: Identity, query: ReportQuery, paginate: bool = True) -> dict:
    if query.sort not in SORT_FIELDS:
        raise HTTPException(422, f"Unsupported sort field: {query.sort}")
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    records = _sorted(records, query)
    undated_page = _sorted(undated, query)[query.undated_offset:query.undated_offset + query.limit]
    if paginate:
        as_of = revision.created_at if revision else datetime.now(UTC)
        items = _job_summaries(session, identity, records[query.offset:query.offset + query.limit], as_of)
        undated_items = _job_summaries(session, identity, undated_page, as_of)
    else:
        items = [_public(r) for r in records]
        undated_items = [_public(r) for r in undated_page]
    return {
        "items": items, "total": len(records),
        "limit": query.limit, "offset": query.offset,
        # Outside every period's totals, but still inspectable beside them.
        "undated_items": undated_items,
        "undated_offset": query.undated_offset,
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def _execution_duration(
    attempt: ExecutionAttempt, running: bool, as_of: datetime
) -> tuple[int | None, bool]:
    """How long one execution ran, and whether that is elapsed so far.

    An execution that finished before it started, or that never recorded its
    end once the job is over, has no duration.
    """
    start, finish = attempt.tool_started_at, attempt.tool_finished_at
    if start is None:
        return None, False
    ongoing = finish is None and running
    finish = as_of if ongoing else finish
    if finish is None or finish < start:
        return None, False
    return int((finish - start).total_seconds()), ongoing


def _timing_issue(created_at: datetime | None, executions: list[ExecutionAttempt]) -> str | None:
    """A recording fault that leaves some of a job's timing unavailable."""
    if any(
        attempt.tool_started_at and attempt.tool_finished_at
        and attempt.tool_finished_at < attempt.tool_started_at
        for attempt in executions
    ):
        return "finished_before_started"
    if created_at and any(
        attempt.tool_started_at and attempt.tool_started_at < created_at for attempt in executions
    ):
        return "started_before_submitted"
    return None


def job_detail(session: Session, identity: Identity, job_id: uuid.UUID, query: ReportQuery) -> dict | None:
    """One job, its whole cost and everything the drawer explains it with.

    The period's records decide whether the viewer may see the job and what
    part of it falls in the period. Everything else, from resources and
    executions to measured use, is built from the job's whole record, so a
    whole-job headline is never shown beside period-only evidence.
    """
    unrestricted = query.model_copy(update={
        "search": None, "tool_id": None, "tool_version": None, "tool_key": None, "invocation_id": None,
        "min_cost": None, "max_cost": None, "quality": None,
    })
    facts = _load_job_facts(session, identity, unrestricted, lifetime_facts=True, only_job=job_id)
    undated: list[dict] = []
    records = _records_from_facts(facts, unrestricted, undated)
    record = next((r for r in [*records, *undated] if r["id"] == str(job_id)), None)
    if not record:
        return None
    whole = unrestricted.model_copy(update={"from_time": None, "to_time": None})
    full = next(r for r in _records_from_facts(facts, whole) if r["id"] == str(job_id))
    revision, as_of = facts.revision, facts.as_of
    lifetime_attempts = full["lifetime_attempts"]
    resources = []
    charged_alone: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for line, lifetime in full["pairs"]:
        sharing = sorted(
            lifetime_attempts.get(lifetime.id, []), key=lambda value: value.source_attempt_id
        )
        entry = {
            "lifetime_id": str(lifetime.id),
            "resource_key": lifetime.resource_key,
            "resource_uid": lifetime.resource_uid,
            "provider": lifetime.provider,
            "machine_type": lifetime.machine_type,
            "machine_capacity": machine_capacity(lifetime.provider, lifetime.machine_type),
            "region": lifetime.region,
            "zone": lifetime.zone,
            "purchase_model": lifetime.purchase_model,
            "capacity_relationship": lifetime.capacity_relationship.value,
            "resource_started_at": lifetime.observed_start,
            "resource_finished_at": lifetime.observed_end,
            "timing_method": lifetime.timing_method,
            "requested_vcpu": _money(lifetime.requested_vcpu) if lifetime.requested_vcpu is not None else None,
            "requested_memory_mib": (
                _money(lifetime.requested_memory_mib)
                if lifetime.requested_memory_mib is not None
                else None
            ),
            "provisioned": lifetime.facts,
            "amount": _money(line.amount) if line.amount is not None else None,
            "quality": _quality([line]),
            "reason": line.reason,
            "provenance": line.details,
            "shared_attempt_ids": [str(attempt.id) for attempt in sharing],
            "shared_attempt_count": len(sharing),
        }
        resources.append(entry)
        if len(sharing) == 1:
            charged_alone[sharing[0].id].append(entry)
    resourced = {attempt.id for users in lifetime_attempts.values() for attempt in users}
    first, repeats, _ = _executions(full["attempts"], resourced)
    executions = [*first, *repeats]
    roles = {attempt.id: "first" for attempt in first} | {attempt.id: "repeat" for attempt in repeats}
    running = full["state"] in EXECUTING_STATES
    attempts = []
    for attempt in full["attempts"]:
        used = [
            entry for entry in resources
            if str(attempt.id) in entry["shared_attempt_ids"]
        ]
        alone = charged_alone.get(attempt.id, [])
        duration, ongoing = _execution_duration(attempt, running, as_of)
        attempts.append({
            "id": str(attempt.id), "source_attempt_id": attempt.source_attempt_id,
            "runner": attempt.runner, "outcome": attempt.outcome,
            "provider_outcome": attempt.provider_outcome, "exit_code": attempt.exit_code,
            "task_index": attempt.task_index, "attempt_ordinal": attempt.attempt_ordinal,
            "tool_started_at": attempt.tool_started_at,
            "tool_finished_at": attempt.tool_finished_at,
            "duration_seconds": duration, "duration_running": ongoing,
            # An observation describes an execution counted under another row.
            "role": roles.get(attempt.id, "observation"),
            "resource_keys": [entry["resource_key"] for entry in used],
            # A lifetime shared by retries is charged once; its amount appears
            # on the resource, not repeated on each attempt row. An attempt
            # that was the sole user of several resources owns all of them.
            "amount": (
                _money(sum((Decimal(entry["amount"]) for entry in alone), ZERO))
                if alone and all(entry["amount"] is not None for entry in alone) else None
            ),
            "amount_shared_with_attempts": [
                other for entry in used for other in entry["shared_attempt_ids"]
                if len(entry["shared_attempt_ids"]) > 1 and other != str(attempt.id)
            ],
        })
    span = _execution_span(full, resourced, as_of)
    before_start = None
    if span["started_at"] and full["created_at"]:
        waited = (span["started_at"] - full["created_at"]).total_seconds()
        before_start = int(waited) if waited >= 0 else None
    metrics = {
        (row.plugin, row.name): row.numeric_value
        for row in session.execute(
            select(JobMetric.plugin, JobMetric.name, JobMetric.numeric_value).where(
                JobMetric.job_id == full["job"].id
            )
        )
    }
    result = _public(record)
    result.update({
        "interval_amount": result["amount"],
        "full_job_amount": _money(full["amount"]) if full["amount"] is not None else None,
        "full_quality": full["quality"], "full_reason": full["reason"],
        "full_capacities": full["capacities"],
        "started_at": span["started_at"], "finished_at": span["finished_at"],
        "duration_seconds": span["duration_seconds"], "duration_running": span["duration_running"],
        "duration_cutoff": as_of if span["duration_running"] else None,
        "before_start_seconds": before_start,
        "timing_issue": _timing_issue(full["created_at"], executions),
        "basis": query.basis, "attempts": attempts, "resources": resources,
        "resource_use": job_resource_use(
            metrics, running=running,
            executions=[(a.tool_started_at, a.tool_finished_at) for a in executions],
            resources=resources,
        ),
        "revision_id": str(revision.id) if revision else None,
    })
    result["cost"] = {
        "basis": query.basis, "amount": result["interval_amount"], "currency": "USD",
        "quality": result["quality"], "reason": result["reason"],
        "attempts": attempts, "resources": resources,
    }
    return result


def tool_statistics(rows: list[dict]) -> dict:
    """What past complete, successful jobs of a tool cost; a description, not a prediction."""
    complete_rows = [
        r for r in rows
        if r["state"] == "ok" and r["full_amount"] is not None
        and r["quality"] not in INCOMPLETE_QUALITIES
    ]
    values = sorted(r["full_amount"] for r in complete_rows)
    if values:
        position = Decimal("0.95") * Decimal(len(values) - 1)
        lower = int(position)
        fraction = position - lower
        p95 = values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * fraction
    else:
        p95 = None
    return {
        "cohort": "complete successful jobs", "sample_count": len(values),
        "excluded_count": len(rows) - len(values),
        "mean": _money(statistics.mean(values)) if values else None,
        "median": _money(statistics.median(values)) if values else None,
        "p95": _money(p95) if p95 is not None else None,
        "method": "continuous linear interpolation (R-7)",
        "approximate": any(r["quality"] == "approximate" for r in complete_rows),
    }


def tools(session: Session, identity: Identity, query: ReportQuery) -> dict:
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    groups: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["tool_id"], record["tool_version"])].append(record)
    items = []
    for (tool_id, version), rows in groups.items():
        known = [r["amount"] for r in rows if r["amount"] is not None]
        items.append({
            "tool_id": tool_id, "tool_name": tool_display_name(tool_id),
            "tool_version": version, "job_count": len(rows),
            "amount": _money(sum(known, ZERO)) if known else None, "priced_count": len(known),
            "incomplete_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in rows),
            "statistics": tool_statistics(rows),
        })
    items.sort(key=lambda x: (
        x["amount"] is None, -(Decimal(x["amount"]) if x["amount"] else ZERO),
        x["tool_id"], x["tool_version"] or "",
    ))
    return {
        "items": items[query.offset:query.offset + query.limit], "total": len(items),
        "limit": query.limit, "offset": query.offset,
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def _run_status(invocation_state: str, rows: list[dict]) -> str:
    """A run's status, derived from its executions rather than its scheduling.

    A scheduled invocation has only finished *scheduling*; its tool executions
    may still be running or may have failed.
    """
    states = {row["state"] for row in rows}
    if invocation_state in {"cancelled", "cancelling"}:
        return "cancelled"
    if states & {"error", "failed"}:
        return "failed"
    if invocation_state == "failed":
        return "failed"
    if states & RUNNING_STATES or invocation_state not in {"scheduled", "completed", "ok"}:
        return "running"
    if not rows:
        return "no runs recorded"
    return "completed"


def _money(value: Decimal | None) -> str | None:
    """An exact decimal string; null stays unknown rather than becoming zero."""
    return None if value is None else format(value, "f")


def _sum_known(values: Iterable[Decimal | None]) -> Decimal | None:
    known = [value for value in values if value is not None]
    return sum(known, ZERO) if known else None


@dataclass
class _RunSet:
    """Every run the shared filters admit, before any page filter narrows them."""

    runs: list[dict]
    records: list[dict]
    record_by_job: dict[uuid.UUID, dict]
    undated: list[dict]
    revision: CostRevision | None
    as_of: datetime


@dataclass
class _Matching:
    """The runs every page filter admits, with each shared job assigned once."""

    run_set: _RunSet
    runs: list[dict]
    # The matching root each job's cost is drawn under in the charts.
    assigned: dict[uuid.UUID, uuid.UUID]
    sharing: dict[uuid.UUID, int]


def _invocation_job_sets(
    session: Session, identity: Identity
) -> tuple[list[Invocation], dict[uuid.UUID, set[uuid.UUID]]]:
    """Each authorized invocation with its own jobs and those of every descendant.

    A root run's jobs include the jobs of its child workflows, once, so a job
    reachable through several nested memberships is one job of the root.
    """
    authorized = _authorized_invocations(session, identity)
    by_id = {inv.id: inv for inv in authorized}
    # A malformed cross-owner membership cannot expand a viewer's authorized cohort.
    statement = (
        select(InvocationJob.invocation_id, InvocationJob.job_id)
        .join(Invocation, InvocationJob.invocation_id == Invocation.id)
        .join(Job, InvocationJob.job_id == Job.id)
        .where(
            Invocation.tenant_id == identity.tenant_id,
            Job.tenant_id == identity.tenant_id,
            Job.owner_id == Invocation.owner_id,
        )
    )
    if not identity.is_admin:
        statement = statement.where(Invocation.owner_id == identity.owner_id)
    own: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for invocation_id, job_id in session.execute(statement):
        own[invocation_id].add(job_id)
    sets = {inv.id: set(own.get(inv.id, ())) for inv in authorized}
    for inv in authorized:
        jobs = own.get(inv.id)
        if not jobs:
            continue
        seen = {inv.id}
        ancestor = inv.parent_id
        while ancestor in by_id and ancestor not in seen:
            seen.add(ancestor)
            sets[ancestor] |= jobs
            ancestor = by_id[ancestor].parent_id
    return authorized, sets


def _job_amount(record: dict, query: ReportQuery) -> Decimal | None:
    """A job's cost inside the report period, as runs count it.

    Without a date range the period is all time, so cost with no usable timing
    belongs to it: it is then part of the job's amount, not set beside it.
    """
    amount = record["amount"]
    if amount is None or query.from_time or query.to_time or query.mode != "accrued":
        return amount
    return amount + record["unattributed_amount"]


JOB_FILTERS = (
    "tool_id", "tool_version", "tool_key", "state", "runner", "destination", "capacity", "quality",
    "min_cost", "max_cost", "owner",
)


def _run_records(
    session: Session, identity: Identity, query: RunReportQuery, roots_only: bool = True
) -> _RunSet:
    """One record per run: identity, status, timing, period share and whole-run total.

    Job-level filters shape the jobs a run is made of; the workflow and run
    selections in the query pick which runs are admitted here. Search and the
    run-only filters are page filters and are applied by `_select_runs`.
    """
    job_query = query.model_copy(update={"search": None, "invocation_id": None, "workflow_id": None})
    facts = _load_job_facts(session, identity, job_query, within_runs=True)
    undated: list[dict] = []
    records = _records_from_facts(facts, job_query, undated)
    dated = bool(query.from_time or query.to_time)
    full_records = _records_from_facts(
        facts, job_query.model_copy(update={"from_time": None, "to_time": None})
    ) if dated else records
    by_id = {uuid.UUID(r["id"]): r for r in records}
    full_by_id = {uuid.UUID(r["id"]): r for r in full_records}
    authorized, job_sets = _invocation_job_sets(session, identity)
    filtered_jobs = any(getattr(query, name) not in (None, "") for name in JOB_FILTERS)
    requested_id: uuid.UUID | None = None
    if query.invocation_id:
        try:
            requested_id = uuid.UUID(query.invocation_id)
        except ValueError:
            requested_id = None
    runs: list[dict] = []
    for inv in sorted(authorized, key=lambda value: value.created_at, reverse=True):
        if roots_only and inv.parent_id is not None:
            continue
        if query.invocation_id and (
            inv.id != requested_id if requested_id else inv.source_id != query.invocation_id
        ):
            continue
        if query.workflow_id and (inv.workflow_id or inv.source_id) != query.workflow_id:
            continue
        job_ids = job_sets[inv.id]
        rows = [by_id[job_id] for job_id in job_ids if job_id in by_id]
        full_rows = [full_by_id[job_id] for job_id in job_ids if job_id in full_by_id]
        started_at = min((row["created_at"] for row in full_rows), default=inv.created_at)
        # A dated report lists the runs that used compute in the period. A run
        # whose jobs have no usable timing belongs to no period; its jobs are
        # reported beside the period as undated work instead.
        if not rows and (filtered_jobs or dated):
            continue
        amounts = {uuid.UUID(row["id"]): _job_amount(row, job_query) for row in rows}
        amount = _sum_known(amounts.values())
        run_total = _sum_known(row["full_amount"] for row in full_rows)
        unpriced = sum(row["quality"] in INCOMPLETE_QUALITIES for row in full_rows)
        status = _run_status(inv.state, full_rows)
        finishes = [
            attempt.tool_finished_at for row in full_rows
            for attempt in row["attempts"] if attempt.tool_finished_at
        ]
        finished_at = None if status == "running" or not finishes else max(finishes)
        ends_at = facts.as_of if status == "running" else finished_at
        runs.append({
            "id": str(inv.id), "source_id": inv.source_id,
            "workflow_id": inv.workflow_id or inv.source_id,
            "workflow_key": inv.workflow_family_id or inv.workflow_id or inv.workflow_name,
            "workflow_name": inv.workflow_name, "workflow_version": inv.workflow_version,
            "parent_id": str(inv.parent_id) if inv.parent_id else None, "state": inv.state,
            "run_status": status,
            "started_at": started_at, "finished_at": finished_at,
            "duration_seconds": (
                int(max(0.0, (ends_at - started_at).total_seconds())) if ends_at else None
            ),
            "job_count": len(rows),
            "run_job_count": len(full_rows),
            # The period's share of this run, and the run as a whole.
            "amount": _money(amount),
            "run_total": _money(run_total),
            "run_total_complete": unpriced == 0 and bool(full_rows),
            "currency": "USD",
            "unpriced_job_count": sum(row["quality"] in INCOMPLETE_QUALITIES for row in rows),
            "run_unpriced_job_count": unpriced,
            "reused_job_count": sum(bool(row["job"].copied_from_source_id) for row in full_rows),
            "timing_unavailable": bool(full_rows) and all(
                row["temporally_unattributed"] for row in full_rows
            ),
            "chart_amount": None, "shared_job_count": 0,
            "_id": inv.id, "_amount": amount, "_run_total": run_total, "_amounts": amounts,
            "_rows": rows, "_full_rows": full_rows, "_job_ids": job_ids,
            "_search": f"{inv.source_id} {inv.workflow_id or ''} {inv.workflow_name}".casefold(),
            "_focus_hit": None,
        })
    return _RunSet(runs, records, by_id, undated, facts.revision, facts.as_of)


def _active_in_focus(run: dict, query: RunReportQuery, as_of: datetime) -> bool:
    """Whether any of the run's jobs has timing inside the focus window."""
    if run["_focus_hit"] is None:
        window = query.model_copy(update={"from_time": query.focus_from, "to_time": query.focus_to})
        hit = False
        for record in run["_rows"]:
            if query.mode == "completed":
                completed_at = record["completed_at"]
                hit = bool(completed_at) and query.focus_from <= completed_at < query.focus_to
            else:
                hit = any(
                    _slice_fraction(start, end, window) > 0
                    for line, lifetime in record["pairs"]
                    for start, end, _ in _line_slices(line, lifetime, as_of)
                )
            if hit:
                break
        run["_focus_hit"] = hit
    return run["_focus_hit"]


def _select_runs(
    run_set: _RunSet, query: RunReportQuery, *, ignoring: str | None = None
) -> list[dict]:
    """The runs that match every page filter.

    `ignoring` names one control, `run_status` or `workflow_key`, whose own
    choice is set aside to see what else it could select. The grouped bounds
    describe the grouping that choice produced, so they are set aside with it.
    """
    term = (query.search or "").casefold()
    boundary = uuid.UUID(query.boundary_run_id) if query.boundary_run_id else None
    selected = []
    for run in run_set.runs:
        if term and term not in run["_search"]:
            continue
        if query.workflow_key and ignoring != "workflow_key" and run["workflow_key"] != query.workflow_key:
            continue
        if query.run_status and ignoring != "run_status" and run["run_status"] != query.run_status:
            continue
        if query.focus_from and not _active_in_focus(run, query, run_set.as_of):
            continue
        if boundary is not None and ignoring is None:
            amount = run["_amount"]
            if amount is None or not (
                amount < query.max_run_amount
                or (amount == query.max_run_amount and run["_id"] >= boundary)
            ):
                continue
        selected.append(run)
    return selected


def _matching_runs(
    session: Session, identity: Identity, query: RunReportQuery
) -> _Matching:
    run_set = _run_records(session, identity, query)
    runs = _select_runs(run_set, query)
    assigned, sharing = _attribute_shared_jobs(runs)
    return _Matching(run_set, runs, assigned, sharing)


def _attribute_shared_jobs(
    runs: list[dict],
) -> tuple[dict[uuid.UUID, uuid.UUID], dict[uuid.UUID, int]]:
    """Draw each job's cost under one matching root, so charts add up to the card.

    The root with the lowest UUID takes a shared job. This is a display rule,
    not a claim about which run caused the work, and it changes only
    `chart_amount` and `shared_job_count`: a run's own amount and whole-run
    total keep counting every job it contains.
    """
    assigned: dict[uuid.UUID, uuid.UUID] = {}
    sharing: dict[uuid.UUID, int] = defaultdict(int)
    for run in runs:
        for job_id in run["_amounts"]:
            sharing[job_id] += 1
            if job_id not in assigned or run["_id"] < assigned[job_id]:
                assigned[job_id] = run["_id"]
    for run in runs:
        run["shared_job_count"] = sum(sharing[job_id] > 1 for job_id in run["_amounts"])
        run["_chart_amount"] = None
        if run["_amount"] is not None:
            run["_chart_amount"] = _sum_known(
                amount for job_id, amount in run["_amounts"].items()
                if assigned[job_id] == run["_id"]
            ) or ZERO
        run["chart_amount"] = _money(run["_chart_amount"])
    return assigned, sharing


def _run_totals(matching: _Matching, unfiltered: int) -> dict:
    runs = matching.runs
    by_status: dict[str, int] = defaultdict(int)
    for run in runs:
        by_status[run["run_status"]] += 1
    return {
        # Summed over unique jobs, so a job shared by two runs is counted once.
        "amount": _money(_sum_known(run["_chart_amount"] for run in runs)),
        "incomplete_run_count": sum(run["unpriced_job_count"] > 0 for run in runs),
        "shared_job_count": sum(count > 1 for count in matching.sharing.values()),
        "run_count": len(runs),
        "by_status": dict(by_status),
        "workflow_count": len({run["workflow_key"] for run in runs}),
        "unfiltered_run_count": unfiltered,
    }


def _filter_options(run_set: _RunSet, query: RunReportQuery) -> dict:
    """What each sidebar control could select if its own choice were cleared."""
    by_status: dict[str, int] = defaultdict(int)
    for run in _select_runs(run_set, query, ignoring="run_status"):
        by_status[run["run_status"]] += 1
    if query.run_status:
        by_status.setdefault(query.run_status, 0)
    workflows: dict[str, dict] = {}
    for run in sorted(
        _select_runs(run_set, query, ignoring="workflow_key"), key=lambda value: value["started_at"]
    ):
        entry = workflows.setdefault(
            run["workflow_key"], {"key": run["workflow_key"], "name": "", "run_count": 0}
        )
        # A workflow that was renamed is called by its newest name.
        entry["name"] = run["workflow_name"]
        entry["run_count"] += 1
    if query.workflow_key and query.workflow_key not in workflows:
        known = next((run for run in run_set.runs if run["workflow_key"] == query.workflow_key), None)
        workflows[query.workflow_key] = {
            "key": query.workflow_key, "run_count": 0,
            "name": known["workflow_name"] if known else query.workflow_key,
        }
    return {
        "by_status": dict(by_status),
        "workflows": sorted(workflows.values(), key=lambda value: (value["name"].casefold(), value["key"])),
    }


def _public_run(run: dict) -> dict:
    return {key: value for key, value in run.items() if not key.startswith("_")}


RUN_SORT_VALUES = {
    "started_at": lambda run: run["started_at"],
    "amount": lambda run: run["_amount"],
    "run_total": lambda run: run["_run_total"],
    "duration": lambda run: run["duration_seconds"],
}


def _sort_runs(runs: list[dict], query: RunReportQuery) -> list[dict]:
    value = RUN_SORT_VALUES[query.run_sort]
    known = [run for run in runs if value(run) is not None]
    missing = [run for run in runs if value(run) is None]
    known.sort(key=lambda run: (value(run), run["id"]), reverse=query.direction == "desc")
    return known + sorted(missing, key=lambda run: run["id"])


def _run_meta(session: Session, identity: Identity, query: RunReportQuery, run_set: _RunSet) -> dict:
    return _meta(session, identity, query, run_set.revision, run_set.records, run_set.undated)


def invocations(session: Session, identity: Identity, query: ReportQuery) -> dict:
    """Workflow runs, with a full-run total beside the selected period's cost.

    "What did this run cost?" and "what did I spend last week?" are different
    questions: the run total covers the whole run, while the period amount is
    the part accrued inside the selected interval. `totals` and
    `filter_options` describe the whole filtered set, never the page.
    """
    query = as_run_query(query)
    matching = _matching_runs(session, identity, query)
    ordered = _sort_runs(matching.runs, query)
    return {
        "items": [_public_run(run) for run in ordered[query.offset:query.offset + query.limit]],
        "total": len(ordered), "limit": query.limit, "offset": query.offset,
        "totals": _run_totals(matching, len(matching.run_set.runs)),
        "filter_options": _filter_options(matching.run_set, query),
        "meta": _run_meta(session, identity, query, matching.run_set),
    }


def invocation_detail(
    session: Session, identity: Identity, invocation_id: uuid.UUID, query: ReportQuery
) -> dict | None:
    query = as_run_query(query).model_copy(update={"invocation_id": None, "workflow_id": None})
    run_set = _run_records(session, identity, query, roots_only=False)
    item = next((run for run in run_set.runs if run["id"] == str(invocation_id)), None)
    if not item:
        return None
    composition = _run_composition(session, identity, invocation_id, item, run_set)
    item = _public_run(item)
    item.update(composition)
    item["children"] = [
        _public_run(run) for run in run_set.runs if run["parent_id"] == str(invocation_id)
    ]
    item["meta"] = _run_meta(session, identity, query, run_set)
    return item


def _step_order(step_key: str) -> tuple[int, tuple[int, ...]]:
    """Galaxy's numeric step keys compare as numbers, so step 10 follows step 2.

    A key that is not numeric says nothing about order and sorts after those
    that do; such jobs are then ordered by when they were submitted.
    """
    parts = step_key.split(":")
    if all(part.isdigit() for part in parts):
        return 0, tuple(int(part) for part in parts)
    return 1, ()


def _execution_span(
    record: dict, resourced: set[uuid.UUID], as_of: datetime
) -> dict:
    """When a job's tool actually ran, and for how long.

    The duration is the union of its executions' observed intervals: neither
    queue time, nor the time a resource was held, nor the overlap of parallel
    attempts counts twice. A job that never started has none, and neither does
    a finished job with an execution whose end was never recorded or was
    recorded before its start.
    """
    none = {"started_at": None, "finished_at": None, "duration_seconds": None, "duration_running": False}
    if record["state"] in UNSTARTED_STATES:
        return none
    first, repeats, _ = _executions(record["attempts"], resourced)
    running = record["state"] in EXECUTING_STATES
    intervals: list[tuple[datetime, datetime]] = []
    open_ended = False
    for attempt in [*first, *repeats]:
        start = attempt.tool_started_at
        if start is None:
            continue
        finish = attempt.tool_finished_at
        if finish is None:
            if not running:
                return none
            finish, open_ended = as_of, True
        if finish < start:
            # A finish before its start is a recording fault, not a zero-length run.
            return none
        intervals.append((start, finish))
    if not intervals:
        return none
    intervals.sort()
    total = 0.0
    current_start, current_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += (current_end - current_start).total_seconds()
            current_start, current_end = start, end
    total += (current_end - current_start).total_seconds()
    return {
        "started_at": intervals[0][0],
        "finished_at": None if open_ended else max(end for _, end in intervals),
        "duration_seconds": int(total), "duration_running": open_ended,
    }


def _environment(capacities: list[str]) -> str:
    """The one verified execution environment of a job, or that it has several."""
    if not capacities:
        return "unknown"
    return capacities[0] if len(capacities) == 1 else "multiple"


def _run_composition(
    session: Session, identity: Identity, invocation_id: uuid.UUID, run: dict, run_set: _RunSet
) -> dict:
    """Every job of the whole run, and the cost entities that produced its cost.

    Both describe the run as a whole: nested workflows included, once, and
    whatever period is selected. The jobs are the same records the run's
    headline total sums, so a breakdown built from them reconciles with it.
    Membership and money are separate: a job may belong to several steps, and
    a charge belongs to one entity however many jobs point at it.
    """
    rows = run["_full_rows"]
    tree = {invocation_id}
    authorized = _authorized_invocations(session, identity)
    names = {inv.id: inv.workflow_name for inv in authorized}
    grew = True
    while grew:
        grew = False
        for inv in authorized:
            if inv.parent_id in tree and inv.id not in tree:
                tree.add(inv.id)
                grew = True
    steps: dict[uuid.UUID, dict[tuple, dict]] = defaultdict(dict)
    unavailable_steps: set[tuple] = set()
    for membership in session.scalars(
        select(InvocationJob).where(InvocationJob.invocation_id.in_(tree))
    ):
        if membership.job_id not in run["_job_ids"]:
            unavailable_steps.add((membership.invocation_id, membership.step_key))
            continue
        steps[membership.job_id][(membership.invocation_id, membership.step_key)] = {
            "invocation_id": str(membership.invocation_id),
            "workflow_name": names.get(membership.invocation_id, ""),
            "step_key": membership.step_key, "relationship": membership.relationship,
            "nested": membership.invocation_id != invocation_id,
        }
    # Every record shares one map of resource users, so it is read once.
    resourced = {
        attempt.id for users in rows[0]["lifetime_attempts"].values() for attempt in users
    } if rows else set()

    def order_key(row: dict) -> tuple:
        memberships = steps.get(row["job"].id, {}).values()
        earliest = min((_step_order(m["step_key"]) for m in memberships), default=(2, ()))
        return earliest, row["created_at"], len(row["source_id"]), row["source_id"], row["id"]

    jobs: list[dict] = []
    entities: list[dict] = []
    for order, row in enumerate(sorted(rows, key=order_key), start=1):
        amount = row["full_amount"]
        environment = _environment(row["capacities"])
        if amount is None:
            attribution = "unknown"
        elif amount > 0:
            attribution = "individual"
        elif amount == 0:
            attribution = "known_zero"
        else:
            attribution = "unsupported"
        entity_id = f"job:{row['id']}" if amount is not None and amount != 0 else None
        if entity_id:
            entities.append({
                "id": entity_id, "kind": "batch_job", "amount": _money(amount),
                "currency": "USD", "scope": "run", "environment": environment,
                "complete": row["quality"] not in INCOMPLETE_QUALITIES,
                "job_ids": [row["id"]],
            })
        membership_list = sorted(
            steps.get(row["job"].id, {}).values(),
            key=lambda m: (m["nested"], _step_order(m["step_key"]), m["step_key"]),
        )
        jobs.append({
            "id": row["id"], "source_id": row["source_id"], "tool_id": row["tool_id"],
            "tool_name": row["tool_name"], "tool_version": row["tool_version"],
            "state": row["state"], "quality": row["quality"],
            "amount": _money(amount), "attribution": attribution,
            "environment": environment, "capacities": row["capacities"],
            "cost_entity_id": entity_id, "created_at": row["created_at"],
            **_execution_span(row, resourced, run_set.as_of),
            "attempt_count": row["attempt_count"],
            "reused": bool(row["job"].copied_from_source_id),
            "order": order, "steps": membership_list,
        })
    positive = sum((Decimal(e["amount"]) for e in entities if Decimal(e["amount"]) > 0), ZERO)
    subtotal = run["_run_total"]
    reason = None
    if any(not Decimal(e["amount"]).is_finite() or Decimal(e["amount"]) < 0 for e in entities):
        reason = "Some amounts are adjustments that a breakdown cannot show."
    elif subtotal is not None and positive != subtotal:
        reason = "The parts do not add up to the run total."
    return {
        "jobs": jobs, "cost_entities": entities,
        "cost_breakdown": {
            "status": "unavailable" if reason else "available", "reason": reason,
            "currency": "USD", "known_subtotal": _money(subtotal),
            "complete": run["run_total_complete"],
            "job_count": len(jobs), "cost_entity_count": len(entities),
            "known_zero_job_count": sum(job["attribution"] == "known_zero" for job in jobs),
            "unknown_job_count": sum(job["attribution"] == "unknown" for job in jobs),
        },
        "unavailable_step_count": len(unavailable_steps),
    }


# Runs drawn individually per workflow and pieces drawn individually per time
# bucket; the rest are folded into one remainder the client draws as a segment.
BREAKDOWN_RUN_LIMIT = 200
TIMELINE_PIECE_LIMIT = 60


def _fold(runs: list[dict], amounts: list[Decimal | None]) -> dict:
    return {
        "count": len(runs),
        "amount": _money(_sum_known(amounts) or ZERO),
        "failed": sum(run["run_status"] == "failed" for run in runs),
        "running": sum(run["run_status"] == "running" for run in runs),
    }


def _whole_run_range(runs: list[dict]) -> dict:
    """The cheapest and priciest finished run, judged by whole-run totals.

    Runs that are still running, incomplete or have no known total say nothing
    reliable about what a whole run costs, so they are counted, not ranged.
    """
    eligible = [
        run["_run_total"] for run in runs
        if run["run_status"] != "running" and run["run_total_complete"]
        and run["_run_total"] is not None
    ]
    return {
        "minimum": _money(min(eligible)) if eligible else None,
        "maximum": _money(max(eligible)) if eligible else None,
        "included_run_count": len(eligible),
        "excluded_run_count": len(runs) - len(eligible),
    }


def _by_amount_then_id(run: dict) -> tuple:
    return (-run["_amount"], run["_id"])


def _group_by_workflow(runs: list[dict]) -> list[dict]:
    """Group matching runs by stored workflow for the By workflow chart.

    Each group lists up to `BREAKDOWN_RUN_LIMIT` runs with known period amounts,
    largest first with ties broken by run UUID. The rest fold into a remainder
    whose boundary is the first folded run's exact amount and ID, so a client
    can select precisely the folded runs even when many share one amount.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        grouped[run["workflow_key"]].append(run)
    groups = []
    for key, members in grouped.items():
        priced = sorted((run for run in members if run["_amount"] is not None), key=_by_amount_then_id)
        shown, folded = priced[:BREAKDOWN_RUN_LIMIT], priced[BREAKDOWN_RUN_LIMIT:]
        remainder = _fold(folded, [run["_chart_amount"] for run in folded])
        remainder["boundary"] = {
            "amount": _money(folded[0]["_amount"]), "run_id": folded[0]["id"],
        } if folded else None
        newest = max(members, key=lambda run: run["started_at"])
        groups.append({
            "key": key, "name": newest["workflow_name"], "run_count": len(members),
            "by_status": dict(Counter(run["run_status"] for run in members)),
            "_amount": _sum_known(run["_chart_amount"] for run in members),
            "incomplete_run_count": sum(run["unpriced_job_count"] > 0 for run in members),
            "runs": [{
                "id": run["id"], "amount": run["amount"], "run_total": run["run_total"],
                "chart_amount": run["chart_amount"], "shared_job_count": run["shared_job_count"],
                "run_total_complete": run["run_total_complete"], "status": run["run_status"],
                "started_at": run["started_at"], "duration_seconds": run["duration_seconds"],
            } for run in shown],
            "remainder": remainder,
            "whole_run_range": _whole_run_range(members),
        })
    groups.sort(key=lambda group: (
        group["_amount"] is None, -(group["_amount"] or ZERO), group["name"], group["key"],
    ))
    for group in groups:
        group["amount"] = _money(group.pop("_amount"))
    return groups


def breakdown(session: Session, identity: Identity, query: ReportQuery) -> dict:
    """Matching runs grouped by stored workflow, for the By workflow chart."""
    query = as_run_query(query)
    matching = _matching_runs(session, identity, query)
    groups = _group_by_workflow(matching.runs)
    return {
        "groups": groups,
        "meta": _run_meta(session, identity, query, matching.run_set),
    }


def _bucket_function(
    unit: str, timezone: ZoneInfo
) -> Callable[[datetime], tuple[datetime, datetime]]:
    """Maps an instant to its local bucket: its start and end, both in UTC.

    Buckets follow local clock time, so a day is 23 or 25 hours across a
    daylight-saving change and its hours are 23 or 25 buckets.
    """
    def bucket_of(instant: datetime) -> tuple[datetime, datetime]:
        local = instant.astimezone(timezone)
        if unit == "hour":
            start = local.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
            return start, start + timedelta(hours=1)
        first_day = local.date() - timedelta(days=local.weekday() if unit == "week" else 0)
        last_day = first_day + timedelta(days=7 if unit == "week" else 1)
        return tuple(
            datetime.combine(day, datetime.min.time(), tzinfo=timezone).astimezone(UTC)
            for day in (first_day, last_day)
        )
    return bucket_of


def _resolve_bucket(query: RunReportQuery, timezone: ZoneInfo, records: list[dict]) -> str:
    """Hours for a single local day, days up to 92, Monday-start weeks beyond."""
    if query.bucket != "auto":
        return query.bucket
    lower, upper = query.from_time, query.to_time
    if lower is None or upper is None:
        window = _window(query, records)
        lower = lower or (datetime.fromisoformat(window["from"]) if window["from"] else None)
        upper = upper or (datetime.fromisoformat(window["to"]) if window["to"] else None)
    if lower is None or upper is None:
        return "day"
    span = upper.astimezone(timezone).replace(tzinfo=None) - lower.astimezone(timezone).replace(tzinfo=None)
    days = span.total_seconds() / 86400
    return "hour" if days <= 1 else "day" if days <= 92 else "week"


def _timeline_axis(
    query: ReportQuery,
    bucket_of: Callable[[datetime], tuple[datetime, datetime]],
    timezone: ZoneInfo,
    starts: Iterable[datetime],
    ends: dict[datetime, datetime],
) -> dict | None:
    """The range a chart draws: the whole period, or the buckets when it has none.

    Empty buckets are not returned, so a client fills the axis from this range.
    """
    found = sorted(starts)
    if not found:
        return None
    first, last = found[0], found[-1]
    lower = bucket_of(query.from_time)[0] if query.from_time else first
    upper = bucket_of(query.to_time - timedelta(microseconds=1))[1] if query.to_time else ends[last]
    return {
        "from": min(lower, first).astimezone(timezone).isoformat(),
        "to": max(upper, ends[last]).astimezone(timezone).isoformat(),
    }


def timeline(session: Session, identity: Identity, query: ReportQuery) -> dict:
    """Matching runs' cost by local hour, day or week, for the Over time chart."""
    query = as_run_query(query)
    matching = _matching_runs(session, identity, query)
    timezone = ZoneInfo(query.timezone)
    unit = _resolve_bucket(query, timezone, matching.run_set.records)
    bucket_of = _bucket_function(unit, timezone)
    run_set = matching.run_set
    cells: dict[tuple[datetime, uuid.UUID], dict] = {}
    ends: dict[datetime, datetime] = {}

    def accrue(start: datetime, end: datetime, run: dict, amount: Decimal | None, open_ended: bool):
        ends[start] = end
        cell = cells.setdefault((start, run["_id"]), {
            "amount": None, "unknown": False, "open": False,
        })
        cell["open"] = cell["open"] or open_ended
        if amount is None:
            cell["unknown"] = True
        else:
            cell["amount"] = (cell["amount"] or ZERO) + amount

    def bounded(instant: datetime) -> tuple[tuple[datetime, datetime], datetime]:
        start, end = bucket_of(instant)
        return (start, end), end

    unbounded = query.mode == "accrued" and not (query.from_time or query.to_time)
    unplaced_jobs, unplaced_amount = 0, None
    for run in matching.runs:
        for job_id in run["_amounts"]:
            if matching.assigned[job_id] != run["_id"]:
                continue
            record = run_set.record_by_job[job_id]
            # Cost with no usable timing cannot be drawn anywhere in time. A
            # dated report leaves it out of the period; an unbounded one keeps
            # it, so it is reported beside the buckets.
            if unbounded and (record["unattributed_amount"] or record["temporally_unattributed"]):
                unplaced_jobs += 1
                if record["full_amount"] is not None:
                    unplaced_amount = (unplaced_amount or ZERO) + record["unattributed_amount"]
            for (start, end), amount, open_ended in _accrual_chunks(
                record, query, run_set.as_of, bounded
            ):
                accrue(start, end, run, amount, open_ended)
    runs_by_id = {run["_id"]: run for run in matching.runs}
    by_bucket: dict[datetime, list[tuple[dict, dict]]] = defaultdict(list)
    for (start, run_id), cell in cells.items():
        by_bucket[start].append((runs_by_id[run_id], cell))
    buckets = []
    for start in sorted(by_bucket):
        entries = by_bucket[start]
        drawn = sorted(
            (entry for entry in entries if entry[1]["amount"]),
            key=lambda entry: (-entry[1]["amount"], entry[0]["_id"]),
        )
        shown, folded = drawn[:TIMELINE_PIECE_LIMIT], drawn[TIMELINE_PIECE_LIMIT:]
        remainder = _fold([entry[0] for entry in folded], [entry[1]["amount"] for entry in folded])
        buckets.append({
            "from": start.astimezone(timezone).isoformat(),
            "to": ends[start].astimezone(timezone).isoformat(),
            "amount": _money(_sum_known(entry[1]["amount"] for entry in entries)),
            "run_count": len(entries),
            "by_status": dict(Counter(entry[0]["run_status"] for entry in entries)),
            "incomplete_run_count": sum(entry[1]["unknown"] for entry in entries),
            "provisional": any(
                entry[1]["open"] or entry[0]["run_status"] == "running" for entry in entries
            ),
            "pieces": [{
                "id": run["id"], "amount": _money(cell["amount"]), "status": run["run_status"],
            } for run, cell in shown],
            "remainder": remainder,
        })
    axis = _timeline_axis(query, bucket_of, timezone, by_bucket, ends)
    drawn_ids = {piece["id"] for bucket in buckets for piece in bucket["pieces"]}
    return {
        "bucket": unit, "buckets": buckets, "axis": axis,
        # What a tooltip says about each run a piece draws, once per run.
        "runs": {
            run["id"]: {
                "workflow_name": run["workflow_name"], "started_at": run["started_at"],
                "duration_seconds": run["duration_seconds"], "amount": run["amount"],
                "run_total": run["run_total"], "shared_job_count": run["shared_job_count"],
            }
            for run in matching.runs if run["id"] in drawn_ids
        },
        "label": "Cost of jobs completed" if query.mode == "completed" else "Cost accrued",
        "unplaced": {"job_count": unplaced_jobs, "amount": _money(unplaced_amount)}
        if unplaced_jobs else None,
        "meta": _run_meta(session, identity, query, run_set),
    }


def _accrual_chunks(
    record: dict,
    query: ReportQuery,
    as_of: datetime,
    bucket_of: Callable[[datetime], tuple[Hashable, datetime]],
) -> Iterator[tuple[Hashable, Decimal | None, bool]]:
    """One job's cost, split at bucket boundaries.

    Yields each piece's bucket, its amount (None when the line has no known
    cost) and whether the resource was still open. `bucket_of` names the bucket
    an instant falls in and the instant that bucket ends. In completed mode the
    whole job is one piece, placed where it finished.
    """
    if query.mode == "completed":
        if record["completed_at"]:
            yield bucket_of(record["completed_at"])[0], record["amount"], False
        return
    for line, lifetime in record["pairs"]:
        open_ended = lifetime.observed_end is None
        for start, end, slice_amount in _line_slices(line, lifetime, as_of):
            if start == end:
                if _slice_fraction(start, end, query) > 0:
                    yield bucket_of(start)[0], slice_amount, open_ended
                continue
            total_seconds = Decimal(str((end - start).total_seconds()))
            cursor = max(start, query.from_time or start)
            limit = min(end, query.to_time or end)
            while cursor < limit:
                bucket, bucket_end = bucket_of(cursor)
                chunk_end = min(limit, bucket_end)
                yield bucket, None if slice_amount is None else (
                    slice_amount * Decimal(str((chunk_end - cursor).total_seconds())) / total_seconds
                ), open_ended
                cursor = chunk_end


def daily(session: Session, identity: Identity, query: ReportQuery) -> dict:
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    timezone = ZoneInfo(query.timezone)
    buckets: dict[str, dict] = defaultdict(lambda: {
        "amount": None, "job_ids": set(), "incomplete_ids": set(), "provisional": False,
        "by_runner": defaultdict(Decimal), "by_owner": defaultdict(Decimal),
        "by_tool": defaultdict(Decimal),
    })
    as_of = revision.created_at if revision else datetime.now(UTC)

    def local_day(instant: datetime) -> tuple[str, datetime]:
        local = instant.astimezone(timezone)
        next_day = datetime.combine(
            local.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone
        ).astimezone(UTC)
        return local.date().isoformat(), next_day

    for record in records:
        for day, amount, open_ended in _accrual_chunks(record, query, as_of, local_day):
            bucket = buckets[day]
            bucket["job_ids"].add(record["id"])
            bucket["provisional"] = bucket["provisional"] or open_ended
            if amount is None:
                bucket["incomplete_ids"].add(record["id"])
                continue
            bucket["amount"] = (bucket["amount"] or ZERO) + amount
            bucket["by_runner"][record["runner"] or "unknown"] += amount
            bucket["by_owner"][record["owner"]] += amount
            bucket["by_tool"][f"{record['tool_id']}@{record['tool_version'] or ''}"] += amount
    items = [{
        "date": day, "amount": _money(data["amount"]), "currency": "USD",
        "job_count": len(data["job_ids"]), "incomplete_count": len(data["incomplete_ids"]),
        "provisional": data["provisional"],
        "by_runner": {key: _money(value) for key, value in data["by_runner"].items()},
        "by_owner": {key: _money(value) for key, value in data["by_owner"].items()},
        "by_tool": {key: _money(value) for key, value in data["by_tool"].items()},
    } for day, data in sorted(buckets.items())]
    return {
        "items": items,
        "label": "Cost of jobs completed per day" if query.mode == "completed" else "Cost accrued per day",
        "temporally_unattributed_count": sum(
            r["temporally_unattributed"] for r in [*records, *undated]
        ),
        "temporally_unattributed_subtotal": _money(
            sum((r["unattributed_amount"] for r in [*records, *undated]), ZERO)
        ),
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def users(session: Session, identity: Identity, query: ReportQuery) -> dict:
    if not identity.is_admin:
        raise HTTPException(403, "Administrator scope required")
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in records:
        groups[(record["owner_id"], record["owner"])].append(record)
    items = []
    for (owner_id, label), rows in groups.items():
        known = [row["amount"] for row in rows if row["amount"] is not None]
        items.append({
            "owner_id": owner_id, "label": label, "job_count": len(rows),
            "amount": _money(sum(known, ZERO)) if known else None,
            "priced_count": len(known), "incomplete_count": len(rows) - len(known),
        })
    return {
        "items": sorted(items, key=lambda item: item["label"])[query.offset:query.offset + query.limit],
        "total": len(items), "limit": query.limit, "offset": query.offset,
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def infrastructure(
    session: Session,
    identity: Identity,
    query: ReportQuery,
    revision: CostRevision | None = None,
    snapshot_validated: bool = False,
) -> dict:
    if not identity.can_view_infrastructure:
        raise HTTPException(403, "Infrastructure reporting is not authorized for this scope")
    if not snapshot_validated:
        revision = _revision(session, identity, query.revision)
    rows = session.scalars(
        select(InfrastructureInterval)
        .where(InfrastructureInterval.tenant_id == identity.tenant_id)
        .order_by(InfrastructureInterval.observed_start)
    ).all()
    items = []
    covered: list[tuple[datetime, datetime]] = []
    for row in rows:
        start, end = row.observed_start, row.observed_end
        overlap_start, overlap_end = max(start, query.from_time or start), min(end, query.to_time or end)
        fraction = max(0.0, (overlap_end - overlap_start).total_seconds()) / (end - start).total_seconds()
        if fraction > 0:
            covered.append((overlap_start, overlap_end))
            items.append({
                "id": str(row.id), "resource_uid": row.resource_uid,
                "machine_type": row.machine_type, "region": row.region,
                "observed_start": start, "observed_end": end,
                "amount": _money(row.amount * Decimal(str(fraction))),
                "currency": row.currency, "quality": row.quality.value,
            })
    return {
        "items": items,
        "amount": _money(sum((Decimal(item["amount"]) for item in items), ZERO)) if items else None,
        "currency": "USD", "scope": "Whole baseline resources; job filters do not apportion this total.",
        "allocation_supported": False,
        "allocation_reason": "T2D allocation is unavailable without a valid component policy.",
        "revision_id": str(revision.id) if revision else None,
        "as_of": revision.created_at.isoformat() if revision else None,
        "observation_window": {
            "from": (query.from_time or (min((row.observed_start for row in rows), default=None))).isoformat()
            if (query.from_time or rows) else None,
            "to": (query.to_time or (max((row.observed_end for row in rows), default=None))).isoformat()
            if (query.to_time or rows) else None,
            "timezone": query.timezone, "semantics": "[from, to)", "mode": query.mode,
        },
        # What the server was actually observed doing inside the requested
        # window; the window itself is only what was asked for.
        "observed_coverage": {
            "from": min(start for start, _ in covered).isoformat(),
            "to": max(end for _, end in covered).isoformat(),
        } if covered else None,
        "current_launch": current_launch(session, identity),
    }


SERVER_STALE_AFTER = timedelta(minutes=5)
SERVER_SCOPE = (
    "The whole Galaxy server VM's compute since its current launch, including idle time. "
    "Report filters do not change it, and it is never added to run costs. It excludes "
    "disks, networking, discounts and other cloud charges."
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _server_stale_reason(
    server: GalaxyServerSession, imported: dict | None, now: datetime
) -> str | None:
    if imported:
        return "This is an imported snapshot; its figures stop at the last observation it holds."
    if server.ended_at:
        return None
    age = now - server.observed_at
    if age <= SERVER_STALE_AFTER:
        return None
    minutes = int(age.total_seconds() // 60)
    elapsed = (
        f"{minutes} minutes" if minutes < 120
        else f"{minutes // 60} hours" if minutes < 48 * 60
        else f"{minutes // (24 * 60)} days"
    )
    return (
        f"The server was last observed {elapsed} ago; the total stops at that observation "
        "rather than assuming the server kept running."
    )


def current_launch(session: Session, identity: Identity, *, now: datetime | None = None) -> dict:
    """The Galaxy server's hourly rate and estimated total since its current launch.

    Derived from the stored session and the catalog on every request, so it
    needs no cached amount and repeated observations cannot add to it. It
    depends on no report filter; the timezone only affects how clients format
    its timestamps.
    """
    if not identity.can_view_infrastructure:
        raise HTTPException(403, "Infrastructure reporting is not authorized for this scope")
    now = now or datetime.now(UTC)
    tenant = session.get(Tenant, identity.tenant_id)
    imported = _imported_snapshot((tenant.capabilities or {}) if tenant else {})
    server = session.scalar(
        select(GalaxyServerSession).where(GalaxyServerSession.tenant_id == identity.tenant_id)
    )
    base = {
        "scope": SERVER_SCOPE, "currency": "USD",
        "calculation_version": SERVER_CALCULATION_VERSION,
    }
    if server is None:
        collection = session.scalar(
            select(IngestionState).where(
                IngestionState.tenant_id == identity.tenant_id,
                IngestionState.source == "galaxy_server",
            )
        )
        reason = "No observation of the Galaxy server has been recorded."
        if collection is not None and collection.error:
            reason += f" The last attempt failed: {collection.error}"
        return {
            **base, "resource_uid": None, "name": None, "project": None, "zone": None,
            "region": None, "machine_type": None, "purchase_model": None, "state": None,
            "descriptor_source": None, "launch_at": None, "launch_source": None,
            "first_observed_at": None, "observed_at": None, "ended_at": None, "as_of": None,
            "stale": False, "stale_reason": None, "hourly_rate": None,
            "hourly_rate_unavailable_reason": reason, "price": None,
            "total_since_launch": None, "known_subtotal": None, "completeness": "unavailable",
            "unavailable_reason": reason, "elapsed_seconds": None, "billed_seconds": None,
            "calculation_revision": None,
        }
    prices = applicable_prices(
        session, provider=server.provider, region=server.region,
        machine_type=server.machine_type, purchase_model=server.purchase_model,
    )
    cost = calculate_server_session(server, prices)
    rate = cost.rate
    stale_reason = _server_stale_reason(server, imported, now)
    # Identifies the inputs of this result, so two responses with the same
    # revision are the same calculation.
    revision = hashlib.sha256("|".join(str(part) for part in (
        SERVER_CALCULATION_VERSION, server.session_key, _iso(cost.cutoff),
        server.machine_type, server.purchase_model, server.region, server.shape_conflict,
        *sorted(str(price.id) for price in prices),
    )).encode()).hexdigest()[:32]
    return {
        **base,
        "resource_uid": server.resource_uid, "name": server.name, "project": server.project,
        "zone": server.zone, "region": server.region, "machine_type": server.machine_type,
        "purchase_model": server.purchase_model, "state": server.state,
        "currency": rate.currency if rate else "USD",
        "descriptor_source": server.descriptor_source,
        "launch_at": _iso(server.launch_at), "launch_source": server.launch_source,
        "first_observed_at": _iso(server.first_observed_at),
        "observed_at": _iso(server.observed_at), "ended_at": _iso(server.ended_at),
        "as_of": _iso(cost.cutoff),
        "stale": stale_reason is not None, "stale_reason": stale_reason,
        "hourly_rate": format(rate.hourly_rate.normalize(), "f") if rate else None,
        "hourly_rate_unavailable_reason": cost.rate_unavailable_reason,
        "price": {
            "price_version_id": str(rate.id), "catalog_id": rate.catalog_id,
            "effective_from": _iso(rate.effective_from), "observed_at": _iso(rate.observed_at),
            "kind": (rate.provenance or {}).get("kind"),
        } if rate else None,
        "total_since_launch": _money(cost.total) if cost.total is not None else None,
        "known_subtotal": _money(cost.known_subtotal) if cost.known_subtotal is not None else None,
        "completeness": cost.completeness,
        "unavailable_reason": cost.unavailable_reason,
        "elapsed_seconds": _money(cost.elapsed_seconds) if cost.elapsed_seconds is not None else None,
        "billed_seconds": _money(cost.billed_seconds) if cost.billed_seconds is not None else None,
        "calculation_revision": revision,
    }


def freshness(session: Session, identity: Identity) -> dict:
    rows = session.scalars(
        select(IngestionState).where(IngestionState.tenant_id == identity.tenant_id)
        .order_by(IngestionState.source)
    ).all()
    now = datetime.now(UTC)
    sources = []
    for row in rows:
        status = row.status
        if status == "healthy" and row.last_success_at and now - row.last_success_at > timedelta(hours=24):
            status = "stale"
        sources.append({
            "source": row.source, "status": status, "last_success_at": row.last_success_at,
            "cursor": row.cursor, "error": row.error,
        })
    price = session.execute(
        select(PriceVersion.catalog_id, PriceVersion.observed_at)
        .order_by(PriceVersion.observed_at.desc()).limit(1)
    ).first()
    if price:
        sources.append({
            "source": "price_catalog", "status": "historical_snapshot",
            "last_success_at": price.observed_at,
            "cursor": {"catalog_id": price.catalog_id}, "error": None,
        })
    gaps = session.scalars(
        select(ObservationGap)
        .where(ObservationGap.tenant_id == identity.tenant_id)
        .order_by(ObservationGap.detected_at.desc())
        .limit(20)
    ).all()
    statuses = {source["status"] for source in sources}
    overall = "failed" if "failed" in statuses else (
        "partial" if statuses - {"healthy", "historical_snapshot"} else "healthy"
    )
    revision = session.get(CostRevision, identity.tenant_id)
    # A revision whose facts have since changed is about to be replaced, and a
    # report pinned to it would be refused, so it is not offered as current.
    current = revision is not None and revision.facts_generation == current_generation(session, identity.tenant_id)
    return {
        "sources": sources,
        "overall_status": overall,
        "revision_id": str(revision.id) if current else None,
        "observation_gaps": [
            {
                "source": gap.source, "kind": gap.kind, "detected_at": gap.detected_at,
                "gap_start": gap.gap_start, "gap_end": gap.gap_end,
                "recoverable": gap.recoverable, "detail": gap.detail,
            }
            for gap in gaps
        ],
    }


def export_csv(session: Session, identity: Identity, query: ReportQuery):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "job_id", "source_id", "tool_id", "tool_version", "owner", "state", "runner",
        "destination", "basis", "currency", "time_semantics", "amount_exact", "quality",
        "reason", "revision_id",
    ])
    yield output.getvalue()
    output.seek(0)
    output.truncate(0)
    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in {"=", "+", "-", "@"} else text
    batch_size = 500
    candidate_offset = 0
    export_query = query.model_copy(update={"offset": 0, "limit": 200})
    while True:
        # Cost sorting depends on calculated lines, so preserve its global order as a compatibility fallback.
        if query.sort == "amount":
            result = list_jobs(session, identity, export_query, paginate=False)
            records = result["items"]
            revision_id = result["meta"]["revision_id"]
            exhausted = True
        else:
            raw_count: list[int] = []
            batch, revision = _base_records(
                session, identity, export_query,
                candidate_offset=candidate_offset, candidate_limit=batch_size,
                candidate_count=raw_count,
            )
            records = [_public(record) for record in batch]
            revision_id = str(revision.id) if revision else None
            exhausted = raw_count[0] < batch_size
        for row in records:
            writer.writerow([
                *[safe(row.get(key)) for key in (
                    "id", "source_id", "tool_id", "tool_version", "owner", "state",
                    "runner", "destination",
                )],
                query.basis, "USD",
                "accrued [from,to)" if query.mode == "accrued" else "completed in range",
                safe(row["amount"]), row["quality"], safe(row["reason"]), revision_id,
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)
        if exhausted:
            break
        candidate_offset += batch_size
