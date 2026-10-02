import { exclusiveEnd, isTimezone, PERIOD_ORDER, resolvePeriod, type Period, type PeriodId } from "./periods";

export type Basis = "additional" | "allocated";
/** Views are named for the questions they answer, not for their endpoints. */
export type View =
  | "overview" | "runs" | "tool-runs" | "daily" | "users" | "server" | "status";

export interface ReportState {
  view: View;
  period: PeriodId;
  mode: "accrued" | "completed";
  fromTime: string;
  toTime: string;
  timezone: string;
  search: string;
  owner: string;
  toolId: string;
  toolVersion: string;
  /** Every version of one tool; the key the server groups the By tool chart by. */
  toolKey: string;
  invocationId: string;
  workflowId: string;
  state: string;
  runner: string;
  destination: string;
  capacity: string;
  quality: string;
  minCost: string;
  maxCost: string;
  sort: string;
  direction: "asc" | "desc";
  offset: number;
  revision?: string;
  // Filters and controls only the Workflow runs page has. They never travel
  // with job or tool requests.
  workflowKey: string;
  runStatus: RunStatus | "";
  focusFrom: string;
  focusTo: string;
  maxRunAmount: string;
  boundaryRunId: string;
  runSort: RunSort;
  runDirection: "asc" | "desc";
  runChart: "workflow" | "time";
  /** Which chart the Jobs page shows; independent of the Workflow runs page's. */
  jobsChart: JobsChart;
}

export type JobsChart = "tool" | "time";

/**
 * What the detail drawer can show: a run, a job, a tool's jobs, a Jobs chart
 * interval's jobs, or what lies behind an Overview figure.
 */
export type DrawerKind = "runs" | "tool-runs" | "tool" | "window" | "overview" | "guide";

export type RunStatus = "completed" | "failed" | "running" | "cancelled";
export type RunSort = "started_at" | "amount" | "run_total" | "duration";

export interface Meta {
  basis: Basis;
  currency: "USD";
  calculation_version: string | null;
  revision_id: string | null;
  as_of: string | null;
  priced_subtotal: string | null;
  observation_window: { from: string | null; to: string | null; timezone: string; semantics: string; mode: string };
  coverage: { jobs: number; priced: number; incomplete: number; known_zero: number; temporally_unattributed: number };
  /** Jobs a dated report leaves out because their cost has no usable timing. */
  undated: { job_count: number; amount: string | null; incomplete: number } | null;
  /** The price list current estimates come from, when it was read, and where it is published. */
  price_list: { catalog_id: string; observed_at: string; url: string | null } | null;
}

/**
 * The Galaxy server's current running session. It never follows report
 * filters; only its timestamps are formatted in the report timezone.
 */
export interface CurrentLaunch {
  scope: string;
  currency: "USD";
  resource_uid: string | null;
  name: string | null;
  machine_type: string | null;
  /** The whole server's published capacity; null when its shape is not known. */
  machine_capacity: MachineCapacity | null;
  region: string | null;
  zone: string | null;
  purchase_model: string | null;
  state: string | null;
  launch_at: string | null;
  launch_source: string | null;
  /** When the recorded session stopped; null while it runs. */
  ended_at: string | null;
  /** Seconds from launch to `as_of`, where the total stops. */
  elapsed_seconds: string | null;
  /** Where the figures stop: the last successful observation, or the stop time. */
  as_of: string | null;
  stale: boolean;
  stale_reason: string | null;
  hourly_rate: string | null;
  hourly_rate_unavailable_reason: string | null;
  price: { catalog_id: string; effective_from: string | null; observed_at: string | null; kind: string | null } | null;
  total_since_launch: string | null;
  known_subtotal: string | null;
  completeness: "complete" | "partial" | "unavailable";
  unavailable_reason: string | null;
  calculation_version: string;
  calculation_revision: string | null;
}

export interface Summary extends Meta {
  amount: string | null;
  job_count: number;
  priced_job_count: number;
  unpriced_job_count: number;
  known_zero_job_count: number;
  failed_spend: string;
  failed_job_count: number;
  failed_incomplete_job_count: number;
  /** The whole cost of jobs that had a repeat attempt. */
  repeated_job_spend: string;
  repeated_job_count: number;
  /** Only what the repeat attempts themselves used. */
  repeat_attempt_spend: string;
  repeat_attempt_shared_spend: string;
  repeat_attempt_spend_complete: boolean;
  baseline_infrastructure_amount: string | null;
  /** When the server was actually observed, not the window that was asked for. */
  baseline_infrastructure_observed: { from: string; to: string } | null;
  current_launch: CurrentLaunch | null;
  can_view_infrastructure: boolean;
  demo: boolean;
  demo_period: { from: string; to: string } | null;
  imported_snapshot: {
    captured_at: string | null;
    source_cutoffs: Record<string, string> | null;
    snapshot_digest: string | null;
    label: string | null;
  } | null;
}

/** Whether a recorded workflow run holds a job; `unknown` when the record cannot say. */
export type JobOrigin = "workflow" | "individual" | "unknown";

