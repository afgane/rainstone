"""The Overview page's cost over time: workflow runs, and individual jobs.

Every job in the period is drawn in one of two blocks per column: "workflow
runs" when a workflow run contains it, or "individual jobs" when it ran on its
own. The columns add up to the Overview total. Splitting the runs further would
crowd the chart as their number grows; the Workflow runs page does that.
"""

import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from rainstone.auth import Identity
from rainstone.models import Invocation
from rainstone.report_query import ReportQuery, as_run_query
from rainstone.reporting import (
    RUNNING_STATES,
    ZERO,
    _accrual_chunks,
    _base_records,
    _bucket_function,
    _invocation_job_sets,
    _job_amount,
    _meta,
    _money,
    _resolve_bucket,
    _sum_known,
    _timeline_axis,
)

# The two blocks a column can have.
WORKFLOW_RUNS = "runs"
WORKFLOW_RUNS_NAME = "Workflow runs"
INDIVIDUAL = "individual"
INDIVIDUAL_NAME = "Individual jobs"


def job_outcome(state: str) -> str:
    """A job's state in the words the page counts: completed, failed, running."""
    if state == "ok":
        return "completed"
    if state in {"error", "failed"}:
        return "failed"
    return "running" if state in RUNNING_STATES else "other"


def workflow_key(invocation: Invocation) -> str:
    """A run's stored workflow: its family ID, then its workflow ID, then its name."""
    return invocation.workflow_family_id or invocation.workflow_id or invocation.workflow_name


def _runs_holding_jobs(session: Session, identity: Identity) -> dict[uuid.UUID, list[Invocation]]:
    """Every root run that contains each job, lowest UUID first.

    A job in several runs is drawn once, under the first; every run that holds
    it still counts as a run.
    """
    authorized, job_sets = _invocation_job_sets(session, identity)
    roots = sorted((inv for inv in authorized if inv.parent_id is None), key=lambda inv: inv.id)
    holders: dict[uuid.UUID, list[Invocation]] = defaultdict(list)
    for root in roots:
        for job_id in job_sets[root.id]:
            holders[job_id].append(root)
    return holders


def cost_timeline(session: Session, identity: Identity, query: ReportQuery) -> dict:
    query = as_run_query(query)
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    as_of = revision.created_at if revision else datetime.now(UTC)
    timezone = ZoneInfo(query.timezone)
    unit = _resolve_bucket(query, timezone, records)
    bucket_of = _bucket_function(unit, timezone)
    holders = _runs_holding_jobs(session, identity)

    cells: dict[tuple[datetime, str], dict] = {}
    ends: dict[datetime, datetime] = {}

    def bounded(instant: datetime) -> tuple[tuple[datetime, datetime], datetime]:
        start, end = bucket_of(instant)
        return (start, end), end

    unbounded = query.mode == "accrued" and not (query.from_time or query.to_time)
    unplaced_jobs, unplaced_amount = 0, None
    outcomes: Counter[str] = Counter()
    runs: set[uuid.UUID] = set()
    workflows: set[str] = set()
    individual_jobs = 0
    for record in records:
        job_id = uuid.UUID(record["id"])
        containing = holders.get(job_id, [])
        root = containing[0] if containing else None
        key = WORKFLOW_RUNS if root else INDIVIDUAL
        outcome = job_outcome(record["state"])
        outcomes[outcome] += 1
        for holder in containing:
            runs.add(holder.id)
            workflows.add(workflow_key(holder))
        if not containing:
            individual_jobs += 1
        # Cost with no usable timing cannot be drawn anywhere in time. A dated
        # report leaves it out of the period; an unbounded one keeps it, so it
        # is reported beside the buckets.
        if unbounded and (record["unattributed_amount"] or record["temporally_unattributed"]):
            unplaced_jobs += 1
            if record["full_amount"] is not None:
                unplaced_amount = (unplaced_amount or ZERO) + record["unattributed_amount"]
        for (start, end), amount, open_ended in _accrual_chunks(record, query, as_of, bounded):
            ends[start] = end
            cell = cells.setdefault((start, key), {
                "amount": None, "jobs": set(), "runs": set(), "failed": set(), "running": set(),
                "unknown": set(), "open": False,
            })
            cell["jobs"].add(job_id)
            if root:
                cell["runs"].add(root.id)
            if outcome in {"failed", "running"}:
                cell[outcome].add(job_id)
            cell["open"] = cell["open"] or open_ended
            if amount is None:
                cell["unknown"].add(job_id)
            else:
                cell["amount"] = (cell["amount"] or ZERO) + amount

    by_bucket: dict[datetime, list[tuple[str, dict]]] = defaultdict(list)
    for (start, key), cell in cells.items():
        by_bucket[start].append((key, cell))
    buckets = []
    for start in sorted(by_bucket):
        entries = by_bucket[start]
        pieces = sorted(
            (entry for entry in entries if entry[1]["amount"]),
            key=lambda entry: (-entry[1]["amount"], entry[0]),
        )

        def union(field: str, chosen: list[tuple[str, dict]] = entries) -> set:
            return set().union(*(cell[field] for _, cell in chosen))

        buckets.append({
            "from": start.astimezone(timezone).isoformat(),
            "to": ends[start].astimezone(timezone).isoformat(),
            "amount": _money(_sum_known(cell["amount"] for _, cell in entries)),
            "job_count": len(union("jobs")),
            "run_count": len(union("runs")),
            "failed_job_count": len(union("failed")),
            "running_job_count": len(union("running")),
            "incomplete_job_count": len(union("unknown")),
            "provisional": any(cell["open"] for _, cell in entries) or bool(union("running")),
            "pieces": [{
                "key": key, "kind": key,
                "name": WORKFLOW_RUNS_NAME if key == WORKFLOW_RUNS else INDIVIDUAL_NAME,
                "amount": _money(cell["amount"]), "job_count": len(cell["jobs"]),
                "run_count": len(cell["runs"]), "failed": len(cell["failed"]),
                "running": len(cell["running"]),
            } for key, cell in pieces],
        })
    return {
        "bucket": unit, "buckets": buckets,
        "axis": _timeline_axis(query, bucket_of, timezone, by_bucket, ends),
        "totals": {
            "amount": _money(_sum_known(_job_amount(record, query) for record in records)),
            "job_count": len(records),
            "by_outcome": dict(outcomes),
            "run_count": len(runs),
            "workflow_count": len(workflows),
            "individual_job_count": individual_jobs,
        },
        "label": "Cost of jobs completed" if query.mode == "completed" else "Cost accrued",
        "unplaced": {"job_count": unplaced_jobs, "amount": _money(unplaced_amount)}
        if unplaced_jobs else None,
        "meta": _meta(session, identity, query, revision, records, undated),
    }
