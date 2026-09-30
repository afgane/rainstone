/**
 * Presentation vocabulary.
 *
 * The API keeps stable machine-readable values; everything a scientist reads is
 * translated here. Accounting distinctions are preserved: zero, a small
 * positive amount, an unknown cost and an incomplete subtotal stay different
 * things, they are simply said in ordinary language.
 */

export const PRIMARY_MEASURE = "Estimated run compute cost";
export const PRIMARY_EXPLANATION =
  "Compute started for your jobs and workflow runs. Your already-running Galaxy server is shown separately.";
export const SERVER_EXPLANATION =
  "Your Galaxy server keeps running between jobs. This is the whole server's compute since it was last launched, including idle time, not a share of any run.";
export const EXISTING_SERVER_SENTENCE =
  "This job used your already-running Galaxy server, so it added no compute charge. The server continues to incur costs.";

/**
 * Dates in the report's timezone, never the browser's, so a run and the day
 * it is counted under always agree.
 */
export function formatDate(instant: string, timezone: string): string {
  return new Date(instant).toLocaleDateString(undefined, { dateStyle: "medium", timeZone: timezone });
}

export function formatDateTime(instant: string, timezone: string): string {
  return new Date(instant).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  });
}

/** Readable money. Details keep the exact decimal string. */
export function formatCost(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "Not available";
  const value = Number(amount);
  if (!Number.isFinite(value)) return "Not available";
  if (value === 0) return "$0.00";
  if (value > 0 && value < 0.01) return "less than $0.01";
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

/** An hourly rate keeps sub-cent precision; the exact string stays in details. */
export function formatRate(rate: string | null | undefined): string {
  if (rate === null || rate === undefined || rate === "") return "Not available";
  const value = Number(rate);
  if (!Number.isFinite(value)) return "Not available";
  return `${value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  })}/hour while running`;
}

const RUN_STATUS: Record<string, string> = {
  completed: "Completed",
  failed: "Failed",
  running: "Running",
  cancelled: "Cancelled",
  "no runs recorded": "No runs recorded",
};

export function runStatusLabel(status: string): string {
  return RUN_STATUS[status] || status;
}

const JOB_STATE: Record<string, string> = {
  ok: "Completed",
  error: "Failed",
  failed: "Failed",
  running: "Running",
  queued: "Queued",
  new: "Not started",
  paused: "Paused",
  deleted: "Deleted",
  resubmitted: "Restarted",
  cancelled: "Cancelled",
};

export function jobStateLabel(state: string): string {
  return JOB_STATE[state] || state;
}

const CAPACITY: Record<string, string> = {
  existing: "Your Galaxy server",
  dedicated: "Dedicated cloud compute",
  elastic_shared: "Shared cloud capacity",
  unknown: "Not established",
  multiple: "Multiple environments",
};

/** Where one job, or one part of a run's cost, ran; retries across several places say so. */
export function environmentLabel(environment: string): string {
  return CAPACITY[environment] || environment;
}

/** Where the work ran, stated only when the resource relationship is verified. */
export function capacityLabel(capacities: string[] | undefined): string {
  if (!capacities || !capacities.length) return "Not established";
  const named = capacities.map(value => CAPACITY[value] || value);
  return [...new Set(named)].join(" and ");
}

const QUALITY: Record<string, string> = {
  known_zero: "$0 extra compute · Used your Galaxy server",
  complete: "Estimated",
  approximate: "Estimated",
  partial: "Cost incomplete",
  unpriced: "Price unavailable",
  in_progress: "Still running",
  unavailable: "Cost data unavailable",
  not_started: "Not run yet",
};

export function qualityLabel(quality: string): string {
  return QUALITY[quality] || quality;
}

/** One sentence explaining an amount, in the user's terms. */
export function costExplanation(record: {
  quality: string;
  amount: string | null;
  reason?: string;
  capacities?: string[];
}): string {
  if (record.quality === "known_zero") return EXISTING_SERVER_SENTENCE;
  if (record.quality === "unpriced") {
    return "No published price covers this machine and region for when it ran, so its cost is unavailable rather than zero.";
  }
  if (record.quality === "partial") {
    return "Some evidence for this job is still missing, so the amount shown is a subtotal.";
  }
  if (record.quality === "in_progress") return "This work is still running, so its cost is provisional.";
  if (record.quality === "unavailable") {
    return "This job finished, but the evidence needed to cost it was not collected, so its cost is unavailable rather than zero.";
  }
  if (record.quality === "not_started") return "This work has not run, so there is no cost to show.";
  return record.reason || "Estimated from the observed run using public prices.";
}

/** Evidence a dated report leaves out because no period can hold it. */
export function undatedSentence(count: number): string {
  return `${pluralize(count, "job")} ${count === 1 ? "has" : "have"} no usable timing, so ${count === 1 ? "it is" : "they are"} left out of every period's totals.`;
}

export function coverageSentence(jobs: number, incomplete: number): string {
  if (!jobs) return "No jobs in this period.";
  if (!incomplete) return `${jobs} ${jobs === 1 ? "job" : "jobs"} included.`;
  return `${incomplete} ${incomplete === 1 ? "job" : "jobs"} still need cost data.`;
}

/** Grammar that stays correct at one. */
export function needsCostData(count: number, noun = "step"): string {
  return `${pluralize(count, noun)} still ${count === 1 ? "needs" : "need"} cost data`;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}

/** A whole-dollar tick as "$5", a cent tick as "$0.25". */
export function formatAxisCost(value: number): string {
  return Number.isInteger(value) ? `$${value}` : `$${value.toFixed(2)}`;
}

/** Wall-clock time: "45 min", "2 h 5 min". A run under a minute reads as one. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "Not available";
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

/** How long a run has been going, or ran for. */
export function durationText(seconds: number | null | undefined, status: string): string {
  return `${formatDuration(seconds)}${status === "running" && seconds !== null && seconds !== undefined ? " so far" : ""}`;
}

/* The Workflow runs page. */
export const PAGE_FILTERS_HEADING = "Filters for this page";
export const PAGE_FILTERS_NOTE = "Workflow runs only. The period above applies everywhere.";
export const WORKFLOW_FIELD = "Workflow";
export const ALL_WORKFLOWS = "All workflows";
export const OUTCOME_FIELD = "Outcome";
export const NO_ACTIVE_FILTERS = "Showing every run in this period.";
export const CLEAR_FILTERS = "Clear filters";
export const COST_SO_FAR = "Cost so far";
export const RUN_TOTAL = "Run total";
export const WORKFLOW_JOBS = "Workflow jobs";
export const SHARED_JOBS_NOTE = "Jobs shared by these runs are counted once";
export const STRIP_TITLE = "Every run, at its own scale";
export const STRIP_HINT = "Choose a workflow in the filters or above to see each of its runs here at full width.";
export const STRAGGLE_NOTE =
  "Runs that began before this period, or are still going after it, show only the part inside it. "
  + "The list shows each run's whole total.";
export const RUN_CHART_HINT =
  "Pointer-only shortcut. The run list below and the table under this chart hold the same "
  + "information for keyboard and screen reader use.";

export const OUTCOMES: Array<{ id: string; label: string }> = [
  { id: "", label: "All" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
  { id: "running", label: "Running" },
  { id: "cancelled", label: "Cancelled" },
];

export const RUN_SORTS: Array<{ id: string; label: string; sort: string; direction: "asc" | "desc" }> = [
  { id: "newest", label: "Newest first", sort: "started_at", direction: "desc" },
  { id: "oldest", label: "Oldest first", sort: "started_at", direction: "asc" },
  { id: "highest", label: "Highest cost", sort: "run_total", direction: "desc" },
  { id: "lowest", label: "Lowest cost", sort: "run_total", direction: "asc" },
  { id: "longest", label: "Longest running", sort: "duration", direction: "desc" },
];

export function acrossWorkflows(count: number): string {
  return `Across ${pluralize(count, "workflow")}`;
}

export function outOfRuns(count: number): string {
  return `Out of ${pluralize(count, "run")} in this period`;
}

export function showingOf(shown: number, total: number): string {
  return `Showing ${shown} of ${total}`;
}

export function showMore(count: number): string {
  return `Show ${count} more`;
}

/** "3 completed · 1 failed", in the order a reader expects; empty when there are no runs. */
export function outcomeMix(byStatus: Record<string, number>): string {
  return ["completed", "failed", "running", "cancelled"]
    .filter(status => byStatus[status])
    .map(status => `${byStatus[status]} ${status}`)
    .join(" · ");
}

export function smallerRuns(count: number): string {
  return pluralize(count, "smaller run");
}

export function rangeCaption(range: {
  minimum: string | null; maximum: string | null; included_run_count: number; excluded_run_count: number;
}): string {
  const excluded = range.excluded_run_count
    ? ` ${pluralize(range.excluded_run_count, "run")} left out: still running or missing cost data.`
    : "";
  if (!range.included_run_count) return `Whole-run range not available.${excluded}`;
  if (range.included_run_count === 1 || range.minimum === range.maximum) {
    return `One run, ${formatCost(range.minimum)} in total.${excluded}`;
  }
  return `Whole-run totals range from ${formatCost(range.minimum)} to ${formatCost(range.maximum)}.${excluded}`;
}

/** The chip for a focus window: which runs were active then. */
export function focusChipLabel(from: string, to: string, timezone: string, mode = "accrued"): string {
  const lead = mode === "completed" ? "Runs with jobs completed" : "Runs active";
  const start = Date.parse(from);
  const end = Date.parse(to);
  const day = (instant: number) =>
    new Date(instant).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone });
  const hour = (instant: number) =>
    new Date(instant).toLocaleTimeString("en-US", { hour: "numeric", timeZone: timezone });
  if (end - start <= 3600e3 + 1) return `${lead} ${day(start)}, ${hour(start)}–${hour(end)}`;
  const last = day(end - 60e3);
  return `${lead} ${day(start) === last ? day(start) : `${day(start)}–${last}`}`;
}

