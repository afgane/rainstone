/**
 * Presentation vocabulary.
 *
 * The API keeps stable machine-readable values; everything a scientist reads is
 * translated here. Accounting distinctions are preserved: zero, a small
 * positive amount, an unknown cost and an incomplete subtotal stay different
 * things, they are simply said in ordinary language.
 */

export const PRIMARY_MEASURE = "Estimated run compute cost";
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

/** The rate to the cent, for a summary card; the server page keeps the precise one. */
export function formatRateInCents(rate: string | null | undefined): string {
  const value = Number(rate);
  if (rate === null || rate === undefined || rate === "" || !Number.isFinite(value)) return "Not available";
  return `${formatCost(rate)}/hour while running`;
}

const RUN_STATUS: Record<string, string> = {
  completed: "Completed",
  failed: "Failed",
  running: "Running",
  cancelled: "Canceled",
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
  cancelled: "Canceled",
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
  collecting: "Cost still being collected",
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
  if (record.quality === "collecting") {
    return "This job finished recently and the evidence needed to cost it is still arriving; its cost appears once it does.";
  }
  if (record.quality === "not_started") return "This work has not run, so there is no cost to show.";
  return record.reason || "Estimated from the observed run using public prices.";
}

/** Evidence a dated report leaves out because no period can hold it. */
export function undatedSentence(count: number): string {
  return `${pluralize(count, "job")} could not be placed in time, so no period includes ${count === 1 ? "it" : "them"}.`;
}

export const UNDATED_LIST_NOTE =
  "They are listed here so they can still be opened. A job that has not started yet stays here until it runs.";

export const RECORDED_ONLY_NOTE = "Only recorded costs are drawn.";

export function inProgressNote(count: number): string {
  return `${pluralize(count, "job")} still in progress`;
}

