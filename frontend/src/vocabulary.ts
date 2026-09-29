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
};

export function jobStateLabel(state: string): string {
  return JOB_STATE[state] || state;
}

const CAPACITY: Record<string, string> = {
  existing: "Your Galaxy server",
  dedicated: "Dedicated cloud compute",
  elastic_shared: "Shared cloud capacity",
  unknown: "Not established",
};

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
  return record.reason || "Estimated from observed execution using public prices.";
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