export function groupedChipLabel(workflowName: string): string {
  return `Smaller runs in ${workflowName}`;
}

/* The Overview's workload card and cost chart. */
export const WORKLOAD_EYEBROW = "Workload";
export const NO_JOBS = "No jobs in this period.";
export const OVERVIEW_CHART_HINT =
  "Pointer-only shortcut. The table under this chart holds the same information for "
  + "keyboard and screen reader use.";

/** A chart's title, named for its columns: hours, days or weeks. */
export function costChartTitle(unit: "hour" | "day" | "week"): string {
  return unit === "hour" ? "Hourly cost" : unit === "week" ? "Weekly cost" : "Daily cost";
}

/** What a block holds: "2 runs · 9 jobs", or just the jobs for work outside a workflow. */
export function pieceCounts(runs: number, jobs: number): string {
  return runs > 0 ? `${pluralize(runs, "run")} · ${pluralize(jobs, "job")}` : pluralize(jobs, "job");
}

/** Failed and still-running jobs, named so they are not carried by colour or texture alone. */
export function jobOutcomes(failed: number, running: number): string {
  return [failed && `${failed} failed`, running && `${running} still running`]
    .filter(Boolean).join(", ");
}

/** Cost that no column can hold, because nothing says when it was incurred. */
export function unplacedSentence(jobs: number, amount: string | null): string {
  const cost = amount === null ? "" : `, ${formatCost(amount)}`;
  return `Cannot be placed in time: ${pluralize(jobs, "job")}${cost}.`;
}


