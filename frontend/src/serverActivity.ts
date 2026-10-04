import type { ServerActivity, ServerJobInterval } from "./api";

/** Pack duration marks without covering a neighbor, including tiny executions. */
export function jobMarks(activity: ServerActivity | null, width: number) {
  if (!activity || activity.kind !== "dots") return [];
  const start = Date.parse(activity.from), end = Date.parse(activity.to);
  if (end <= start) return [];
  const lanes: number[] = [];
  return activity.intervals.map((interval: ServerJobInterval) => {
    const x = 4 + (Date.parse(interval.from) - start) / (end - start) * (width - 8);
    const right = 4 + (Date.parse(interval.to) - start) / (end - start) * (width - 8);
    const size = Math.min(width - 4 - x, Math.max(3, right - x));
    let lane = lanes.findIndex(previous => previous + 3 <= x);
    if (lane === -1) lane = lanes.length;
    lanes[lane] = x + size;
    return { interval, x, width: size, lane };
  });
}
