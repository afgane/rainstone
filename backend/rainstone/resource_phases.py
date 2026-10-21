"""Observed VM phases; pricing remains in the normal lifetime calculation."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

ZERO = Decimal("0")
PHASES = ("provisioning", "execution", "idle", "teardown", "unattributed")


@dataclass(frozen=True)
class PhaseWindow:
    phase: str
    start: datetime | None
    end: datetime | None
    reason: str | None = None


def phase_windows(start: datetime | None, end: datetime | None, attempts: Sequence,
                  *, shared_job_count: int = 1) -> list[PhaseWindow]:
    def unknown(reason: str) -> list[PhaseWindow]:
        return [PhaseWindow("unattributed", start, end, reason)]

    if start is None or end is None or end <= start:
        return unknown("The resource lifetime is incomplete or invalid.")
    if shared_job_count > 1:
        return unknown("The resource is shared by jobs without a cost allocation policy.")
    if not attempts or any(a.tool_started_at is None or a.tool_finished_at is None for a in attempts):
        return unknown("An execution start or finish was not recorded for every attempt on this resource.")
    windows = sorted((a.tool_started_at, a.tool_finished_at) for a in attempts)
    if any(lower < start or upper > end or upper < lower for lower, upper in windows):
        return unknown("An execution timestamp is invalid or falls outside the resource lifetime.")
    merged: list[tuple[datetime, datetime]] = []
    for lower, upper in windows:
        if merged and lower <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(upper, merged[-1][1]))
        else:
            merged.append((lower, upper))
    phases = [PhaseWindow("provisioning", start, merged[0][0])]
    previous = merged[0][0]
    for lower, upper in merged:
        if lower > previous:
            phases.append(PhaseWindow("idle", previous, lower))
        phases.append(PhaseWindow("execution", lower, upper))
        previous = upper
    phases.append(PhaseWindow("teardown", previous, end))
    return [phase for phase in phases if phase.end > phase.start]


def summarize_phases(phases: Sequence[PhaseWindow], windows: Sequence[tuple[datetime, datetime]],
                     allocations: Sequence[dict], *, priced: bool) -> list[dict]:
    """Persist phase totals, including null costs when timing or pricing is absent."""
    result = []
    for name in PHASES:
        members = [phase for phase in phases if phase.phase == name]
        if not members:
            continue
        seconds = sum((
            Decimal(str(max(0, (min(phase.end, upper) - max(phase.start, lower)).total_seconds())))
            for phase in members if phase.start is not None and phase.end is not None
            for lower, upper in windows
        ), ZERO)
        if name == "unattributed":
            seconds = sum((Decimal(str((upper - lower).total_seconds())) for lower, upper in windows), ZERO)
        selected = [allocation for allocation in allocations if allocation.get("phase") == name]
        result.append({
            "phase": name,
            "started_at": min((phase.start for phase in members if phase.start), default=None),
            "finished_at": max((phase.end for phase in members if phase.end), default=None),
            "observed_seconds": str(seconds) if windows else None,
            "charged_seconds": str(sum((Decimal(a["charged_seconds"]) for a in selected), ZERO)) if priced else None,
            "amount": str(sum((Decimal(a["amount"]) for a in selected), ZERO)) if priced else None,
            **({"reason": members[0].reason} if members[0].reason else {}),
        })
    # Cost-line details are JSON, so dates cross the persistence boundary here.
    for entry in result:
        for key in ("started_at", "finished_at"):
            entry[key] = entry[key].isoformat() if entry[key] else None
    return result