export interface Job {
  id: string; source_id: string; tool_id: string; tool_name: string;
  tool_key: string; tool_version: string | null;
  owner: string; owner_id: string; state: string; runner: string | null;
  destination: string | null; created_at: string; amount: string | null; currency: string;
  quality: string; reason: string; cost_lines: number; attempt_count: number;
  repeat_attempt_count: number; attempt_evidence: "provider" | "galaxy_record" | "none";
  capacities: string[]; temporally_unattributed: boolean;
  /** Set on job list rows only. */
  origin?: JobOrigin | null;
  /** The earliest run that holds the job, and how many runs hold it in all. */
  origin_run?: { id: string; workflow_name: string } | null;
  origin_run_count?: number;
  /** The tool's whole execution, whatever part of it the period holds; null when not recorded. */
  duration_seconds?: number | null;
  duration_running?: boolean;
}

export interface JobList {
  items: Job[]; total: number; limit: number; offset: number;
  /** Outside the period's totals; shown beside them, never counted in them. */
  undated_items: Job[];
  meta: Meta;
}

export interface Infrastructure {
  items: Array<Record<string, string>>; amount: string | null; scope: string;
  allocation_reason: string; observation_window: Record<string, string>;
  observed_coverage: { from: string; to: string } | null;
  current_launch: CurrentLaunch;
  activity: ServerActivity | null;
}

export interface ServerJobInterval {
  job_id: string; source_id: string; from: string; to: string; running: boolean;
}

export interface ServerJobStep { from: string; to: string; count: number }

export interface ServerActivity {
  from: string; to: string; kind: "dots" | "steps" | "hidden"; job_count: number;
  intervals: ServerJobInterval[]; steps: ServerJobStep[];
}

export interface Invocation {
  id: string; source_id: string; workflow_id: string; workflow_key: string; workflow_name: string;
  /** Galaxy's internal workflow ID, not a version number; it is never displayed. */
  workflow_version: string | null; parent_id: string | null; state: string;
  run_status: string; started_at: string;
  /** Null while the run is still running. */
  finished_at: string | null;
  /** Wall clock from the first job's submission; to the revision time while running. */
  duration_seconds: number | null;
  job_count: number; run_job_count: number;
  /** Cost accrued inside the selected period. */
  amount: string | null;
  /** The whole run, whatever period is selected. */
  run_total: string | null;
  run_total_complete: boolean;
  currency: string;
  unpriced_job_count: number; run_unpriced_job_count: number; reused_job_count: number;
  timing_unavailable: boolean;
  /** What the charts draw for this run, with a shared job counted under one run only. */
  chart_amount: string | null;
  shared_job_count: number;
}

/** How a job's cost reached the run: its own charge, a known zero, or not at all. */
export type JobAttribution = "individual" | "known_zero" | "unknown" | "unsupported";

export interface RunJobStep {
  invocation_id: string; workflow_name: string; step_key: string; relationship: string;
  /** Reached through a child workflow rather than the run itself. */
  nested: boolean;
}

/** One distinct job of the whole run, however many steps it belongs to. */
export interface RunJob {
  id: string; source_id: string; tool_id: string; tool_name: string; tool_version: string | null;
  state: string; quality: string;
  /** The job's whole cost. Null is unknown, never zero. */
  amount: string | null;
  attribution: JobAttribution;
  /** A verified capacity relationship, "multiple" for retries across several, or "unknown". */
  environment: string;
  capacities: string[];
  cost_entity_id: string | null;
  created_at: string; started_at: string | null; finished_at: string | null;
  /** Observed tool execution time; null when it never started or cannot be relied on. */
  duration_seconds: number | null;
  /** The job is still running, so its duration is elapsed so far. */
  duration_running: boolean;
  attempt_count: number;
  /** Its outputs were reused from an earlier job, so it added no new compute. */
  reused: boolean;
  /** Position in the run's execution order, from 1. */
  order: number;
  steps: RunJobStep[];
}

/** A charge that produced cost in the run, however many jobs point at it. */
export interface CostEntity {
  id: string; kind: "batch_job" | "vm_session"; amount: string; currency: "USD"; scope: "run";
  environment: string; complete: boolean; job_ids: string[];
  /** A virtual machine session's own name, when it has one. */
  label?: string | null;
}

export interface CostBreakdownFacts {
  status: "available" | "unavailable";
  reason: string | null;
  currency: "USD";
  known_subtotal: string | null;
  complete: boolean;
  job_count: number; cost_entity_count: number;
  known_zero_job_count: number; unknown_job_count: number;
}

/** A run opened in the drawer: the run, every job of the whole run, and where its cost came from. */
export interface InvocationDetail extends Invocation {
  jobs: RunJob[];
  cost_entities: CostEntity[];
  cost_breakdown: CostBreakdownFacts;
  /** Memberships to jobs the viewer cannot see; counted, never described. */
  unavailable_step_count: number;
  children: Invocation[];
  meta: Meta;
}

export interface MachineCapacity {
  vcpu: string; memory_mib: string;
  /** The GPUs the machine type always comes with; null for a machine without them. */
  gpu: { count: string; model: string } | null;
  source: "published_machine_shape";
}

/** One chargeable resource lifetime a job used. Amounts are the whole job's, never the period's. */
export interface JobResource {
  lifetime_id: string; resource_key: string; resource_uid: string; provider: string;
  machine_type: string | null;
  /** The machine's own size from Google's published shapes; null when its type is not one of them. */
  machine_capacity: MachineCapacity | null;
  region: string | null; zone: string | null;
  purchase_model: string | null; capacity_relationship: string;
  resource_started_at: string | null;
  /** Null while the resource is still in use, or when its end was never observed. */
  resource_finished_at: string | null;
  timing_method: string | null;
  /** The request the resource was made for: decimal strings, never a machine's capacity. */
  requested_vcpu: string | null; requested_memory_mib: string | null;
  amount: string | null; quality: string; reason: string;
  shared_attempt_ids: string[]; shared_attempt_count: number;
}

