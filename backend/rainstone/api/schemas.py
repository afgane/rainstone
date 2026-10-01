from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ObservationWindow(APIModel):
    from_: datetime | None = None
    to: datetime | None = None
    timezone: str
    semantics: str
    mode: str

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Coverage(APIModel):
    jobs: int
    priced: int
    incomplete: int
    known_zero: int
    temporally_unattributed: int


class UndatedEvidence(APIModel):
    """Jobs a dated report leaves out because their cost has no usable timing."""

    job_count: int
    amount: str | None
    incomplete: int


class PriceList(APIModel):
    catalog_id: str
    observed_at: datetime
    url: str | None


class ReportMeta(APIModel):
    basis: Literal["additional", "allocated"]
    currency: Literal["USD"]
    applied_filters: dict[str, Any]
    observation_window: dict[str, Any]
    revision_id: str | None
    calculation_version: str | None
    as_of: datetime | None
    priced_subtotal: str | None
    coverage: Coverage
    undated: UndatedEvidence | None = None
    price_list: PriceList | None = None


class ServerPrice(APIModel):
    price_version_id: str
    catalog_id: str
    effective_from: datetime | None
    observed_at: datetime | None
    kind: str | None


class CurrentLaunch(APIModel):
    """The Galaxy server's current running session; report filters never apply."""

    scope: str
    currency: Literal["USD"]
    resource_uid: str | None
    name: str | None
    project: str | None
    zone: str | None
    region: str | None
    machine_type: str | None
    purchase_model: str | None
    state: str | None
    descriptor_source: str | None
    launch_at: datetime | None
    launch_source: str | None
    first_observed_at: datetime | None
    observed_at: datetime | None
    ended_at: datetime | None
    as_of: datetime | None
    stale: bool
    stale_reason: str | None
    hourly_rate: str | None
    hourly_rate_unavailable_reason: str | None
    price: ServerPrice | None
    total_since_launch: str | None
    known_subtotal: str | None
    completeness: Literal["complete", "partial", "unavailable"]
    unavailable_reason: str | None
    elapsed_seconds: str | None
    billed_seconds: str | None
    calculation_version: str
    calculation_revision: str | None


class SummaryResponse(ReportMeta):
    amount: str | None
    job_count: int
    priced_job_count: int
    unpriced_job_count: int
    known_zero_job_count: int
    failed_spend: str
    failed_job_count: int
    failed_incomplete_job_count: int
    repeated_job_spend: str
    repeated_job_count: int
    repeat_attempt_spend: str
    repeat_attempt_shared_spend: str
    repeat_attempt_spend_complete: bool
    baseline_infrastructure_amount: str | None
    baseline_infrastructure_observed: dict[str, str] | None = None
    current_launch: CurrentLaunch | None = None
    can_view_infrastructure: bool
    demo: bool
    demo_period: dict[str, str] | None = None
    imported_snapshot: dict[str, Any] | None = None


JobOrigin = Literal["workflow", "individual", "unknown"]


class OriginRun(APIModel):
    """The earliest authorized root run that holds a job."""

    id: str
    workflow_name: str


class JobItem(APIModel):
    id: str
    source_id: str
    tool_id: str
    tool_name: str
    # Every version of the tool shares this key; it is what `tool_key` filters by.
    tool_key: str
    tool_version: str | None
    owner: str
    owner_id: str
    state: str
    runner: str | None
    destination: str | None
    created_at: datetime
    updated_at: datetime
    amount: str | None
    currency: Literal["USD"]
    quality: str
    reason: str
    cost_lines: int
    attempt_count: int
    repeat_attempt_count: int
    attempt_evidence: Literal["provider", "galaxy_record", "none"]
    observation_count: int
    capacities: list[str]
    unattributed_amount: str
    temporally_unattributed: bool
    completed_at: datetime | None
    # Set on job list rows: whether a recorded workflow run holds the job, and
    # how long its tool executed, whatever part of that the period holds.
    origin: JobOrigin | None = None
    origin_run: OriginRun | None = None
    origin_run_count: int = 0
    duration_seconds: int | None = None
    duration_running: bool = False


class JobListResponse(APIModel):
    items: list[JobItem]
    total: int
    limit: int
    offset: int
    undated_items: list[JobItem] = []
    undated_offset: int = 0
    meta: ReportMeta


