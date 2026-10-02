"""What lies behind an Overview figure: one chart block, or the whole period.

Every answer is built from the Overview timeline's own records and partition,
so it reconciles with the block or headline it explains. A job belongs to the
workflow runs when an authorized root run holds it, and is counted under the
lowest-UUID such root, exactly as the chart draws it; every other job is an
individual job. Totals describe the whole scoped set, never a page of it.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from rainstone.auth import Identity
from rainstone.jobs_report import _family, _job_row
from rainstone.overview import _runs_holding_jobs, job_outcome
from rainstone.report_query import ReportQuery, as_run_query
from rainstone.reporting import (
    INCOMPLETE_QUALITIES,
    ZERO,
    _accrual_chunks,
    _base_records,
    _job_amount,
    _meta,
    _money,
    _run_records,
    _sum_known,
)

Scope = Literal["period", "interval"]
Kind = Literal["runs", "individual", "tools"]
SUPPORTED = {("interval", "runs"), ("interval", "individual"), ("period", "runs"), ("period", "tools")}
# How many contributors a period ranking lists.
RANKING_LIMIT = 5
FAR_FUTURE = datetime.max.replace(tzinfo=UTC)


def _within(lower: datetime, upper: datetime) -> Callable[[datetime], tuple[bool, datetime]]:
    """A bucket function with one bucket, the interval, and the time either side of it."""
    def bucket_of(instant: datetime) -> tuple[bool, datetime]:
        if instant < lower:
            return False, lower
        return (True, upper) if instant < upper else (False, FAR_FUTURE)
    return bucket_of


def _interval_share(
    record: dict, query: ReportQuery, as_of: datetime, bucket_of: Callable
) -> tuple[bool, Decimal | None, bool]:
    """Whether a job has cost inside the interval, that cost, and whether it is still open.

    The pieces are the chart's own accrual chunks, so the interval's amount is
    the amount of the block it was opened from.
    """
    found, amount, open_ended = False, None, False
    for inside, piece, still_open in _accrual_chunks(record, query, as_of, bucket_of):
        if not inside:
            continue
        found = True
        open_ended = open_ended or still_open
        if piece is not None:
            amount = (amount or ZERO) + piece
    return found, amount, open_ended


def _by_amount(amount: Decimal | None, key: str) -> tuple:
    """Known amounts largest first, then unknown ones, ties broken by ID."""
    return (amount is None, -(amount or ZERO), key)


def _incomplete(records: list[dict]) -> int:
    return sum(record["quality"] in INCOMPLETE_QUALITIES for record in records)


def _run_rows(
    session: Session, identity: Identity, query: ReportQuery,
    contributions: dict[uuid.UUID, list[tuple[dict, Decimal | None]]],
    roots: dict[uuid.UUID, object], sharing: dict[str, int],
) -> list[dict]:
    """Each contributing run with the cost counted under it, enriched in one pass."""
    whole = {
        run["_id"]: run for run in _run_records(session, identity, as_run_query(query)).runs
    }
    rows = []
    for run_id, entries in contributions.items():
        root, known = roots[run_id], whole.get(run_id)
        records = [record for record, _ in entries]
        rows.append({
            "id": str(run_id), "workflow_name": root.workflow_name,
            "run_status": known["run_status"] if known else None,
            "started_at": known["started_at"] if known else root.created_at,
            "amount": _money(_sum_known(amount for _, amount in entries)),
            "job_count": len(entries),
            "incomplete_job_count": _incomplete(records),
            "shared_job_count": sum(sharing[record["id"]] > 1 for record in records),
            "run_total": known["run_total"] if known else None,
            "run_total_complete": bool(known and known["run_total_complete"]),
            "_amount": _sum_known(amount for _, amount in entries),
        })
    return rows


def _public(row: dict) -> dict:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _ranking(rows: list[dict], amount_of: Callable[[dict], Decimal | None], key: str) -> tuple[list[dict], dict]:
    """The top contributors among those with a complete, positive cost.

    An incomplete estimate cannot be compared with a complete one, so it is
    left out and counted instead.
    """
    complete = [row for row in rows if not row["incomplete_job_count"] and amount_of(row) is not None]
    eligible = sorted(
        (row for row in complete if amount_of(row) > 0),
        key=lambda row: _by_amount(amount_of(row), row[key]),
    )
    return eligible[:RANKING_LIMIT], {
        "eligible_count": len(eligible),
        "excluded_count": len(rows) - len(complete),
        "zero_count": len(complete) - len(eligible),
        "limit": RANKING_LIMIT,
    }


def details(
    session: Session, identity: Identity, query: ReportQuery, scope: Scope, kind: Kind,
    window_from: datetime | None = None, window_to: datetime | None = None,
) -> dict:
    if (scope, kind) not in SUPPORTED:
        raise HTTPException(422, f"Overview details do not support {kind} for a {scope}")
    lower, upper = query.from_time, query.to_time
    if scope == "interval":
        if window_from is None or window_to is None:
            raise HTTPException(422, "An interval needs window_from and window_to")
        lower = max(window_from, lower) if lower else window_from
        upper = min(window_to, upper) if upper else window_to
        if lower >= upper:
            raise HTTPException(422, "The interval must overlap the report period")
    # The Overview timeline's own query: shared filters only, no page filters.
    # A run query has its own default page size, so the drawer's is kept.
    query = as_run_query(query).model_copy(update={"limit": query.limit})
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    as_of = revision.created_at if revision else datetime.now(UTC)
    holders = _runs_holding_jobs(session, identity)
    sharing = {record["id"]: len(holders.get(uuid.UUID(record["id"]), [])) for record in records}

    scoped: list[tuple[dict, Decimal | None]] = []
    provisional = False
    if scope == "interval":
        bucket_of = _within(lower, upper)
        for record in records:
            in_runs = bool(holders.get(uuid.UUID(record["id"])))
            if in_runs != (kind == "runs"):
                continue
            found, amount, open_ended = _interval_share(record, query, as_of, bucket_of)
            if found:
                scoped.append((record, amount))
                provisional = provisional or open_ended or job_outcome(record["state"]) == "running"
    elif kind == "runs":
        scoped = [
            (record, _job_amount(record, query)) for record in records
            if holders.get(uuid.UUID(record["id"]))
        ]
    else:
        scoped = [(record, _job_amount(record, query)) for record in records]

    scoped_records = [record for record, _ in scoped]
    result = {
        "scope": scope, "kind": kind, "from": lower, "to": upper,
        "amount": _money(_sum_known(amount for _, amount in scoped)),
        "job_count": len(scoped),
        "incomplete_job_count": _incomplete(scoped_records),
        "provisional": provisional,
        "shared_job_count": sum(sharing[record["id"]] > 1 for record in scoped_records),
        "run_count": None, "tool_count": None, "ranking": None,
        "items": [], "total": 0, "limit": query.limit, "offset": query.offset,
        "meta": _meta(session, identity, query, revision, records, undated),
    }

    if kind == "tools":
        grouped: dict[str, list[dict]] = defaultdict(list)
        for record in scoped_records:
            grouped[record["tool_key"]].append(record)
        families = [_family(key, rows, query) for key, rows in grouped.items()]
        top, ranking = _ranking(families, lambda family: family["_amount"], "key")
        result.update({
            "tool_count": len(families), "ranking": ranking, "total": len(top), "limit": RANKING_LIMIT,
            "offset": 0, "items": [{
                "key": family["key"], "name": family["name"], "tool_ids": family["tool_ids"],
                "versions": family["versions"], "amount": family["amount"],
                "job_count": family["job_count"],
            } for family in top],
        })
        return result

    if kind == "runs":
        contributions: dict[uuid.UUID, list[tuple[dict, Decimal | None]]] = defaultdict(list)
        roots = {}
        for record, amount in scoped:
            root = holders[uuid.UUID(record["id"])][0]
            roots[root.id] = root
            contributions[root.id].append((record, amount))
        rows = _run_rows(session, identity, query, contributions, roots, sharing)
        result["run_count"] = len(rows)
        if scope == "period":
            top, ranking = _ranking(rows, lambda row: row["_amount"], "id")
            result.update({
                "ranking": ranking, "total": len(top), "limit": RANKING_LIMIT, "offset": 0,
                "items": [_public(row) for row in top],
            })
            return result
        ordered = sorted(rows, key=lambda row: _by_amount(row["_amount"], row["id"]))
        page = ordered[query.offset:query.offset + query.limit]
        result.update({"items": [_public(row) for row in page], "total": len(ordered)})
        return result

    ordered = sorted(scoped, key=lambda entry: _by_amount(entry[1], entry[0]["id"]))
    page = ordered[query.offset:query.offset + query.limit]
    result.update({
        "items": [_job_row(record, amount, as_of) for record, amount in page], "total": len(ordered),
    })
    return result