/** One observation of an execution; `observation` rows repeat one counted under another role. */
export interface JobExecution {
  id: string; source_attempt_id: string; runner: string; outcome: string;
  provider_outcome: string | null; exit_code: number | null;
  task_index: number | null; attempt_ordinal: number | null;
  tool_started_at: string | null; tool_finished_at: string | null;
  /** Null when the execution has no reliable interval; elapsed so far while it runs. */
  duration_seconds: number | null; duration_running: boolean;
  role: "first" | "repeat" | "observation";
  resource_keys: string[];
  /** Set only when this execution alone used every resource it is credited with. */
  amount: string | null;
  amount_shared_with_attempts: string[];
}

/**
 * Why a comparison with the request was or was not made. `unsupported_scope`
 * carries a reason: the counters cannot be tied to one execution on one resource,
 * or the request's scope is not the tool's.
 */
export type ComparisonStatus =
  | "available" | "not_recorded" | "invalid_value" | "unsupported_scope"
  | "request_unavailable" | "duration_unavailable";

/** Average CPU over the matched execution. Peak CPU and CPU history are not collected. */
export interface JobCpuUse {
  status: ComparisonStatus; reason: string | null;
  cpu_seconds: string | null; duration_seconds: string | null; average_cores: string | null;
  requested_vcpu: string | null;
  /** Average cores over requested vCPUs; above 1 is use above the request. */
  request_fraction: string | null;
}

/** Peak memory over the matched execution. */
export interface JobMemoryUse {
  status: ComparisonStatus; reason: string | null;
  peak_bytes: string | null;
  /** The cgroup metric the peak came from. */
  source: string | null;
  requested_memory_mib: string | null;
  request_fraction: string | null;
}

export interface RecordedMetric { plugin: string; name: string; value: string; unit: string | null }

export interface JobResourceUse {
  /** `unestablished` when the job's counters cannot be tied to one execution on one resource. */
  measurement_scope: "single_execution" | "unestablished";
  scope_reason: string | null;
  cpu: JobCpuUse; memory: JobMemoryUse;
  metrics: RecordedMetric[];
}

/** A job opened in the drawer. The `full_` fields and the lists describe the whole job. */
export interface JobDetail extends Job {
  revision_id: string | null; basis: Basis;
  /** The part of the job inside the selected period. */
  interval_amount: string | null;
  full_job_amount: string | null;
  full_quality: string; full_reason: string; full_capacities: string[];
  /** The union of reliable tool executions, matching the workflow run's job rows. */
  started_at: string | null; finished_at: string | null;
  duration_seconds: number | null; duration_running: boolean;
  /** Where a running job's figures stop: the snapshot's time. */
  duration_cutoff: string | null;
  /** Submission to the first tool start: waiting, provisioning and setup together. */
  before_start_seconds: number | null;
  timing_issue: "finished_before_started" | "started_before_submitted" | null;
  attempts: JobExecution[]; resources: JobResource[];
  resource_use: JobResourceUse;
}

/** The whole filtered set, never the loaded page. */
export interface RunTotals {
  amount: string | null;
  incomplete_run_count: number;
  shared_job_count: number;
  run_count: number;
  by_status: Record<string, number>;
  workflow_count: number;
  unfiltered_run_count: number;
}

export interface WorkflowOption { key: string; name: string; run_count: number }

/** What each sidebar control could select if its own choice were cleared. */
export interface RunFilterOptions {
  by_status: Record<string, number>;
  workflows: WorkflowOption[];
}

export interface InvocationList {
  items: Invocation[]; total: number; limit: number; offset: number;
  totals: RunTotals; filter_options: RunFilterOptions; meta: Meta;
}

export interface BreakdownRun {
  id: string; amount: string | null; run_total: string | null; chart_amount: string | null;
  shared_job_count: number; run_total_complete: boolean; status: string;
  started_at: string; duration_seconds: number | null;
}

export interface Remainder {
  count: number; amount: string; failed: number; running: number;
  boundary?: { amount: string; run_id: string } | null;
}

export interface BreakdownGroup {
  key: string; name: string; run_count: number; by_status: Record<string, number>;
  amount: string | null;
  incomplete_run_count: number; runs: BreakdownRun[]; remainder: Remainder;
  whole_run_range: {
    minimum: string | null; maximum: string | null;
    included_run_count: number; excluded_run_count: number;
  };
}

export interface Breakdown { groups: BreakdownGroup[]; meta: Meta }

export interface TimelinePiece { id: string; amount: string; status: string }

export interface TimelineBucket {
  from: string; to: string; amount: string | null; run_count: number;
  by_status: Record<string, number>; incomplete_run_count: number; provisional: boolean;
  pieces: TimelinePiece[]; remainder: Remainder;
}

export type BucketUnit = "hour" | "day" | "week";

/** What a tooltip says about a run a timeline piece draws. */
export interface TimelineRun {
  workflow_name: string; started_at: string; duration_seconds: number | null;
  amount: string | null; run_total: string | null; shared_job_count: number;
}