ComparisonStatus = Literal[
    "available", "not_recorded", "invalid_value", "unsupported_scope",
    "request_unavailable", "duration_unavailable",
]


class CpuUse(APIModel):
    """Average CPU over the matched execution; there is no peak or history."""

    status: ComparisonStatus
    reason: str | None
    cpu_seconds: str | None
    duration_seconds: str | None
    average_cores: str | None
    requested_vcpu: str | None
    request_fraction: str | None


class MemoryUse(APIModel):
    """Peak memory over the matched execution, in bytes."""

    status: ComparisonStatus
    reason: str | None
    peak_bytes: str | None
    source: str | None
    requested_memory_mib: str | None
    request_fraction: str | None


class RecordedMetric(APIModel):
    plugin: str
    name: str
    value: str
    unit: str | None


class JobResourceUse(APIModel):
    measurement_scope: Literal["single_execution", "unestablished"]
    scope_reason: str | None
    cpu: CpuUse
    memory: MemoryUse
    metrics: list[RecordedMetric]


class JobDetailResponse(JobItem):
    # The period's share of the job; everything below `full_` is the whole job.
    interval_amount: str | None
    full_job_amount: str | None
    full_quality: str
    full_reason: str
    full_capacities: list[str]
    started_at: datetime | None
    finished_at: datetime | None
    duration_seconds: int | None
    duration_running: bool
    duration_cutoff: datetime | None
    before_start_seconds: int | None
    timing_issue: Literal["finished_before_started", "started_before_submitted"] | None
    basis: str
    attempts: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    resource_use: JobResourceUse
    revision_id: str | None
    cost: dict[str, Any]


class ToolStatistics(APIModel):
    cohort: str
    sample_count: int
    excluded_count: int
    mean: str | None
    median: str | None
    p95: str | None
    method: str
    approximate: bool


class ToolItem(APIModel):
    tool_id: str
    tool_name: str
    tool_version: str | None
    job_count: int
    amount: str | None
    priced_count: int
    incomplete_count: int
    statistics: ToolStatistics


class ToolListResponse(APIModel):
    items: list[ToolItem]
    total: int
    meta: ReportMeta


class InvocationItem(APIModel):
    id: str
    source_id: str
    workflow_id: str
    workflow_key: str
    workflow_name: str
    workflow_version: str | None
    parent_id: str | None
    state: str
    run_status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: int | None = None
    job_count: int
    run_job_count: int
    amount: str | None
    run_total: str | None
    run_total_complete: bool
    currency: Literal["USD"]
    unpriced_job_count: int
    run_unpriced_job_count: int
    reused_job_count: int
    timing_unavailable: bool
    # The run's cost as the charts draw it, counting a shared job once.
    chart_amount: str | None = None
    shared_job_count: int = 0


class RunTotals(APIModel):
    amount: str | None
    incomplete_run_count: int
    shared_job_count: int
    run_count: int
    by_status: dict[str, int]
    workflow_count: int
    unfiltered_run_count: int


class WorkflowOption(APIModel):
    key: str
    name: str
    run_count: int


class RunFilterOptions(APIModel):
    by_status: dict[str, int]
    workflows: list[WorkflowOption]


class InvocationListResponse(APIModel):
    items: list[InvocationItem]
    total: int
    limit: int
    offset: int
    totals: RunTotals
    filter_options: RunFilterOptions
    meta: ReportMeta


class RunJobStep(APIModel):
    invocation_id: str
    workflow_name: str
    step_key: str
    relationship: str
    nested: bool


class RunJob(APIModel):
    """One distinct job of the whole run, however many steps it belongs to."""

    id: str
    source_id: str
    tool_id: str
    tool_name: str
    tool_version: str | None
    state: str
    quality: str
    # Whole-run amount; null is unknown, never zero.
    amount: str | None
    attribution: Literal["individual", "known_zero", "unknown", "unsupported"]
    environment: str
    capacities: list[str]
    cost_entity_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    # Observed tool execution time; null when it never started or is unreliable.
    duration_seconds: int | None
    duration_running: bool
    attempt_count: int
    reused: bool
    order: int
    steps: list[RunJobStep]


class CostEntity(APIModel):
    """A charge that produced cost in the run, however many jobs point at it."""

    id: str
    kind: Literal["batch_job", "vm_session"]
    amount: str
    currency: Literal["USD"]
    scope: Literal["run"]
    environment: str
    complete: bool
    job_ids: list[str]


