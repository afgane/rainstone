"""The Jobs page: every matching job, by tool and over time, and their drawers.

Workflow jobs and individual tool jobs are reported together, from the same
records the summary sums, so every figure here reconciles with Overview. Tools
group by `tool_family_key`, so the versions of one tool are one row and two
tools that share a readable name stay apart. Amounts are split by each job's
recorded status, using Overview's own outcome words; a status piece is never a
reconstruction of what a job's status was at some past hour.
"""

import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from rainstone.auth import Identity
from rainstone.overview import job_outcome
from rainstone.report_query import ReportQuery, RunReportQuery
from rainstone.reporting import (
    EXECUTING_STATES,
    INCOMPLETE_QUALITIES,
    ZERO,
    _accrual_chunks,
    _base_records,
    _bucket_function,
    _execution_span,
    _job_amount,
    _load_job_facts,
    _meta,
    _money,
    _records_from_facts,
    _resolve_bucket,
    _sum_known,
    _timeline_axis,
    tool_display_name,
    tool_statistics,
)

# The order status pieces are stacked in, in both charts and every drawer.
STATUS_ORDER = ("completed", "running", "failed", "other")
# How many jobs a tool drawer lists as contributing most to its cost.
CONTRIBUTOR_LIMIT = 5
DEFAULT_GROUP_LIMIT = 12

RANKED = "ranked"
SERVER = "server"
ZERO_COST = "zero"
UNAVAILABLE = "unavailable"