export interface Timeline {
  bucket: BucketUnit; buckets: TimelineBucket[]; axis: { from: string; to: string } | null;
  runs: Record<string, TimelineRun>; label: string; unplaced: { job_count: number; amount: string | null } | null; meta: Meta;
}

/** One block of an Overview column: all workflow runs together, or the individual jobs. */
export interface CostPiece {
  key: "runs" | "individual";
  kind: "runs" | "individual";
  name: string;
  amount: string;
  job_count: number;
  run_count: number;
  failed: number;
  running: number;
}

export interface CostBucket {
  from: string; to: string; amount: string | null; job_count: number; run_count: number;
  failed_job_count: number; running_job_count: number; incomplete_job_count: number;
  provisional: boolean; pieces: CostPiece[];
}

/** The period's workload: what ran, in the words the Overview counts it. */
export interface WorkloadTotals {
  amount: string | null; job_count: number;
  by_outcome: Record<string, number>;
  run_count: number; workflow_count: number; individual_job_count: number;
}

export interface CostTimeline {
  bucket: BucketUnit; buckets: CostBucket[]; axis: { from: string; to: string } | null;
  totals: WorkloadTotals; label: string;
  unplaced: { job_count: number; amount: string | null } | null; meta: Meta;
}

/** Everything the Workflow runs page draws, from one calculation revision. */
export interface RunsView {
  list: InvocationList;
  /** Every workflow the other filters leave, so choosing one never hides the rest. */
  breakdown: Breakdown | null;
  timeline: Timeline | null;
  /** The chosen workflow alone, under every filter, for the strip below the chart. */
  strip: Breakdown | null;
}

/** A recorded job status as the Jobs page stacks it. */
export type JobStatus = "completed" | "running" | "failed" | "other";

/** Known cost and job counts of one status; the pieces of a whole add up to it exactly. */
export interface StatusPiece {
  status: JobStatus; amount: string | null; job_count: number; incomplete_job_count: number;
}

/** The whole matching set of jobs, never a page or a batch of tools. */
export interface JobTotals {
  amount: string | null; job_count: number; tool_count: number;
  incomplete_job_count: number; known_zero_job_count: number; by_status: StatusPiece[];
}

export type ToolCategory = "ranked" | "server" | "zero" | "unavailable";

/** Every version of one tool, under the page's filters. */
export interface ToolFamily {
  key: string; name: string; tool_ids: string[];
  versions: Array<{ version: string | null; job_count: number }>;
  job_count: number; amount: string | null;
  incomplete_job_count: number; known_zero_job_count: number;
  category: ToolCategory; by_status: StatusPiece[];
}

/** Tools outside the ranking. The counts ignore the tool search; the list follows it. */
export interface ToolSection { tool_count: number; job_count: number; groups: ToolFamily[] }

export interface JobBreakdown {
  /** Ranked tools, as many as were asked for, matching the tool search. */
  groups: ToolFamily[];
  /** Ranked tools matching the tool search. */
  total: number;
  ranked_tool_count: number;
  remainder: { tool_count: number; job_count: number; amount: string | null; incomplete_job_count: number };
  /** The largest tool's amount, so every bar keeps one scale. */
  scale: string | null;
  server: ToolSection; zero: ToolSection; unavailable: ToolSection;
  totals: JobTotals; meta: Meta;
}

export interface JobBucket {
  from: string; to: string; amount: string | null; job_count: number;
  incomplete_job_count: number; provisional: boolean; by_status: StatusPiece[];
}

export interface JobTimeline {
  bucket: BucketUnit; buckets: JobBucket[]; axis: { from: string; to: string } | null;
  totals: JobTotals; label: string;
  unplaced: { job_count: number; amount: string | null } | null; meta: Meta;
}

/** A job in a drawer list: the drawer's own share of its cost, beside its whole duration. */
export interface ScopedJob {
  id: string; tool_name: string; tool_id: string; tool_version: string | null; state: string;
  amount: string | null; quality: string; capacities: string[]; created_at: string;
  duration_seconds: number | null; duration_running: boolean;
}

export interface ToolDetail {
  key: string; name: string; tool_ids: string[];
  versions: Array<{ version: string | null; job_count: number }>;
  amount: string | null; job_count: number; incomplete_job_count: number; known_zero_job_count: number;
  category: ToolCategory | null; by_status: StatusPiece[];
  contributors: {
    kind: ToolCategory; jobs: ScopedJob[];
    eligible_job_count: number; excluded_job_count: number; limit: number;
  };
  statistics: {
    sample_count: number; excluded_count: number;
    mean: string | null; median: string | null; p95: string | null;
  };
  meta: Meta;
}

export interface WindowDetail {
  from: string; to: string; amount: string | null; job_count: number; incomplete_job_count: number;
  provisional: boolean; by_status: StatusPiece[];
  items: ScopedJob[]; total: number; limit: number; offset: number; meta: Meta;
}

/** A workflow run behind an Overview figure. `amount` is only what Overview counts under it there. */
export interface OverviewRunItem {
  id: string; workflow_name: string; run_status: string | null; started_at: string;
  amount: string | null; job_count: number; incomplete_job_count: number; shared_job_count: number;
  run_total: string | null; run_total_complete: boolean;
}