class CostBreakdownFacts(APIModel):
    status: Literal["available", "unavailable"]
    reason: str | None
    currency: Literal["USD"]
    known_subtotal: str | None
    complete: bool
    job_count: int
    cost_entity_count: int
    known_zero_job_count: int
    unknown_job_count: int


class InvocationDetailResponse(InvocationItem):
    jobs: list[RunJob]
    cost_entities: list[CostEntity]
    cost_breakdown: CostBreakdownFacts
    unavailable_step_count: int
    children: list[InvocationItem]
    meta: ReportMeta


class BreakdownRun(APIModel):
    id: str
    amount: str | None
    run_total: str | None
    chart_amount: str | None
    shared_job_count: int
    run_total_complete: bool
    status: str
    started_at: datetime
    duration_seconds: int | None = None


class Remainder(APIModel):
    count: int
    amount: str
    failed: int
    running: int
    # Only a workflow's remainder is selectable, by this exact run and amount.
    boundary: dict[str, str] | None = None


class WholeRunRange(APIModel):
    minimum: str | None
    maximum: str | None
    included_run_count: int
    excluded_run_count: int


class BreakdownGroup(APIModel):
    key: str
    name: str
    run_count: int
    by_status: dict[str, int] = {}
    amount: str | None
    incomplete_run_count: int
    runs: list[BreakdownRun]
    remainder: Remainder
    whole_run_range: WholeRunRange


class BreakdownResponse(APIModel):
    groups: list[BreakdownGroup]
    meta: ReportMeta


class TimelinePiece(APIModel):
    id: str
    amount: str
    status: str


class TimelineAxis(APIModel):
    """The range a chart draws, written like its buckets' own instants."""

    from_: datetime = Field(alias="from")
    to: datetime

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TimelineBucket(APIModel):
    from_: datetime = Field(alias="from")
    to: datetime
    amount: str | None
    run_count: int
    by_status: dict[str, int] = {}
    incomplete_run_count: int
    provisional: bool
    pieces: list[TimelinePiece]
    remainder: Remainder

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TimelineResponse(APIModel):
    bucket: Literal["hour", "day", "week"]
    buckets: list[TimelineBucket]
    axis: TimelineAxis | None
    runs: dict[str, dict[str, Any]] = {}
    label: str
    unplaced: dict[str, Any] | None = None
    meta: ReportMeta


class CostPiece(APIModel):
    key: Literal["runs", "individual"]
    kind: Literal["runs", "individual"]
    name: str
    amount: str
    job_count: int
    run_count: int
    failed: int
    running: int


class CostBucket(APIModel):
    from_: datetime = Field(alias="from")
    to: datetime
    amount: str | None
    job_count: int
    run_count: int
    failed_job_count: int
    running_job_count: int
    incomplete_job_count: int
    provisional: bool
    pieces: list[CostPiece]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class WorkloadTotals(APIModel):
    amount: str | None
    job_count: int
    by_outcome: dict[str, int]
    run_count: int
    workflow_count: int
    individual_job_count: int


class CostTimelineResponse(APIModel):
    bucket: Literal["hour", "day", "week"]
    buckets: list[CostBucket]
    axis: TimelineAxis | None
    totals: WorkloadTotals
    label: str
    unplaced: dict[str, Any] | None = None
    meta: ReportMeta


class StatusPiece(APIModel):
    """Known cost and job counts of one recorded job status."""

    status: Literal["completed", "running", "failed", "other"]
    amount: str | None
    job_count: int
    incomplete_job_count: int


class JobTotals(APIModel):
    amount: str | None
    job_count: int
    tool_count: int
    incomplete_job_count: int
    known_zero_job_count: int
    by_status: list[StatusPiece]


class ToolVersion(APIModel):
    version: str | None
    job_count: int


class ToolFamily(APIModel):
    key: str
    name: str
    tool_ids: list[str]
    versions: list[ToolVersion]
    job_count: int
    amount: str | None
    incomplete_job_count: int
    known_zero_job_count: int
    category: Literal["ranked", "server", "zero", "unavailable"]
    by_status: list[StatusPiece]


class ToolSection(APIModel):
    """Tools outside the ranking; the counts ignore the tool search, the list does not."""

    tool_count: int
    job_count: int
    groups: list[ToolFamily]


