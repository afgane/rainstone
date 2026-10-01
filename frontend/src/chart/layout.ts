/**
 * Chart geometry, kept free of the DOM so its rules can be tested.
 *
 * Both charts draw one block per run. Blocks below a minimum size are folded
 * into one grouped segment instead of vanishing, and a block never gains width
 * by being zero or unknown: only a positive cost is drawn.
 */

import type { BucketUnit, Remainder } from "../api";

/** Blocks are separated by this many pixels of surface. */
export const BLOCK_GAP = 2;
export const MINIMUM_HORIZONTAL = 6;
export const MINIMUM_VERTICAL = 5;
/** The height of every time chart's plot, in pixels. */
export const PLOT_HEIGHT = 200;

/** A run as the layout sees it: what to draw, and where it sits in the order. */
export interface LayoutRun {
  id: string;
  /** What the chart draws for this run; null or 0 draws nothing. */
  drawn: number | null;
  /** The run's own share of the period, which orders By workflow and names its boundary. */
  amount: string | null;
  status: string;
}

export interface Boundary { amount: string; runId: string }

export type Segment =
  | { kind: "run"; run: LayoutRun; size: number }
  | {
      kind: "more";
      /** The runs folded into the segment, counting the server's remainder. */
      count: number;
      drawn: number;
      failed: number;
      running: number;
      /** The exact run that starts the folded suffix; null when a whole column is selected. */
      boundary: Boundary | null;
      size: number;
    };

const emptyRemainder: Remainder = { count: 0, amount: "0", failed: 0, running: 0, boundary: null };

/**
 * Lay out one bar or column.
 *
 * `runs` arrive in their display order. Blocks that would fall below `minimum`
 * pixels fold together with everything after the first of them (a contiguous
 * suffix of the order, so the fold can be named by its first run) and with the
 * server's remainder. A lone undersized block stays a block at the minimum. A
 * remainder with nothing else folded is a grouped segment of its own, named by
 * its own boundary.
 */
export function layoutSegments(
  runs: LayoutRun[],
  remainder: Remainder | null | undefined,
  length: number,
  minimum: number,
  options: { selectableBoundary: boolean } = { selectableBoundary: true },
): Segment[] {
  const rest = remainder ?? emptyRemainder;
  const restDrawn = Number(rest.amount) || 0;
  const drawnRuns = runs.filter(run => (run.drawn ?? 0) > 0);
  const total = drawnRuns.reduce((sum, run) => sum + (run.drawn as number), 0) + restDrawn;
  if (total <= 0) return [];
  const budget = Math.max(length, minimum);
  const undersized = drawnRuns.findIndex(run => (run.drawn as number) / total * budget < minimum);
  const suffix = undersized === -1 ? [] : drawnRuns.slice(undersized);
  const folding = suffix.length >= 2 || (suffix.length === 1 && rest.count > 0);
  const singles = folding ? drawnRuns.slice(0, undersized) : drawnRuns;
  const grouped = folding || rest.count > 0;
  const count = singles.length + (grouped ? 1 : 0);
  const available = Math.max(minimum, budget - BLOCK_GAP * (count - 1));
  const size = (amount: number) => Math.max(minimum, amount / total * available);
  const segments: Segment[] = singles.map(run => ({
    kind: "run", run, size: size(run.drawn as number),
  }));
  if (grouped) {
    const folded = folding ? suffix : [];
    const drawn = folded.reduce((sum, run) => sum + (run.drawn as number), 0) + restDrawn;
    segments.push({
      kind: "more",
      count: folded.length + rest.count,
      drawn,
      failed: folded.filter(run => run.status === "failed").length + rest.failed,
      running: folded.filter(run => run.status === "running").length + rest.running,
      boundary: !options.selectableBoundary ? null
        : folded.length && folded[0].amount !== null
          ? { amount: folded[0].amount, runId: folded[0].id }
          : rest.boundary ? { amount: rest.boundary.amount, runId: rest.boundary.run_id } : null,
      size: size(drawn),
    });
  }
  return segments;
}

/** A scale with about four ticks, at 1, 2, 2.5, 5 or 10 times a power of ten. */
export function niceScale(max: number): { max: number; step: number } {
  if (!(max > 0)) return { max: 1, step: 0.25 };
  const raw = max / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normal = raw / magnitude;
  const step = (normal <= 1 ? 1 : normal <= 2 ? 2 : normal <= 2.5 ? 2.5 : normal <= 5 ? 5 : 10) * magnitude;
  return { step, max: Math.ceil(max / step - 1e-9) * step };
}

const LABEL_STEPS: Record<BucketUnit, { steps: number[]; width: number }> = {
  hour: { steps: [1, 2, 3, 4, 6], width: 46 },
  day: { steps: [1, 2, 3, 5, 7], width: 46 },
  week: { steps: [1, 2, 3, 4, 6], width: 46 },
};

/** Label every Nth bucket, the smallest N whose labels do not touch. */
export function axisLabelStep(unit: BucketUnit, slotWidth: number): number {
  const { steps, width } = LABEL_STEPS[unit];
  return steps.find(step => slotWidth * step >= width) ?? steps[steps.length - 1];
}

const shortDate = (instant: number, timeZone: string) =>
  new Date(instant).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone });
const hourOfDay = (instant: number, timeZone: string) =>
  new Date(instant).toLocaleTimeString("en-US", { hour: "numeric", timeZone });

/** A bucket named for people: "Sep 28, 3 PM–4 PM", "Sep 28" or "Week of Sep 21". */
export function bucketLabel(unit: BucketUnit, from: number, to: number, timeZone: string): string {
  if (unit === "hour") {
    return `${shortDate(from, timeZone)}, ${hourOfDay(from, timeZone)}–${hourOfDay(to, timeZone)}`;
  }
  return unit === "week" ? `Week of ${shortDate(from, timeZone)}` : shortDate(from, timeZone);
}