export interface OverviewToolItem {
  key: string; name: string; tool_ids: string[];
  versions: Array<{ version: string | null; job_count: number }>;
  amount: string | null; job_count: number;
}

/** How a period ranking chose its top contributors from every candidate. */
export interface OverviewRanking {
  eligible_count: number; excluded_count: number; zero_count: number; limit: number;
}

interface OverviewDetailBase {
  scope: "period" | "interval";
  from: string | null; to: string | null;
  amount: string | null; job_count: number; incomplete_job_count: number;
  provisional: boolean; shared_job_count: number;
  run_count: number | null; tool_count: number | null; ranking: OverviewRanking | null;
  total: number; limit: number; offset: number; meta: Meta;
}

/** `/overview/details`: totals describe the whole scoped set, whatever page of items is returned. */
export type OverviewDetail =
  | (OverviewDetailBase & { kind: "runs"; items: OverviewRunItem[] })
  | (OverviewDetailBase & { kind: "individual"; items: ScopedJob[] })
  | (OverviewDetailBase & { kind: "tools"; items: OverviewToolItem[] });

/** The Jobs page's charts, from the revision the rest of the page shows; one may not be loaded yet. */
export interface JobCharts { breakdown: JobBreakdown | null; timeline: JobTimeline | null }

/** How much of the tool ranking is shown and which tools it is narrowed to. Never a report filter. */
export interface ToolRanking { limit: number; search: string }

export const TOOL_BATCH = 12;
export const DEFAULT_RANKING: ToolRanking = { limit: TOOL_BATCH, search: "" };
export const WINDOW_PAGE_SIZE = 20;
export const JOB_PAGE_SIZE = 50;

export interface GroupItem {
  tool_id?: string; tool_name?: string; tool_version?: string; owner_id?: string; label?: string;
  job_count: number; amount: string | null; priced_count: number; incomplete_count: number;
  statistics?: { sample_count: number; excluded_count: number; mean: string | null; median: string | null; p95: string | null };
}

export interface DailyItem {
  date: string; amount: string | null; currency: string; job_count: number; provisional: boolean;
  incomplete_count: number;
  by_runner: Record<string, string>; by_owner: Record<string, string>; by_tool: Record<string, string>;
}

export interface Freshness {
  overall_status: string;
  sources: Array<{ source: string; status: string; last_success_at: string | null; error: string | null }>;
  observation_gaps: Array<{ source: string; kind: string; detected_at: string; recoverable: boolean; detail: string }>;
  /** The revision a report requested now would show; null while a recalculation is pending. */
  revision_id: string | null;
}

export interface Me {
  source_id: string; label: string; is_admin: boolean;
  auth_mode: string; attribution: string;
  capabilities: { infrastructure: boolean; users: boolean };
}

export interface StatusCheck {
  name: string; status: string; detail: string; facts: Record<string, unknown>;
}

export interface Status {
  generated_at: string; overall_status: string; auth_mode: string; tenant: string;
  checks: StatusCheck[]; failed_capabilities: string[];
  recorded_reports?: Array<{
    context: string; generated_at: string; age_seconds: number; stale: boolean;
    overall_status: string;
  }>;
}

function meta(name: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content || "";
}

// Deployed modes resolve identity on the server; only the development fixture
// adapter accepts these headers, so production requests never carry them.
const identityHeaders: Record<string, string> = meta("rainstone-auth-mode") === "development"
  ? { "X-Rainstone-Tenant": "anvil-demo", "X-Rainstone-User": "admin", "X-Rainstone-Admin": "true" }
  : {};

export function authMode(): string {
  return meta("rainstone-auth-mode") || "development";
}

function apiPath(path: string): string {
  const base = meta("rainstone-base") || "/";
  return `${base.replace(/\/$/, "")}/api${path}`;
}

/** Filters a scientist never has to touch to get an answer. */
export const ADVANCED_FILTERS = [
  "state", "runner", "destination", "capacity", "quality", "toolKey", "toolId", "toolVersion",
  "workflowId", "invocationId", "minCost", "maxCost", "owner",
] as const;

export type AdvancedFilter = (typeof ADVANCED_FILTERS)[number];

export const FILTER_LABELS: Record<AdvancedFilter, string> = {
  state: "Status",
  runner: "Where it ran",
  destination: "Destination",
  capacity: "Capacity",
  quality: "Cost coverage",
  toolKey: "Tool",
  toolId: "Tool ID",
  toolVersion: "Tool version",
  workflowId: "Workflow ID",
  invocationId: "Run ID",
  minCost: "Minimum cost",
  maxCost: "Maximum cost",
  owner: "Galaxy account",
};

export function activeFilters(state: ReportState): Array<{ key: AdvancedFilter; value: string }> {
  return ADVANCED_FILTERS
    .map(key => ({ key, value: String(state[key] ?? "") }))
    .filter(entry => entry.value !== "");
}

export function periodOf(state: ReportState, now = new Date()): Period {
  return resolvePeriod(state.period, state.timezone, {
    fromDate: state.fromTime, toDate: state.toTime,
  }, now);
}