class ToolRemainder(APIModel):
    tool_count: int
    job_count: int
    amount: str | None
    incomplete_job_count: int


class JobBreakdownResponse(APIModel):
    groups: list[ToolFamily]
    total: int
    ranked_tool_count: int
    remainder: ToolRemainder
    scale: str | None
    server: ToolSection
    zero: ToolSection
    unavailable: ToolSection
    totals: JobTotals
    meta: ReportMeta


class JobBucket(APIModel):
    from_: datetime = Field(alias="from")
    to: datetime
    amount: str | None
    job_count: int
    incomplete_job_count: int
    provisional: bool
    by_status: list[StatusPiece]

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class JobTimelineResponse(APIModel):
    bucket: Literal["hour", "day", "week"]
    buckets: list[JobBucket]
    axis: TimelineAxis | None
    totals: JobTotals
    label: str
    unplaced: dict[str, Any] | None = None
    meta: ReportMeta


class ScopedJob(APIModel):
    """A job in a drawer list. `amount` is the drawer's scope; the duration is the whole execution."""

    id: str
    tool_name: str
    tool_id: str
    tool_version: str | None
    state: str
    amount: str | None
    quality: str
    capacities: list[str]
    created_at: datetime
    duration_seconds: int | None
    duration_running: bool


class Contributors(APIModel):
    kind: Literal["ranked", "server", "zero", "unavailable"]
    jobs: list[ScopedJob]
    eligible_job_count: int
    excluded_job_count: int
    limit: int


class ToolDetailResponse(APIModel):
    key: str
    name: str
    tool_ids: list[str]
    versions: list[ToolVersion]
    amount: str | None
    job_count: int
    incomplete_job_count: int
    known_zero_job_count: int
    category: Literal["ranked", "server", "zero", "unavailable"] | None
    by_status: list[StatusPiece]
    contributors: Contributors
    statistics: ToolStatistics
    meta: ReportMeta


class WindowDetailResponse(APIModel):
    from_: datetime = Field(alias="from")
    to: datetime
    amount: str | None
    job_count: int
    incomplete_job_count: int
    provisional: bool
    by_status: list[StatusPiece]
    items: list[ScopedJob]
    total: int
    limit: int
    offset: int
    meta: ReportMeta

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class DailyItem(APIModel):
    date: str
    # Null when no job of the day has a known cost; an observed zero is "0".
    amount: str | None
    currency: Literal["USD"]
    job_count: int
    incomplete_count: int
    provisional: bool
    by_runner: dict[str, str]
    by_owner: dict[str, str]
    by_tool: dict[str, str]


class DailyResponse(APIModel):
    items: list[DailyItem]
    label: str
    temporally_unattributed_count: int
    temporally_unattributed_subtotal: str
    meta: ReportMeta


class UserItem(APIModel):
    owner_id: str
    label: str
    job_count: int
    amount: str | None
    priced_count: int
    incomplete_count: int


class UserListResponse(APIModel):
    items: list[UserItem]
    total: int
    meta: ReportMeta


class InfrastructureResponse(APIModel):
    items: list[dict[str, Any]]
    amount: str | None
    currency: Literal["USD"]
    scope: str
    allocation_supported: bool
    allocation_reason: str
    observation_window: dict[str, Any]
    observed_coverage: dict[str, str] | None = None
    revision_id: str | None
    as_of: datetime | None
    current_launch: CurrentLaunch


class FreshnessResponse(APIModel):
    sources: list[dict[str, Any]]
    overall_status: str
    revision_id: str | None
    observation_gaps: list[dict[str, Any]]


class MeResponse(APIModel):
    source_id: str
    label: str
    is_admin: bool
    auth_mode: str
    attribution: str
    capabilities: dict[str, bool]


class StatusCheck(APIModel):
    name: str
    status: str
    detail: str
    facts: dict[str, Any]


class StatusResponse(APIModel):
    generated_at: str
    overall_status: str
    auth_mode: str
    tenant: str
    checks: list[StatusCheck]
    failed_capabilities: list[str]
    recorded_reports: list[dict[str, Any]] = []


class CatalogResponse(APIModel):
    active_catalog_id: str | None
    observed_at: str | None
    imported_at: str | None
    signature_key_id: str | None
    signature_verified: bool = False
    provenance: dict[str, Any]
    supported: list[dict[str, Any]]