/* The workflow run drawer's cost breakdown and job list. */
export const BREAKDOWN_HEADING = "Cost breakdown by tool";
export const BREAKDOWN_UNAVAILABLE = "Cost breakdown unavailable";
export const JOBS_HEADING = "Jobs";
export const NO_RUN_JOBS = "No jobs are recorded for this run yet.";
export const SERVER_GROUP_NOTE =
  "These jobs used your Galaxy server and added no compute charge. The server's own cost is reported separately.";
export const MULTIPLE_ENVIRONMENTS_NOTE = "Some of these jobs ran in more than one place.";
export const CLEAR_SELECTION = "Clear selection";

export function fingerprintCaption(cellCount: number): string {
  return `Each of the ${cellCount} squares is about 1% of the cost shown.`;
}

/** What a share is a share of, so it never implies a final total that is not known. */
export function shareBasis(running: boolean, complete: boolean): string {
  if (running) return "of cost so far";
  return complete ? "of this run's cost" : "of recorded cost";
}

/** A part's share of the known cost: whole percents above ten, one decimal below, and "less than 1%". */
export function formatShare(share: number): string {
  const percent = share * 100;
  if (percent < 1) return "Less than 1%";
  const rounded = percent < 10 ? Math.round(percent * 10) / 10 : Math.round(percent);
  return `${rounded}%`;
}