export function queryString(state: ReportState, now = new Date()): string {
  const query = new URLSearchParams({ mode: state.mode, timezone: state.timezone });
  const period = periodOf(state, now);
  query.set("from", offsetBoundary(period.fromDate, state.timezone));
  // Users choose an inclusive last day; the API boundary is exclusive.
  query.set("to", offsetBoundary(exclusiveEnd(period), state.timezone));
  const filters = {
    search: state.search, owner: state.owner, tool_id: state.toolId,
    tool_version: state.toolVersion, tool_key: state.toolKey, invocation_id: state.invocationId,
    workflow_id: state.workflowId, state: state.state, runner: state.runner,
    destination: state.destination, capacity: state.capacity, quality: state.quality,
    min_cost: state.minCost, max_cost: state.maxCost,
  };
  for (const [key, value] of Object.entries(filters)) {
    if (value) query.set(key, value);
  }
  query.set("sort", state.sort);
  query.set("direction", state.direction);
  query.set("offset", String(state.offset));
  if (state.revision) query.set("revision", state.revision);
  return query.toString();
}

/**
 * The shared fields plus the run-only ones, for the run endpoints alone. Job
 * sorting and paging are dropped: runs sort by `run_sort` and page by an
 * explicit offset.
 */
export function runQueryString(
  state: ReportState, page: { limit?: number; offset?: number } = {}, now = new Date(),
): string {
  const query = new URLSearchParams(queryString(state, now));
  query.delete("sort");
  query.set("direction", state.runDirection);
  query.set("offset", String(page.offset ?? 0));
  if (page.limit) query.set("limit", String(page.limit));
  query.set("run_sort", state.runSort);
  const runFilters = {
    workflow_key: state.workflowKey, run_status: state.runStatus,
    focus_from: state.focusFrom, focus_to: state.focusTo,
    max_run_amount: state.maxRunAmount, boundary_run_id: state.boundaryRunId,
  };
  for (const [key, value] of Object.entries(runFilters)) {
    if (value) query.set(key, value);
  }
  return query.toString();
}

/** The page filters that narrow the runs, in the order the sidebar lists them. */
export const RUN_FILTER_FIELDS = [
  "workflowKey", "runStatus", "focusFrom", "focusTo", "maxRunAmount", "boundaryRunId",
] as const;

export const NO_RUN_FILTERS: Pick<ReportState, (typeof RUN_FILTER_FIELDS)[number]> = {
  workflowKey: "", runStatus: "", focusFrom: "", focusTo: "", maxRunAmount: "", boundaryRunId: "",
};

/** The page's own controls, back to what a first visit shows. */
export const DEFAULT_RUN_CONTROLS = {
  runSort: "started_at", runDirection: "desc", runChart: "workflow",
} as const;

const VIEWS: View[] = ["overview", "runs", "tool-runs", "daily", "users", "server", "status"];
const RUN_STATUSES: RunStatus[] = ["completed", "failed", "running", "cancelled"];
const RUN_SORTS: RunSort[] = ["started_at", "amount", "run_total", "duration"];

/** The report a URL describes. Anything missing or unrecognised falls back to its default. */
export function stateFromUrl(search: string): ReportState {
  const params = new URLSearchParams(search);
  // The Tools page became the Jobs page's By tool chart; its links still lead there.
  const legacyTools = params.get("view") === "tools";
  const view = (legacyTools ? "tool-runs" : params.get("view")) as View;
  const outcome = params.get("outcome") as RunStatus;
  const runSort = params.get("run_sort") as RunSort;
  const period = params.get("period") as PeriodId;
  const timezone = params.get("timezone") || "";
  return {
    view: VIEWS.includes(view) ? view : "overview",
    period: PERIOD_ORDER.includes(period) ? period : "this-month",
    mode: "accrued",
    fromTime: params.get("from") || "",
    toTime: params.get("to") || "",
    timezone: isTimezone(timezone) ? timezone : "UTC",
    search: params.get("search") || "", owner: params.get("owner") || "",
    toolId: params.get("tool_id") || "", toolVersion: params.get("tool_version") || "",
    toolKey: params.get("tool_key") || "",
    invocationId: params.get("invocation_id") || "", workflowId: params.get("workflow_id") || "",
    state: params.get("state") || "", runner: params.get("runner") || "",
    destination: params.get("destination") || "", capacity: params.get("capacity") || "",
    quality: params.get("quality") || "", minCost: params.get("min_cost") || "",
    // The Jobs page lists the costliest jobs first unless a link asks for another order.
    maxCost: params.get("max_cost") || "", sort: params.get("sort") || "amount",
    direction: params.get("direction") === "asc" ? "asc" : "desc",
    offset: Number(params.get("offset")) || 0,
    workflowKey: params.get("workflow") || "",
    runStatus: RUN_STATUSES.includes(outcome) ? outcome : "",
    focusFrom: params.get("focus_from") || "",
    focusTo: params.get("focus_to") || "",
    maxRunAmount: params.get("max_amount") || "",
    boundaryRunId: params.get("boundary_run_id") || "",
    runSort: RUN_SORTS.includes(runSort) ? runSort : DEFAULT_RUN_CONTROLS.runSort,
    runDirection: params.get("run_dir") === "asc" ? "asc" : "desc",
    runChart: view === "runs" && params.get("chart") === "time" ? "time" : DEFAULT_RUN_CONTROLS.runChart,
    jobsChart: !legacyTools && view === "tool-runs" && params.get("chart") === "time" ? "time" : "tool",
  };
}

