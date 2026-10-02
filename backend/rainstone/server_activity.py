"""Recorded tool execution on the configured Galaxy host, independent of cost."""

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from rainstone.auth import Identity
from rainstone.models import CapacityRelationship, ExecutionAttempt, Job, LifetimeAttempt, ResourceLifetime

DOT_WINDOW = timedelta(days=7)
MAX_DOTS = 500
MAX_STEPS = 2000


def merge_windows(windows: list[dict]) -> list[dict]:
    """One job's overlapping attempts count once; gaps between retries remain."""
    merged = []
    for window in sorted(windows, key=lambda row: (row["job_id"], row["from"], row["to"])):
        if merged and merged[-1]["job_id"] == window["job_id"] and window["from"] <= merged[-1]["to"]:
            previous = merged[-1]
            previous["to"] = max(previous["to"], window["to"])
            previous["running"] = previous["running"] or window["running"]
        else:
            merged.append(dict(window))
    return sorted(merged, key=lambda row: (row["from"], row["to"], row["job_id"]))


def concurrency(windows: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Exact half-open intervals of concurrent jobs, never a utilization estimate."""
    events = defaultdict(int)
    for window in windows:
        events[window["from"]] += 1
        events[window["to"]] -= 1
    previous, count = start, 0
    steps = []
    for instant, change in sorted(events.items()):
        if not change:
            continue
        if instant > previous:
            steps.append({"from": previous, "to": instant, "count": count})
        count += change
        previous = instant
    if previous < end:
        steps.append({"from": previous, "to": end, "count": count})
    return steps


def activity(session: Session, identity: Identity, launch: dict) -> dict | None:
    start = datetime.fromisoformat(launch["launch_at"]) if launch["launch_at"] else None
    end = datetime.fromisoformat(launch["as_of"]) if launch["as_of"] else None
    if start is None or end is None or end <= start:
        return None
    statement = (
        select(
            Job.id.label("job_id"), Job.source_id, Job.state,
            ExecutionAttempt.id.label("attempt_id"), ExecutionAttempt.runner,
            ExecutionAttempt.tool_started_at, ExecutionAttempt.tool_finished_at,
            ResourceLifetime.resource_uid,
            ResourceLifetime.facts["verified_vm_identity"].as_boolean().label("verified"),
        )
        .join(ExecutionAttempt, ExecutionAttempt.job_id == Job.id)
        .join(LifetimeAttempt, LifetimeAttempt.attempt_id == ExecutionAttempt.id)
        .join(ResourceLifetime, ResourceLifetime.id == LifetimeAttempt.lifetime_id)
        .where(
            Job.tenant_id == identity.tenant_id,
            ResourceLifetime.tenant_id == identity.tenant_id,
            ResourceLifetime.capacity_relationship == CapacityRelationship.existing,
            ExecutionAttempt.runner.in_(("local", "kubernetes")),
            ExecutionAttempt.tool_started_at < end,
            or_(ExecutionAttempt.tool_finished_at > start, ExecutionAttempt.tool_finished_at.is_(None)),
        )
    )
    if not identity.is_admin:
        statement = statement.where(Job.owner_id == identity.owner_id)
    provider_name = f"gce://{launch.get('project')}/{launch.get('zone')}/{launch.get('name')}"
    windows, seen = [], set()
    for row in session.execute(statement.execution_options(yield_per=1000)):
        if row.attempt_id in seen or row.state in {"new", "paused"}:
            continue
        exact = row.resource_uid in (launch["resource_uid"], provider_name)
        # Existing Kubernetes placement is established by the collector's
        # configured host node aliases when the node lacks a provider identity.
        alias = row.runner == "kubernetes" and not row.verified
        if not exact and not alias:
            continue
        finished = row.tool_finished_at
        running = finished is None and row.state in {"running", "queued", "resubmitted"}
        if finished is None and not running:
            continue
        left, right = max(start, row.tool_started_at), min(end, finished or end)
        if right <= left:
            continue
        seen.add(row.attempt_id)
        windows.append({
            "job_id": str(row.job_id), "source_id": row.source_id,
            "from": left, "to": right, "running": running,
        })
    windows = merge_windows(windows)
    steps = concurrency(windows, start, end)
    kind = "dots" if end - start <= DOT_WINDOW and len(windows) <= MAX_DOTS else "steps"
    if len(steps) > MAX_STEPS:
        kind = "hidden"
    return {
        "from": start, "to": end, "kind": kind,
        "job_count": len({window["job_id"] for window in windows}),
        "intervals": windows if kind == "dots" else [],
        "steps": steps if kind != "hidden" else [],
    }