/** Worded as settled: nothing the reader does will bring the cost back. */
export function unrecordedNote(count: number): string {
  return `${pluralize(count, "job")} whose cost was not recorded ${count === 1 ? "is" : "are"} not included`;
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
  { id: "cancelled", label: "Canceled" },
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

/* The Overview's cost cards and cost chart. */
export const WORKLOAD_EYEBROW = "Workload";
export const NO_JOBS = "No jobs in this period.";
export const RUN_COMPUTE = "Run compute";
export const SERVER_COMPUTE = "Galaxy server";
// Two parts of one cost, never a sum: the cards cover different spans of time.
export const COST_PARTS_SENTENCE =
  "Your compute cost has two parts: run compute, for the machines started to run your jobs, "
  + "and the Galaxy server, which runs whether or not jobs do.";
export const OVERVIEW_CHART_TITLE = "Run compute over time";
export const OVERVIEW_CHART_SCOPE = "Galaxy server shown separately";
export const OVERVIEW_CHART_HINT = "Select a block to see what ran.";
export const EXPLORE_PERIOD = "Explore this period";
export const WORKFLOW_BLOCK = "Workflow runs";
export const INDIVIDUAL_BLOCK = "Jobs outside workflows";

/** How long the server has been up: "5 h 12 min", or "28 days 4 h" once it has run a day. */
export function sinceLaunch(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "Time since launch unavailable";
  const days = Math.floor(seconds / 86400);
  if (!days) return `${formatDuration(seconds)} since launch`;
  const hours = Math.floor((seconds % 86400) / 3600);
  return `${pluralize(days, "day")}${hours ? ` ${hours} h` : ""} since launch`;
}

/**
 * Short words for how far the server card's figure can be taken at face
 * value. Why, and the exact cutoff, are on the Galaxy server page.
 */
export function serverQualifiers(
  launch: { ended_at: string | null; stale: boolean } | null, imported: boolean,
): string[] {
  if (!launch) return [];
  return [
    ...(launch.ended_at ? ["Stopped"] : []),
    ...(launch.stale ? [imported ? "Snapshot" : "Stale"] : []),
  ];
}

/* What lies behind an Overview figure, in its drawer. */
export const COUNTED_HERE = "Counted here";
export const PERIOD_OVERLAP_NOTE =
  "Workflow runs and tools are two views of the same work, so their amounts overlap.";

export function sharedJobsNote(count: number): string {
  return `${pluralize(count, "job")} ${count === 1 ? "belongs" : "belong"} to more than one run; `
    + `${count === 1 ? "it is" : "each is"} counted once, under one run, as on the chart.`;
}

export function excludedContributors(count: number, noun: "run" | "tool"): string {
  return `${pluralize(count, noun)} with incomplete cost data ${count === 1 ? "is" : "are"} not ranked.`;
}

export function topContributors(count: number, noun: "workflow run" | "tool"): string {
  return count === 1 ? `Top ${noun}` : `Top ${count} ${noun}s`;
}

/** What a block holds: "2 runs · 9 jobs", or just the jobs for work outside a workflow. */
export function pieceCounts(runs: number, jobs: number): string {
  return runs > 0 ? `${pluralize(runs, "run")} · ${pluralize(jobs, "job")}` : pluralize(jobs, "job");
}

/** Failed and still-running jobs, named so they are not carried by color or texture alone. */
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
export const GPU_PRICE_NOTE = "The machine's price includes its GPUs.";
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

/* The Jobs page. */
export const JOBS_SEARCH_HELP = "Search by tool";
export const TOOL_SEARCH_LABEL = "Find a tool";
export const TOOL_SEARCH_HELP = "Finds a tool in this chart. The totals and the job list stay as they are.";
export const JOBS_SCOPE = "Workflow jobs and individual tool jobs";
export const JOBS_CHART_HINT =
  "Pointer-only shortcut. The table under this chart and the job list below hold the same "
  + "information for keyboard and screen reader use.";
export const STATUS_NOTE =
  "Colors show each job's status as recorded for this report, not its status at that time.";
export const SPAN_NOTE =
  "Jobs that ran across this interval show only the part of their cost inside it. "
  + "Each duration is the job's whole run.";
export const RANKING_NOTE = "Among jobs with complete cost data.";
export const SERVER_TOOL_NOTE =
  "These jobs used your Galaxy server and added no compute charge. The server's own cost is reported separately.";

const ORIGIN: Record<string, string> = {
  workflow: "Part of a workflow",
  individual: "Individual tool job",
  unknown: "Workflow link not recorded",
};

/** What the record says about a job's workflow, never more than it can show. */
export function originLabel(origin: string | null | undefined): string {
  return ORIGIN[origin ?? "unknown"] ?? ORIGIN.unknown;
}

/** "and 2 other runs", for a job that more than one workflow run holds. */
export function otherRuns(count: number): string {
  return count > 0 ? `and ${pluralize(count, "other run")}` : "";
}

const STATUS_PIECE: Record<string, string> = {
  completed: "Completed", running: "Running", failed: "Failed", other: "Other status",
};

export function statusPieceLabel(status: string): string {
  return STATUS_PIECE[status] ?? status;
}

/** "157 completed · 4 running · 8 failed", from status pieces; empty when there are none. */
export function statusMix(pieces: Array<{ status: string; job_count: number }>): string {
  return pieces.filter(piece => piece.job_count)
    .map(piece => `${piece.job_count} ${piece.status === "other" ? "other status" : piece.status}`)
    .join(" · ");
}

/** A job's amount in a list: a server job adds nothing, which is not the same as a $0.00 charge. */
export function jobAmountText(amount: string | null, quality: string): string {
  return quality === "known_zero" ? "$0 extra" : formatCost(amount);
}

export function contributorsHeading(count: number): string {
  return count === 1 ? "The job contributing most to the cost" : `${count} jobs contributing most to the cost`;
}

export function excludedFromRanking(count: number): string {
  return `${pluralize(count, "job")} with incomplete cost data ${count === 1 ? "is" : "are"} not ranked.`;
}

export function showJobs(count: number): string {
  return `Show ${pluralize(count, "job")}`;
}

export function moreTools(count: number): string {
  return pluralize(count, "more tool");
}


/** One status's part of a tool or interval, in words: "Failed: $1.20 · 3 jobs". */
export function statusLine(piece: { status: string; amount: string | null; job_count: number }): string {
  return `${statusPieceLabel(piece.status)}: ${formatCost(piece.amount)} · ${pluralize(piece.job_count, "job")}`;
}

/** The Jobs page's list orders. Links can carry any other supported order, which is kept. */
export const JOB_SORTS: Array<{ id: string; label: string; sort: string; direction: "asc" | "desc" }> = [
  { id: "highest", label: "Highest cost", sort: "amount", direction: "desc" },
  { id: "lowest", label: "Lowest cost", sort: "amount", direction: "asc" },
  { id: "newest", label: "Newest first", sort: "created_at", direction: "desc" },
  { id: "oldest", label: "Oldest first", sort: "created_at", direction: "asc" },
  { id: "tool", label: "Tool name", sort: "tool_id", direction: "asc" },
  { id: "status", label: "Status", sort: "state", direction: "asc" },
];