def _status_pieces(
    records: Iterable[dict], amount_of: Callable[[dict], Decimal | None]
) -> list[dict]:
    """Known cost and job counts per recorded status, in the stacking order.

    Each job is in exactly one piece, so the pieces add up to the whole.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[job_outcome(record["state"])].append(record)
    return [{
        "status": status,
        "amount": _money(_sum_known(amount_of(record) for record in grouped[status])),
        "job_count": len(grouped[status]),
        "incomplete_job_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in grouped[status]),
    } for status in STATUS_ORDER if grouped[status]]


def _resourced(record: dict) -> set[uuid.UUID]:
    return {attempt.id for users in record["lifetime_attempts"].values() for attempt in users}


def _job_row(record: dict, amount: Decimal | None, as_of: datetime) -> dict:
    """A job in a drawer list: its scoped cost beside its whole-execution duration."""
    span = _execution_span(record, _resourced(record), as_of)
    return {
        "id": record["id"], "tool_name": record["tool_name"], "tool_id": record["tool_id"],
        "tool_version": record["tool_version"], "state": record["state"],
        "amount": _money(amount), "quality": record["quality"],
        "capacities": record["capacities"], "created_at": record["created_at"],
        "duration_seconds": span["duration_seconds"], "duration_running": span["duration_running"],
    }


def _category(amount: Decimal | None, records: list[dict]) -> str:
    """Where a tool sits: ranked by a positive cost, or in one of the compact sections.

    Only jobs whose every cost line says they ran on the already-running Galaxy
    server make a server tool; any other observed zero is just a zero.
    """
    if amount is None:
        return UNAVAILABLE
    if amount > 0:
        return RANKED
    if all(r["quality"] == "known_zero" and r["capacities"] == ["existing"] for r in records):
        return SERVER
    return ZERO_COST


def _family(key: str, records: list[dict], query: ReportQuery) -> dict:
    amount = _sum_known(_job_amount(record, query) for record in records)
    tool_ids = sorted({record["tool_id"] for record in records})
    versions = Counter(record["tool_version"] for record in records)
    return {
        "key": key, "name": tool_display_name(tool_ids[0]), "tool_ids": tool_ids,
        "versions": [
            {"version": version, "job_count": count}
            for version, count in sorted(versions.items(), key=lambda item: (-item[1], item[0] or ""))
        ],
        "job_count": len(records),
        "amount": _money(amount),
        "incomplete_job_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in records),
        "known_zero_job_count": sum(r["quality"] == "known_zero" for r in records),
        "category": _category(amount, records),
        "by_status": _status_pieces(records, lambda record: _job_amount(record, query)),
        "_amount": amount,
    }


def _public_family(family: dict) -> dict:
    return {key: value for key, value in family.items() if not key.startswith("_")}


def _totals(records: list[dict], query: ReportQuery) -> dict:
    """The whole matching set, never a page, a batch of tools or an open drawer."""
    return {
        "amount": _money(_sum_known(_job_amount(record, query) for record in records)),
        "job_count": len(records),
        "tool_count": len({record["tool_key"] for record in records}),
        "incomplete_job_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in records),
        "known_zero_job_count": sum(r["quality"] == "known_zero" for r in records),
        "by_status": _status_pieces(records, lambda record: _job_amount(record, query)),
    }


def _matches(family: dict, term: str) -> bool:
    return not term or any(
        term in text.casefold() for text in (family["name"], family["key"], *family["tool_ids"])
    )


def _section(families: list[dict], term: str) -> dict:
    return {
        "tool_count": len(families),
        "job_count": sum(family["job_count"] for family in families),
        "groups": [_public_family(family) for family in families if _matches(family, term)],
    }


def breakdown(
    session: Session, identity: Identity, query: ReportQuery,
    tool_search: str | None = None, group_limit: int = DEFAULT_GROUP_LIMIT,
) -> dict:
    """Every matching tool family, for the By tool chart.

    Tools with a positive known cost are ranked by it, then by key, and
    returned up to `group_limit`; the rest of the ranking is summed into
    `remainder`. `tool_search` narrows which tools are listed, never the
    totals: it is a way to find a row, not a report filter. `scale` is the
    largest tool's amount, so bars keep one scale however many are shown.
    """
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["tool_key"]].append(record)
    families = [_family(key, rows, query) for key, rows in grouped.items()]
    by_category: dict[str, list[dict]] = defaultdict(list)
    for family in families:
        by_category[family["category"]].append(family)
    ranked = sorted(by_category[RANKED], key=lambda family: (-family["_amount"], family["key"]))
    term = (tool_search or "").strip().casefold()
    matching = [family for family in ranked if _matches(family, term)]
    shown, rest = matching[:group_limit], matching[group_limit:]
    by_name = lambda family: (family["name"].casefold(), family["key"])  # noqa: E731
    return {
        "groups": [_public_family(family) for family in shown],
        "total": len(matching),
        "ranked_tool_count": len(ranked),
        "remainder": {
            "tool_count": len(rest),
            "job_count": sum(family["job_count"] for family in rest),
            "amount": _money(_sum_known(family["_amount"] for family in rest)),
            "incomplete_job_count": sum(family["incomplete_job_count"] for family in rest),
        },
        "scale": _money(ranked[0]["_amount"]) if ranked else None,
        "server": _section(sorted(by_category[SERVER], key=by_name), term),
        "zero": _section(sorted(by_category[ZERO_COST], key=by_name), term),
        "unavailable": _section(sorted(by_category[UNAVAILABLE], key=by_name), term),
        "totals": _totals(records, query),
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def timeline(session: Session, identity: Identity, query: RunReportQuery) -> dict:
    """Matching jobs' cost per local hour, day or week, stacked by recorded status.

    Buckets come from the same rule and accrual slicing as the Overview and
    workflow run timelines, so day columns equal the daily report. A bucket
    with jobs but no known cost has a null amount; empty buckets are omitted
    and `axis` gives the range to fill.
    """
    undated: list[dict] = []
    records, revision = _base_records(session, identity, query, undated=undated)
    as_of = revision.created_at if revision else datetime.now(UTC)
    timezone = ZoneInfo(query.timezone)
    unit = _resolve_bucket(query, timezone, records)
    bucket_of = _bucket_function(unit, timezone)
    cells: dict[datetime, dict[str, dict]] = defaultdict(dict)
    ends: dict[datetime, datetime] = {}

    def bounded(instant: datetime) -> tuple[tuple[datetime, datetime], datetime]:
        start, end = bucket_of(instant)
        return (start, end), end

    unbounded = query.mode == "accrued" and not (query.from_time or query.to_time)
    unplaced_jobs, unplaced_amount = 0, None
    for record in records:
        status = job_outcome(record["state"])
        if unbounded and (record["unattributed_amount"] or record["temporally_unattributed"]):
            unplaced_jobs += 1
            if record["full_amount"] is not None:
                unplaced_amount = (unplaced_amount or ZERO) + record["unattributed_amount"]
        for (start, end), amount, open_ended in _accrual_chunks(record, query, as_of, bounded):
            ends[start] = end
            cell = cells[start].setdefault(status, {
                "amount": None, "jobs": set(), "unknown": set(), "open": False,
            })
            cell["jobs"].add(record["id"])
            cell["open"] = cell["open"] or open_ended or record["state"] in EXECUTING_STATES
            if amount is None:
                cell["unknown"].add(record["id"])
            else:
                cell["amount"] = (cell["amount"] or ZERO) + amount
    buckets = []
    for start in sorted(cells):
        by_status = cells[start]
        jobs = set().union(*(cell["jobs"] for cell in by_status.values()))
        unknown = set().union(*(cell["unknown"] for cell in by_status.values()))
        buckets.append({
            "from": start.astimezone(timezone).isoformat(),
            "to": ends[start].astimezone(timezone).isoformat(),
            "amount": _money(_sum_known(cell["amount"] for cell in by_status.values())),
            "job_count": len(jobs),
            "incomplete_job_count": len(unknown),
            "provisional": any(cell["open"] for cell in by_status.values()),
            "by_status": [{
                "status": status, "amount": _money(by_status[status]["amount"]),
                "job_count": len(by_status[status]["jobs"]),
                "incomplete_job_count": len(by_status[status]["unknown"]),
            } for status in STATUS_ORDER if status in by_status],
        })
    return {
        "bucket": unit, "buckets": buckets,
        "axis": _timeline_axis(query, bucket_of, timezone, cells, ends),
        "totals": _totals(records, query),
        "label": "Cost of jobs completed" if query.mode == "completed" else "Cost accrued",
        "unplaced": {"job_count": unplaced_jobs, "amount": _money(unplaced_amount)}
        if unplaced_jobs else None,
        "meta": _meta(session, identity, query, revision, records, undated),
    }


def tool_detail(session: Session, identity: Identity, query: ReportQuery, tool_key: str) -> dict:
    """One tool family under the page's filters, and the jobs that cost most in the period.

    Contributors are chosen from every matching job, by the period's cost,
    largest first with ties broken by job ID. A job whose cost is incomplete
    cannot be compared with one whose cost is known, so it is left out of the
    ranking and counted in `excluded_job_count`; its known subtotal is still
    part of the tool's amount.
    """
    scoped = query.model_copy(update={"tool_key": tool_key})
    undated: list[dict] = []
    records, revision = _base_records(session, identity, scoped, undated=undated)
    as_of = revision.created_at if revision else datetime.now(UTC)
    family = _family(tool_key, records, scoped) if records else None
    eligible = [
        record for record in records
        if record["quality"] not in INCOMPLETE_QUALITIES and _job_amount(record, scoped) is not None
    ]
    newest_first = lambda record: (-record["created_at"].timestamp(), record["id"])  # noqa: E731
    if family and family["category"] == SERVER:
        kind, chosen = SERVER, sorted(records, key=newest_first)
    elif any(_job_amount(record, scoped) > 0 for record in eligible):
        kind = RANKED
        chosen = sorted(eligible, key=lambda record: (-_job_amount(record, scoped), record["id"]))
    elif eligible:
        kind, chosen = ZERO_COST, sorted(eligible, key=newest_first)
    else:
        kind, chosen = UNAVAILABLE, []
    return {
        "key": tool_key,
        "name": family["name"] if family else tool_display_name(tool_key),
        "tool_ids": family["tool_ids"] if family else [],
        "versions": family["versions"] if family else [],
        "amount": family["amount"] if family else None,
        "job_count": len(records),
        "incomplete_job_count": family["incomplete_job_count"] if family else 0,
        "known_zero_job_count": family["known_zero_job_count"] if family else 0,
        "category": family["category"] if family else None,
        "by_status": family["by_status"] if family else [],
        "contributors": {
            "kind": kind,
            "jobs": [_job_row(record, _job_amount(record, scoped), as_of) for record in chosen[:CONTRIBUTOR_LIMIT]],
            "eligible_job_count": len(eligible),
            "excluded_job_count": len(records) - len(eligible),
            "limit": CONTRIBUTOR_LIMIT,
        },
        "statistics": tool_statistics(records),
        "meta": _meta(session, identity, scoped, revision, records, undated),
    }


def window_detail(
    session: Session, identity: Identity, query: ReportQuery,
    window_from: datetime, window_to: datetime,
) -> dict:
    """The page's matching jobs that have cost inside one chart interval.

    The interval is clipped to the report period. Which jobs match is decided
    by the page's own filters over the whole period, so a cost or coverage
    filter means the same here as on the page; each job then carries only the
    part of its cost inside the interval. Totals describe every such job,
    whatever page of them is returned.
    """
    lower = max(window_from, query.from_time) if query.from_time else window_from
    upper = min(window_to, query.to_time) if query.to_time else window_to
    if lower >= upper:
        raise HTTPException(422, "The interval must overlap the report period")
    facts = _load_job_facts(session, identity, query)
    period_undated: list[dict] = []
    period = _records_from_facts(facts, query, period_undated)
    matching = {record["id"] for record in period}
    window = query.model_copy(update={
        "from_time": lower, "to_time": upper, "min_cost": None, "max_cost": None, "quality": None,
    })
    records = [record for record in _records_from_facts(facts, window) if record["id"] in matching]
    known = sorted(
        (record for record in records if record["amount"] is not None),
        key=lambda record: (-record["amount"], record["id"]),
    )
    missing = sorted((record for record in records if record["amount"] is None), key=lambda r: r["id"])
    ordered = known + missing
    page = ordered[query.offset:query.offset + query.limit]
    return {
        "from": lower, "to": upper,
        "amount": _money(_sum_known(record["amount"] for record in records)),
        "job_count": len(records),
        "incomplete_job_count": sum(r["quality"] in INCOMPLETE_QUALITIES for r in records),
        "provisional": any(
            record["state"] in EXECUTING_STATES
            or any(lifetime.observed_end is None for _, lifetime in record["pairs"])
            for record in records
        ),
        "by_status": _status_pieces(records, lambda record: record["amount"]),
        "items": [_job_row(record, record["amount"], facts.as_of) for record in page],
        "total": len(ordered), "limit": query.limit, "offset": query.offset,
        "meta": _meta(session, identity, query, facts.revision, period, period_undated),
    }