/**
 * The URL query that reproduces a view. Defaults are left out, and the run-only
 * parameters appear only on the Workflow runs page, so other links stay clean.
 */
export function urlQuery(state: ReportState): URLSearchParams {
  const query = new URLSearchParams(queryString(state));
  query.set("view", state.view);
  query.set("period", state.period);
  // Period presets resolve their own dates; only custom dates travel in the URL.
  query.delete("from");
  query.delete("to");
  if (state.period === "custom") {
    query.set("from", state.fromTime);
    query.set("to", state.toTime);
  }
  if (state.view === "runs") {
    const entries: Array<[string, string, string]> = [
      ["workflow", state.workflowKey, ""], ["outcome", state.runStatus, ""],
      ["focus_from", state.focusFrom, ""], ["focus_to", state.focusTo, ""],
      ["max_amount", state.maxRunAmount, ""], ["boundary_run_id", state.boundaryRunId, ""],
      ["run_sort", state.runSort, DEFAULT_RUN_CONTROLS.runSort],
      ["run_dir", state.runDirection, DEFAULT_RUN_CONTROLS.runDirection],
      ["chart", state.runChart, DEFAULT_RUN_CONTROLS.runChart],
    ];
    for (const [key, value, fallback] of entries) {
      if (value && value !== fallback) query.set(key, value);
    }
  }
  if (state.view === "tool-runs" && state.jobsChart !== "tool") query.set("chart", state.jobsChart);
  return query;
}

/**
 * A time chart's request. A week or month still in progress is drawn whole, so
 * it is asked for in days even on its first day, when the elapsed part alone
 * would be a single day and come back in hours.
 */
export function withChartBucket(query: string, state: ReportState): string {
  if (state.period !== "this-week" && state.period !== "this-month") return query;
  const params = new URLSearchParams(query);
  params.set("bucket", "day");
  return params.toString();
}

/** The UTC instant of a local calendar date or date-time in the report's timezone. */
export function offsetBoundary(value: string, timezone: string): string {
  if (/Z$|[+-]\d\d:\d\d$/.test(value)) return value;
  const local = value.length === 10 ? `${value}T00:00:00` : value;
  const [date, clock] = local.split("T");
  const [year, month, day] = date.split("-").map(Number);
  const [hour = 0, minute = 0, second = 0] = (clock || "").split(":").map(Number);
  const desired = Date.UTC(year, month - 1, day, hour, minute, second);
  let instant = desired;
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  });
  for (let pass = 0; pass < 2; pass += 1) {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(instant)).map(part => [part.type, part.value]));
    const rendered = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
    instant += desired - rendered;
  }
  return new Date(instant).toISOString();
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiPath(path), { headers: identityHeaders, signal });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(body.detail || `${response.status} ${response.statusText}`, response.status);
  }
  return response.json() as Promise<T>;
}

export async function loadReport(
  state: ReportState, signal?: AbortSignal, ranking: ToolRanking = DEFAULT_RANKING,
) {
  try {
    return await loadPinnedReport(state, signal, ranking);
  } catch (reason) {
    // The snapshot this load pinned was superseded while the load was still
    // running, which an unattended collector does routinely. Every part of one
    // view must come from one revision, so the load is repeated against the
    // new one rather than shown as an error or mixed with the old one.
    if (reason instanceof ApiError && reason.status === 409) {
      return await loadPinnedReport(state, signal, ranking);
    }
    throw reason;
  }
}

/** Runs listed per page, and how many more each "Show more" appends. */
export const RUN_PAGE_SIZE = 20;

/** The charts a runs view needs: the active tab's, and the strip's when a workflow is chosen. */
export function chartsNeeded(state: ReportState): { breakdown: boolean; timeline: boolean; strip: boolean } {
  return {
    breakdown: state.runChart === "workflow",
    timeline: state.runChart === "time",
    strip: Boolean(state.workflowKey),
  };
}

async function loadRunCharts(
  state: ReportState,
  wanted: { breakdown?: boolean; timeline?: boolean; strip?: boolean },
  signal?: AbortSignal,
) {
  const query = runQueryString(state);
  // The By workflow chart keeps every workflow visible while one is chosen, so
  // it is asked without that choice (and the grouped runs that belong to it).
  const allWorkflows = runQueryString({ ...state, workflowKey: "", maxRunAmount: "", boundaryRunId: "" });
  const [breakdown, timeline, strip] = await Promise.all([
    wanted.breakdown ? get<Breakdown>(`/invocations/breakdown?${allWorkflows}`, signal) : null,
    wanted.timeline ? get<Timeline>(`/invocations/timeline?${withChartBucket(query, state)}`, signal) : null,
    wanted.strip ? get<Breakdown>(`/invocations/breakdown?${query}`, signal) : null,
  ]);
  return { breakdown, timeline, strip };
}

/** The runs a pinned report has not yet shown, one page at a time. */
export function loadMoreRuns(state: ReportState, offset: number, signal?: AbortSignal) {
  return get<InvocationList>(
    `/invocations?${runQueryString(state, { limit: RUN_PAGE_SIZE, offset })}`, signal,
  );
}

/** A chart the page has not loaded yet, from the revision the rest of the page shows. */
export function loadRunChart(state: ReportState, kind: "breakdown" | "timeline", signal?: AbortSignal) {
  return loadRunCharts(state, { [kind]: true }, signal);
}

