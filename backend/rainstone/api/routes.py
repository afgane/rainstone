import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from rainstone import jobs_report, overview_details
from rainstone.api.schemas import (
    BreakdownResponse,
    CatalogResponse,
    CostTimelineResponse,
    DailyResponse,
    FreshnessResponse,
    InfrastructureResponse,
    InvocationDetailResponse,
    InvocationListResponse,
    JobBreakdownResponse,
    JobDetailResponse,
    JobListResponse,
    JobTimelineResponse,
    MeResponse,
    OverviewDetailResponse,
    StatusResponse,
    SummaryResponse,
    TimelineResponse,
    ToolDetailResponse,
    ToolListResponse,
    UserListResponse,
    WindowDetailResponse,
)
from rainstone.auth import Identity, current_identity
from rainstone.catalog import coverage as catalog_coverage
from rainstone.config import Settings, get_settings
from rainstone.db import get_session
from rainstone.doctor import readiness, run_checks
from rainstone.overview import cost_timeline
from rainstone.report_query import (
    ReportQuery,
    RunReportQuery,
    cost_timeline_query,
    report_query,
    run_report_query,
)
from rainstone.reporting import (
    breakdown,
    daily,
    export_csv,
    freshness,
    infrastructure,
    invocation_detail,
    invocations,
    job_detail,
    list_jobs,
    summary,
    timeline,
    tools,
    users,
    validate_snapshot,
)

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    """Process liveness only: it must not depend on external services."""
    return {"status": "ok"}


@router.get("/ready")
def ready(
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Readiness: serve reports only against a migrated, enrolled instance."""
    state = readiness(session, settings)
    if not state["ready"]:
        response.status_code = 503
    return state


@router.get("/me", response_model=MeResponse)
def me(
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    return {
        "source_id": identity.source_id, "label": identity.label,
        "is_admin": identity.is_admin,
        "auth_mode": settings.auth_mode,
        "attribution": identity.attribution,
        "capabilities": {
            "infrastructure": identity.can_view_infrastructure,
            "users": identity.is_admin,
        },
    }


@router.get("/status", response_model=StatusResponse)
def status(
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Sanitized operational diagnostics: no DSNs, secrets or raw job data.

    Source and cloud findings come from the collector's and installation's recorded
    reports, because this process deliberately holds none of those credentials.
    """
    if not settings.diagnostics_enabled:
        raise HTTPException(404, "Diagnostics are disabled for this deployment")
    return run_checks(session, settings, context="web")


@router.get("/status/download")
def status_download(
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
    settings: Settings = Depends(get_settings),
) -> Response:
    if not settings.diagnostics_enabled:
        raise HTTPException(404, "Diagnostics are disabled for this deployment")
    payload = json.dumps(
        run_checks(session, settings, context="web"), indent=2, sort_keys=True, default=str
    )
    return Response(
        payload,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=rainstone-diagnostics.json"},
    )


@router.get("/catalog", response_model=CatalogResponse)
def catalog(
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return catalog_coverage(session)


@router.get("/summary", response_model=SummaryResponse)
def get_summary(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return summary(session, identity, query)


@router.get("/jobs", response_model=JobListResponse)
def get_jobs(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return list_jobs(session, identity, query)


# The literal Jobs routes come before the `{job_id}` route below.
@router.get("/jobs/breakdown", response_model=JobBreakdownResponse)
def get_job_breakdown(
    query: ReportQuery = Depends(report_query),
    tool_search: str | None = Query(default=None, max_length=200),
    group_limit: int = Query(default=jobs_report.DEFAULT_GROUP_LIMIT, ge=1, le=10000),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return jobs_report.breakdown(session, identity, query, tool_search, group_limit)


@router.get("/jobs/timeline", response_model=JobTimelineResponse)
def get_job_timeline(
    query: RunReportQuery = Depends(cost_timeline_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return jobs_report.timeline(session, identity, query)


@router.get("/jobs/tool-detail", response_model=ToolDetailResponse)
def get_tool_detail(
    tool_key: str = Query(min_length=1, max_length=500),
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return jobs_report.tool_detail(session, identity, query, tool_key)


@router.get("/jobs/window-detail", response_model=WindowDetailResponse)
def get_window_detail(
    window_from: datetime,
    window_to: datetime,
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    for label, value in (("window_from", window_from), ("window_to", window_to)):
        if value.utcoffset() is None:
            raise HTTPException(422, f"{label} must include an explicit UTC offset")
    if window_from >= window_to:
        raise HTTPException(422, "The interval must satisfy window_from < window_to")
    return jobs_report.window_detail(session, identity, query, window_from, window_to)


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
def get_job(
    job_id: uuid.UUID,
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    result = job_detail(session, identity, job_id, query)
    if result is None:
        raise HTTPException(404, "Job not found")
    return result


@router.get("/tools", response_model=ToolListResponse)
def get_tools(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return tools(session, identity, query)


@router.get("/invocations", response_model=InvocationListResponse)
def get_invocations(
    query: RunReportQuery = Depends(run_report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return invocations(session, identity, query)


# The two literal routes come before the `{invocation_id}` route below.
@router.get("/invocations/breakdown", response_model=BreakdownResponse)
def get_invocation_breakdown(
    query: RunReportQuery = Depends(run_report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return breakdown(session, identity, query)


@router.get("/invocations/timeline", response_model=TimelineResponse)
def get_invocation_timeline(
    query: RunReportQuery = Depends(run_report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return timeline(session, identity, query)


@router.get("/invocations/{invocation_id}", response_model=InvocationDetailResponse)
def get_invocation(
    invocation_id: uuid.UUID,
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    result = invocation_detail(session, identity, invocation_id, query)
    if result is None:
        raise HTTPException(404, "Invocation not found")
    return result


@router.get("/timeline", response_model=CostTimelineResponse)
def get_cost_timeline(
    query: RunReportQuery = Depends(cost_timeline_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return cost_timeline(session, identity, query)


@router.get("/overview/details", response_model=OverviewDetailResponse)
def get_overview_details(
    scope: overview_details.Scope,
    kind: overview_details.Kind,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    for label, value in (("window_from", window_from), ("window_to", window_to)):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, f"{label} must include an explicit UTC offset")
    if window_from and window_to and window_from >= window_to:
        raise HTTPException(422, "The interval must satisfy window_from < window_to")
    return overview_details.details(session, identity, query, scope, kind, window_from, window_to)


@router.get("/daily", response_model=DailyResponse)
def get_daily(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return daily(session, identity, query)


@router.get("/users", response_model=UserListResponse)
def get_users(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return users(session, identity, query)


@router.get("/infrastructure", response_model=InfrastructureResponse)
def get_infrastructure(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return infrastructure(session, identity, query, include_activity=True)


@router.get("/export/jobs.csv")
def get_export(
    query: ReportQuery = Depends(report_query),
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> StreamingResponse:
    validate_snapshot(session, identity, query)
    return StreamingResponse(
        export_csv(session, identity, query),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=rainstone-jobs.csv"},
    )


@router.get("/freshness", response_model=FreshnessResponse)
def get_freshness(
    session: Session = Depends(get_session),
    identity: Identity = Depends(current_identity),
) -> dict:
    return freshness(session, identity)
