import { durationText, formatCost, formatDateTime, runStatusLabel, smallerRuns } from "../../vocabulary";
import type { TooltipContent } from "./useChartTooltip";

/** What a tooltip needs to say about one run. */
export interface TipRun {
  workflow_name: string;
  started_at: string;
  duration_seconds: number | null;
  status: string;
  amount: string | null;
  run_total: string | null;
  run_total_complete?: boolean;
  chart_amount?: string | null;
  shared_job_count?: number;
}

/**
 * A run's block, value first. The block draws the run's contribution to the
 * chart; when a job is shared with another run that differs from the run's own
 * cost in the period and from its whole-run total, so the three are named.
 */
export function runTooltip(run: TipRun, timezone: string, drawn: string | null): TooltipContent {
  const lines = [
    run.workflow_name,
    `Started ${formatDateTime(run.started_at, timezone)} · ${durationText(run.duration_seconds, run.status)}`,
    runStatusLabel(run.status),
  ];
  if ((run.shared_job_count ?? 0) > 0) {
    lines.push(
      `Counted in this chart: ${formatCost(drawn)}. Cost in this period: ${formatCost(run.amount)}. `
      + `Whole-run total: ${formatCost(run.run_total)}.`,
      "Jobs shared by runs are counted once.",
    );
  } else if (run.run_total !== null && run.amount !== run.run_total) {
    lines[2] += ` · Run total ${formatCost(run.run_total)}`;
  }
  return { value: formatCost(drawn), lines };
}

/** A grouped segment, naming the failed and still-running runs folded into it. */
export function groupedTooltip(
  count: number, drawn: number, failed: number, running: number, hint: string,
): TooltipContent {
  const named = [failed && `${failed} failed`, running && `${running} still running`]
    .filter(Boolean).join(", ");
  return {
    value: formatCost(String(drawn)),
    lines: [`${smallerRuns(count)}${named ? ` (${named})` : ""}`, hint],
  };
}