/** The tool ranking a Jobs page shows. Its size and search are presentation, never report filters. */
export function loadToolRanking(state: ReportState, ranking: ToolRanking, signal?: AbortSignal) {
  const query = new URLSearchParams(queryString(state));
  query.set("group_limit", String(ranking.limit));
  if (ranking.search.trim()) query.set("tool_search", ranking.search.trim());
  return get<JobBreakdown>(`/jobs/breakdown?${query}`, signal);
}

/** The Jobs page's chart that is shown; the other loads when its tab is chosen. */
export async function loadJobCharts(
  state: ReportState, kind: JobsChart, ranking: ToolRanking, signal?: AbortSignal,
): Promise<JobCharts> {
  if (kind === "tool") return { breakdown: await loadToolRanking(state, ranking, signal), timeline: null };
  return { breakdown: null, timeline: await get<JobTimeline>(`/jobs/timeline?${withChartBucket(queryString(state), state)}`, signal) };
}

/** One page of the job list, from a pinned report. */
export function loadJobPage(state: ReportState, signal?: AbortSignal) {
  return get<JobList>(`/jobs?${queryString(state)}`, signal);
}

/** One view, assembled from a single calculation revision. */
async function loadPinnedReport(state: ReportState, signal?: AbortSignal, ranking = DEFAULT_RANKING) {
  const initialQuery = queryString(state);
  const summary = await get<Summary>(`/summary?${initialQuery}`, signal);
  const snapshotState = { ...state, revision: summary.revision_id || state.revision };
  const query = queryString(snapshotState);
  // Only the Jobs page shows a job list; every other page reads what it shows from its own endpoints.
  const jobs = state.view === "tool-runs"
    ? get<JobList>(`/jobs?${query}`, signal)
    : Promise.resolve<JobList>({ items: [], undated_items: [], total: 0, limit: 50, offset: 0, meta: summary });
  const common = [jobs, get<Freshness>("/freshness", signal), get<Me>("/me", signal)] as const;
  // Overview's rankings load when they are asked for, in the drawer.
  const viewRequest = state.view === "overview"
    ? get<CostTimeline>(`/timeline?${withChartBucket(query, state)}`, signal)
    : state.view === "tool-runs" ? loadJobCharts(snapshotState, state.jobsChart, ranking, signal)
    : state.view === "runs" ? loadRunsView(snapshotState, signal)
    : state.view === "daily" ? get<{ items: DailyItem[]; meta: Meta }>(`/daily?${query}`, signal)
    : state.view === "users" ? get<{ items: GroupItem[]; meta: Meta }>(`/users?${query}`, signal)
    : state.view === "server" ? get<Infrastructure>(`/infrastructure?${query}`, signal)
    : state.view === "status" ? get<Status>("/status", signal)
    : Promise.resolve(null);
  const [loadedJobs, freshness, me, view] = await Promise.all([...common, viewRequest]);
  return { summary, jobs: loadedJobs, freshness, me, view };
}

async function loadRunsView(state: ReportState, signal?: AbortSignal): Promise<RunsView> {
  const [list, charts] = await Promise.all([
    get<InvocationList>(`/invocations?${runQueryString(state, { limit: RUN_PAGE_SIZE })}`, signal),
    loadRunCharts(state, chartsNeeded(state), signal),
  ]);
  return { list, ...charts };
}

/** Report sources, as opposed to the price catalog, which is versioned separately. */
const COLLECTION_SOURCES = new Set(["galaxy_db", "kubernetes", "gcp_batch"]);

/**
 * The instant every report source had been collected through: the oldest of
 * their last successes. A missing success leaves the cutoff unknown. The
 * server already marks a source stale once its last success is too old.
 */
export function collectionCutoff(freshness: Freshness | null) {
  const sources = (freshness?.sources || []).filter(source => COLLECTION_SOURCES.has(source.source));
  if (!sources.length || sources.some(source => !source.last_success_at)) {
    return { cutoff: null, stale: true };
  }
  const cutoff = sources
    .map(source => source.last_success_at as string)
    .reduce((oldest, value) => (new Date(value) < new Date(oldest) ? value : oldest));
  return { cutoff, stale: sources.some(source => source.status !== "healthy") };
}

/**
 * Whether a newer summary of the same view would show the reader different
 * figures. A revision covers the whole tenant, so it changes for work the
 * reader cannot see; only a change in what this view counts is worth offering.
 */
export function figuresDiffer(shown: Summary, latest: Summary): boolean {
  const figures = (summary: Summary) => [
    summary.amount, summary.job_count, summary.priced_job_count, summary.unpriced_job_count,
    summary.known_zero_job_count, summary.failed_spend, summary.failed_job_count,
    summary.baseline_infrastructure_amount, summary.current_launch?.total_since_launch ?? null,
  ];
  const before = figures(shown);
  return figures(latest).some((value, index) => value !== before[index]);
}

export function diagnosticsUrl(): string {
  return apiPath("/status/download");
}

export async function downloadExport(state: ReportState): Promise<void> {
  const response = await fetch(apiPath(`/export/jobs.csv?${queryString({ ...state, offset: 0 })}`), {
    headers: identityHeaders,
  });
  if (!response.ok) throw new Error(`Export failed: ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = "rainstone-jobs.csv"; link.click();
  URL.revokeObjectURL(url);
}