export function jobsInPart(count: number): string {
  return pluralize(count, "job");
}

/** Brief text for a group of equal-tool jobs: "wig to bigwig ×3". */
export function repeatedToolName(name: string, count: number): string {
  return count > 1 ? `${name} ×${count}` : name;
}

export function shownOf(shown: number, total: number, noun: string): string {
  return `Showing ${shown} of ${pluralize(total, noun)}`;
}

export function groupHeading(environment: string, count: number): string {
  return `${environmentLabel(environment)} · ${pluralize(count, "job")}`;
}

/** What a group's cost figure leaves out, said under it. */
export function groupCoverage(hasCost: boolean, incomplete: number): string {
  if (!incomplete) return "";
  return hasCost
    ? `Recorded so far · ${needsCostData(incomplete, "job")}`
    : needsCostData(incomplete, "job");
}

export function unavailableSteps(count: number): string {
  return `${pluralize(count, "step")} of this run ${count === 1 ? "has" : "have"} no job you can see.`;
}

export function selectionGone(): string {
  return "The part you had selected is no longer available.";
}

/** The visual class of a job's state, kept apart from the words so an unmapped state is never hidden. */
export type JobStateKind =
  | "completed" | "running" | "failed" | "queued" | "cancelled" | "paused" | "not-started"
  | "deleted" | "restarted" | "unknown";

const JOB_STATE_KIND: Record<string, JobStateKind> = {
  ok: "completed", error: "failed", failed: "failed", running: "running", queued: "queued",
  new: "not-started", paused: "paused", deleted: "deleted", resubmitted: "restarted",
  cancelled: "cancelled",
};

export function jobStateKind(state: string): JobStateKind {
  return JOB_STATE_KIND[state] ?? "unknown";
}

/**
 * How long a job ran, keeping seconds: "14s", "2m 08s", "38m 12s", "1h 05m",
 * "2d 03h". Under a second is "<1s".
 */
export function formatJobDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 1) return "<1s";
  if (whole < 60) return `${whole}s`;
  const pad = (value: number) => String(value).padStart(2, "0");
  if (whole < 3600) return `${Math.floor(whole / 60)}m ${pad(whole % 60)}s`;
  if (whole < 86400) return `${Math.floor(whole / 3600)}h ${pad(Math.floor((whole % 3600) / 60))}m`;
  return `${Math.floor(whole / 86400)}d ${pad(Math.floor((whole % 86400) / 3600))}h`;
}

/** The same duration in words for a screen reader. */
export function jobDurationLabel(seconds: number | null | undefined, running = false): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "Duration not available";
  return `${formatJobDuration(seconds)}${running ? " elapsed so far" : ""}`;
}

/** Money for the constrained job row; the full wording stays in labels and tooltips. */
export function formatCompactCost(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const value = Number(amount);
  if (!Number.isFinite(value)) return "—";
  return value > 0 && value < 0.01 ? "<$0.01" : formatCost(amount);
}

export function jobCostLabel(amount: string | null | undefined): string {
  if (amount === null || amount === undefined || amount === "" || !Number.isFinite(Number(amount))) {
    return "Cost not available";
  }
  return `Cost ${formatCost(amount)}`;
}

/* The job drawer. */
export const TIMELINE_HEADING = "Timeline";
export const COMPUTE_HEADING = "Compute";
export const RESOURCE_USE_HEADING = "Resource use";
export const COST_ESTIMATE_HEADING = "How this cost was estimated";
export const TECHNICAL_HEADING = "Technical details";
export const RAN_FOR = "Ran for";
export const WAITED_TO_START = "Waited to start";
export const SUBMITTED = "Submitted";
export const WAITING_TO_START = "Waiting to start";
export const AVERAGE_CPU = "Average CPU use";
export const PEAK_MEMORY = "Peak memory use";
export const NO_COMPUTE_EVIDENCE = "No evidence of where this ran was collected.";
export const USAGE_NOT_RECORDED = "Usage measurements were not recorded.";
export const SERVER_USE_NOTE = "Your Galaxy server's own usage is not attributed to individual jobs.";
export const MEASUREMENTS_HEADING = "About these measurements";
export const MEASUREMENTS_EXPLANATION =
  "Average CPU use is the CPU time the run used divided by how long the tool ran. Peak memory use is "
  + "the most memory it held at once. Each is set beside what was requested for the job; a request is a "
  + "reference, not a limit, so use can be above it.";
