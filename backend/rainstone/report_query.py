import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ReportQuery(BaseModel):
    """The single filter contract shared by every reporting endpoint."""

    model_config = ConfigDict(frozen=True)
    basis: Literal["additional", "allocated"] = "additional"
    currency: Literal["USD"] = "USD"
    mode: Literal["accrued", "completed"] = "accrued"
    from_time: datetime | None = None
    to_time: datetime | None = None
    timezone: str = "UTC"
    search: str | None = None
    tool_id: str | None = None
    tool_version: str | None = None
    invocation_id: str | None = None
    workflow_id: str | None = None
    owner: str | None = None
    state: str | None = None
    runner: str | None = None
    destination: str | None = None
    capacity: str | None = None
    quality: str | None = None
    min_cost: Decimal | None = None
    max_cost: Decimal | None = None
    revision: str | None = None
    limit: int = 50
    offset: int = 0
    # The undated list pages on its own, beside the period's results.
    undated_offset: int = 0
    sort: str = "created_at"
    direction: Literal["asc", "desc"] = "desc"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


def report_query(
    basis: Literal["additional", "allocated"] = "additional",
    currency: str = "USD",
    mode: Literal["accrued", "completed"] = "accrued",
    from_time: datetime | None = Query(default=None, alias="from"),
    to_time: datetime | None = Query(default=None, alias="to"),
    timezone: str = "UTC",
    search: str | None = Query(default=None, max_length=200),
    tool_id: str | None = Query(default=None, max_length=500),
    tool_version: str | None = Query(default=None, max_length=100),
    invocation_id: str | None = None,
    workflow_id: str | None = Query(default=None, max_length=300),
    owner: str | None = Query(default=None, max_length=200),
    state: str | None = Query(default=None, max_length=40),
    runner: str | None = Query(default=None, max_length=100),
    destination: str | None = Query(default=None, max_length=200),
    capacity: str | None = Query(default=None, max_length=40),
    quality: str | None = Query(default=None, max_length=40),
    min_cost: Decimal | None = Query(default=None, ge=0),
    max_cost: Decimal | None = Query(default=None, ge=0),
    revision: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    undated_offset: int = Query(default=0, ge=0),
    sort: str = Query(default="created_at", max_length=40),
    direction: Literal["asc", "desc"] = "desc",
) -> ReportQuery:
    if currency != "USD":
        raise HTTPException(422, "Only USD reporting is currently supported")
    for label, value in (("from", from_time), ("to", to_time)):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, f"{label} must include an explicit UTC offset")
    if from_time and to_time and from_time >= to_time:
        raise HTTPException(422, "The report interval must satisfy from < to")
    try:
        return ReportQuery(**locals() | {"currency": "USD"})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


RunStatus = Literal["completed", "failed", "running", "cancelled"]
RunSort = Literal["started_at", "amount", "run_total", "duration"]
RunBucket = Literal["auto", "hour", "day", "week"]
DEFAULT_RUN_LIMIT = 20
MAX_RUN_LIMIT = 200


class RunReportQuery(ReportQuery):
    """The shared contract plus the filters only the workflow run endpoints know.

    Search and every field below narrow the list, the totals, the breakdown and
    the timeline alike. Sorting and paging are presentation controls.
    """

    limit: int = DEFAULT_RUN_LIMIT
    # A run's stored workflow: its family ID, then its workflow ID, then its name.
    workflow_key: str | None = None
    run_status: RunStatus | None = None
    # Selects runs with job timing inside a window that lies within the period.
    focus_from: datetime | None = None
    focus_to: datetime | None = None
    # The period share of the first run inside a grouped segment, and that
    # run's ID: together they name an exact suffix of the amount-and-ID order.
    max_run_amount: Decimal | None = None
    boundary_run_id: str | None = None
    run_sort: RunSort = "started_at"
    bucket: RunBucket = "auto"

    @field_validator("limit")
    @classmethod
    def bounded_limit(cls, value: int) -> int:
        if not 1 <= value <= MAX_RUN_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_RUN_LIMIT}")
        return value

    @field_validator("max_run_amount")
    @classmethod
    def nonnegative_amount(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (value < 0 or not value.is_finite()):
            raise ValueError("max_run_amount must be a nonnegative number")
        return value

    @field_validator("boundary_run_id")
    @classmethod
    def canonical_run_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise ValueError("boundary_run_id must be a run UUID") from exc

    @model_validator(mode="after")
    def consistent_selection(self) -> "RunReportQuery":
        if (self.focus_from is None) != (self.focus_to is None):
            raise ValueError("focus_from and focus_to must be supplied together")
        if self.focus_from is not None and self.focus_to is not None:
            for label, value in (("focus_from", self.focus_from), ("focus_to", self.focus_to)):
                if value.utcoffset() is None:
                    raise ValueError(f"{label} must include an explicit UTC offset")
            if self.focus_from >= self.focus_to:
                raise ValueError("The focus window must satisfy focus_from < focus_to")
            if self.from_time and self.focus_from < self.from_time:
                raise ValueError("The focus window must lie inside the period")
            if self.to_time and self.focus_to > self.to_time:
                raise ValueError("The focus window must lie inside the period")
        if (self.max_run_amount is None) != (self.boundary_run_id is None):
            raise ValueError("max_run_amount and boundary_run_id must be supplied together")
        if self.max_run_amount is not None and self.workflow_key is None:
            raise ValueError("A grouped selection needs workflow_key")
        return self


def as_run_query(query: ReportQuery) -> RunReportQuery:
    """A run query carrying a plain query's shared fields and no run filters."""
    if isinstance(query, RunReportQuery):
        return query
    return RunReportQuery(**query.model_dump(exclude={"limit"}))


def run_report_query(
    request: Request,
    shared: ReportQuery = Depends(report_query),
    workflow_key: str | None = Query(default=None, max_length=300),
    run_status: RunStatus | None = None,
    focus_from: datetime | None = None,
    focus_to: datetime | None = None,
    max_run_amount: Decimal | None = Query(default=None, ge=0),
    boundary_run_id: str | None = Query(default=None, max_length=36),
    run_sort: RunSort = "started_at",
    bucket: RunBucket = "auto",
) -> RunReportQuery:
    # The shared dependency defaults to a page of 50; run pages default to 20.
    limit = shared.limit if "limit" in request.query_params else DEFAULT_RUN_LIMIT
    try:
        return RunReportQuery(
            **shared.model_dump(exclude={"limit"}), limit=limit, workflow_key=workflow_key,
            run_status=run_status, focus_from=focus_from, focus_to=focus_to,
            max_run_amount=max_run_amount, boundary_run_id=boundary_run_id,
            run_sort=run_sort, bucket=bucket,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
