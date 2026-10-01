import { describe, expect, it } from "vitest";
import { costShares, parseWindowId, windowId, windowLabel } from "./jobsView";

describe("chart intervals in the address", () => {
  it("round-trips an interval", () => {
    const window = { unit: "day" as const, from: "2026-09-02T00:00:00.000Z", to: "2026-09-03T00:00:00.000Z" };
    expect(parseWindowId(windowId(window))).toEqual(window);
  });

  it("refuses an identifier that names no interval", () => {
    expect(parseWindowId("fortnight|2026-09-02T00:00:00Z|2026-09-03T00:00:00Z")).toBeNull();
    expect(parseWindowId("day|soon|later")).toBeNull();
    expect(parseWindowId("")).toBeNull();
  });

  it("names an interval in the report's timezone", () => {
    expect(windowLabel({ unit: "day", from: "2026-09-02T04:00:00Z", to: "2026-09-03T04:00:00Z" }, "America/New_York"))
      .toBe("Sep 2");
    expect(windowLabel({ unit: "week", from: "2026-09-21T00:00:00Z", to: "2026-09-28T00:00:00Z" }, "UTC"))
      .toBe("Week of Sep 21");
  });
});

describe("status shares", () => {
  it("gives positive pieces exact shares and leaves out zero and unknown ones", () => {
    const shares = costShares([
      { status: "completed", amount: "3", job_count: 2, incomplete_job_count: 0 },
      { status: "running", amount: "0", job_count: 1, incomplete_job_count: 0 },
      { status: "failed", amount: "1", job_count: 1, incomplete_job_count: 0 },
      { status: "other", amount: null, job_count: 1, incomplete_job_count: 1 },
    ]);
    expect(shares.map(entry => [entry.piece.status, entry.share])).toEqual([["completed", 0.75], ["failed", 0.25]]);
  });

  it("draws nothing when no piece has a cost", () => {
    expect(costShares([{ status: "completed", amount: "0", job_count: 4, incomplete_job_count: 0 }])).toEqual([]);
  });
});