export const ABOVE_REQUEST_NOTE =
  "Use was above the request, so this bar is stretched to fit it. The marker shows the requested amount.";
export const COST_METHOD =
  "Estimated from when the machine that ran this job was in use and the published price for that machine.";
export const COST_EXCLUSIONS = "Costs are compute only, in USD. Storage, network and other charges are not included.";
export const COST_COMPONENTS_NOTE = "These amounts are parts of the job's cost above, not additional costs.";
export const TIMING_ESTIMATE_NOTE =
  "Timing comes from recorded events. The machine can be held before and after the tool runs.";

export const TIMING_NOTE = {
  finished_before_started: "The recorded finish is earlier than the recorded start, so no duration is shown.",
  started_before_submitted: "The recorded start is earlier than the submission, so the wait before it is not shown.",
  not_recorded: "When the tool started and finished was not recorded.",
  no_finish: "The tool's finish was not recorded, so no duration is shown.",
} as const;

export const TIMELINE_LABEL = {
  submitted: "Submitted", started: "Started", finished: "Finished", "first-started": "First started",
  "last-finished": "Last finished", recorded: "Recorded so far",
} as const;

/** What the big number is, without claiming a total that is not known. */
export function jobHeadlineLabel(quality: string, amount: string | null): string {
  if (quality === "known_zero") return qualityLabel(quality);
  if (quality === "in_progress" && amount !== null) return COST_SO_FAR;
  if (quality === "partial" && amount !== null) return "Estimated compute cost, recorded so far";
  return "Estimated compute cost";
}

/** What a finished estimate needs no sentence for; everything else is said beside the figure. */
export function needsCostNote(quality: string): boolean {
  return quality !== "complete" && quality !== "approximate";
}

const PURCHASE_MODEL: Record<string, string> = { on_demand: "On-demand", spot: "Spot", preemptible: "Preemptible" };

/** The purchase model as recorded; one that is not known here is shown as it came. */
export function purchaseModelLabel(model: string): string {
  return PURCHASE_MODEL[model] ?? model;
}

const UNSUPPORTED: Record<string, string> = {
  galaxy_server: "This job ran on your Galaxy server, whose usage is not attributed to single jobs.",
  running: "Shown once the job has finished.",
  no_execution: "No tool run was recorded for this job.",
  several_executions:
    "This job ran more than once, and its measurements are not matched to a single run.",
  several_resources:
    "This job used more than one machine, so its measurements are not compared with a single request.",
  request_scope_unverified:
    "The request may cover more than the tool itself, so no percentage is shown.",
  source_unresolved: "Two memory measurements disagree, so none is shown.",
};

/** Why a measurement has no bar, in words; null when it has one. */
export function comparisonNote(kind: "cpu" | "memory", status: string, reason: string | null): string | null {
  if (status === "available") return null;
  if (status === "not_recorded") return kind === "cpu" ? "CPU use not recorded." : "Memory use not recorded.";
  const sentence = status === "invalid_value" ? "The recorded value is not valid, so it is not shown."
    : status === "duration_unavailable" ? "How long the tool ran is not available, so no average is shown."
    : status === "request_unavailable"
      ? reason === "request_not_positive"
        ? "The recorded request is not a usable size, so no comparison is shown."
        : "No request was recorded, so no comparison is shown."
      : (reason && UNSUPPORTED[reason]) || "This measurement cannot be compared with the request.";
  return `Not available. ${sentence}`;
}

/** The clock time of an instant in the report's timezone. */
export function formatClock(instant: string, timezone: string): string {
  return new Date(instant).toLocaleTimeString(undefined, { timeStyle: "short", timeZone: timezone });
}

/** Seconds and the timezone's name, for where an exact moment matters. */
export function formatExactDateTime(instant: string, timezone: string): string {
  // `dateStyle` cannot be combined with `timeZoneName`, so the fields are spelled out.
  return new Date(instant).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit",
    timeZone: timezone, timeZoneName: "short",
  });
}

/** The calendar day in the report's timezone, to tell when a timeline crosses midnight. */
export function dayKey(instant: string, timezone: string): string {
  return new Date(instant).toLocaleDateString("en-CA", { timeZone: timezone });
}
