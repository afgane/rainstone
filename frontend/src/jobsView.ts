import type { BucketUnit, JobStatus, StatusPiece } from "./api";
import { bucketLabel } from "./chart/layout";

/** The order status pieces are stacked and listed in, everywhere on the Jobs page. */
export const STATUS_ORDER: JobStatus[] = ["completed", "running", "failed", "other"];

/** A chart interval a drawer is opened for: its unit and its bounds, already inside the period. */
export interface JobWindow { unit: BucketUnit; from: string; to: string }

const UNITS: BucketUnit[] = ["hour", "day", "week"];

/** An interval as it travels in the address, as one drawer identifier. */
export function windowId(window: JobWindow): string {
  return `${window.unit}|${window.from}|${window.to}`;
}

export function parseWindowId(id: string): JobWindow | null {
  const [unit, from, to] = id.split("|");
  if (!UNITS.includes(unit as BucketUnit) || Number.isNaN(Date.parse(from)) || Number.isNaN(Date.parse(to))) {
    return null;
  }
  return { unit: unit as BucketUnit, from, to };
}

/** "Sep 28", "Sep 28, 3 PM–4 PM" or "Week of Sep 21", in the report's timezone. */
export function windowLabel(window: JobWindow, timezone: string): string {
  return bucketLabel(window.unit, Date.parse(window.from), Date.parse(window.to), timezone);
}

/** Pieces with a positive cost, as fractions of the whole that add up to one. */
export function costShares(pieces: StatusPiece[]): Array<{ piece: StatusPiece; share: number }> {
  const drawn = pieces.filter(piece => Number(piece.amount) > 0);
  const total = drawn.reduce((sum, piece) => sum + Number(piece.amount), 0);
  return total > 0 ? drawn.map(piece => ({ piece, share: Number(piece.amount) / total })) : [];
}
