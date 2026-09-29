import { offsetBoundary, type BucketUnit } from "../api";
import { monthEnd, shiftDays, type Period } from "../periods";

export interface AxisSlot { from: number; to: number }

/** Local calendar arithmetic on a `YYYY-MM-DD` date, free of timezone drift. */
function addDays(date: string, days: number): string {
  const [year, month, day] = date.split("-").map(Number);
  const moved = new Date(Date.UTC(year, month - 1, day + days));
  return moved.toISOString().slice(0, 10);
}

/** The calendar date an instant falls on in the report's timezone. */
export function localDate(instant: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(instant));
}

/**
 * Every bucket of the axis, empty ones included, in order. The server sends only
 * buckets that hold cost, with an axis whose ends are local bucket boundaries.
 * Hours are absolute, which is what makes a daylight-saving day 23 or 25 of them.
 */
export function axisSlots(unit: BucketUnit, axis: { from: string; to: string }, timezone: string): AxisSlot[] {
  const end = Date.parse(axis.to);
  const slots: AxisSlot[] = [];
  if (unit === "hour") {
    for (let from = Date.parse(axis.from); from < end; from += 3600e3) {
      slots.push({ from, to: from + 3600e3 });
    }
    return slots;
  }
  const step = unit === "week" ? 7 : 1;
  const lastDate = localDate(axis.to, timezone);
  const at = (date: string) => Date.parse(offsetBoundary(`${date}T00:00:00`, timezone));
  for (let date = localDate(axis.from, timezone); date < lastDate; date = addDays(date, step)) {
    slots.push({ from: at(date), to: at(addDays(date, step)) });
  }
  return slots;
}

/**
 * Where a period's chart axis ends. A week or month still in progress is drawn
 * whole, its coming days empty; any other period ends where it does.
 */
export function periodAxisEnd(period: Period, timezone: string): string {
  const lastDay = period.id === "this-week" ? shiftDays(period.fromDate, 6)
    : period.id === "this-month" ? monthEnd(period.fromDate) : period.toDate;
  return offsetBoundary(shiftDays(lastDay, 1), timezone);
}

/** A bucket's axis label: the hour of day, or the month and day. */
export function axisText(unit: BucketUnit, from: number, timezone: string): string {
  return new Date(from).toLocaleString(
    "en-US",
    unit === "hour" ? { hour: "numeric", timeZone: timezone } : { month: "short", day: "numeric", timeZone: timezone },
  );
}
