import { describe, expect, it } from "vitest";
import type { ServerActivity } from "./api";
import { jobMarks } from "./serverActivity";

const activity: ServerActivity = {
  from: "2026-10-01T00:00:00Z", to: "2026-10-01T01:00:00Z", kind: "dots", job_count: 3,
  intervals: [
    { job_id: "a", source_id: "1", from: "2026-10-01T00:00:00Z", to: "2026-10-01T00:10:00Z", running: false },
    { job_id: "b", source_id: "2", from: "2026-10-01T00:05:00Z", to: "2026-10-01T00:25:00Z", running: false },
    { job_id: "c", source_id: "3", from: "2026-10-01T00:30:00Z", to: "2026-10-01T01:00:00Z", running: false },
  ], steps: [],
};

describe("server job duration marks", () => {
  it("positions and sizes jobs against the whole session and separates overlaps", () => {
    const marks = jobMarks(activity, 608);
    expect(marks.map(mark => [mark.x, mark.width, mark.lane])).toEqual([
      [4, 100, 0], [54, 200, 1], [304, 300, 0],
    ]);
  });

  it("keeps very short jobs visible within the plot at narrow widths", () => {
    const tiny = { ...activity, intervals: [{ ...activity.intervals[0],
      from: "2026-10-01T00:59:59Z", to: activity.to }] };
    const [mark] = jobMarks(tiny, 100);
    expect(mark.width).toBeGreaterThan(0);
    expect(mark.x + mark.width).toBeLessThanOrEqual(96);
    expect(jobMarks(null, 608)).toEqual([]);
    expect(jobMarks({ ...activity, kind: "steps" }, 608)).toEqual([]);
  });
});
