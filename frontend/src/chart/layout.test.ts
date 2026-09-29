import { describe, expect, it } from "vitest";

import type { Remainder } from "../api";
import {
  axisLabelStep, BLOCK_GAP, bucketLabel, layoutSegments, MINIMUM_HORIZONTAL, MINIMUM_VERTICAL,
  niceScale, type LayoutRun,
} from "./layout";

function run(id: string, drawn: number | null, status = "completed", amount = drawn): LayoutRun {
  return { id, drawn, amount: amount === null ? null : String(amount), status };
}

const NOTHING_LEFT: Remainder = { count: 0, amount: "0", failed: 0, running: 0, boundary: null };

describe("layoutSegments", () => {
  it("draws every run as its own block when each is big enough", () => {
    const segments = layoutSegments([run("a", 50), run("b", 30), run("c", 20)], NOTHING_LEFT, 500, 6);
    expect(segments.map(segment => segment.kind)).toEqual(["run", "run", "run"]);
    // The gaps come out of the room the blocks share.
    const sizes = segments.map(segment => segment.size);
    expect(sizes.reduce((a, b) => a + b, 0) + BLOCK_GAP * 2).toBeCloseTo(500);
    expect(sizes[0] / sizes[1]).toBeCloseTo(50 / 30);
  });

  it("folds undersized blocks into one grouped segment that ends the bar", () => {
    const runs = [run("a", 90), run("b", 5), run("c", 3), run("d", 2)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 100, 6);
    expect(segments.map(segment => segment.kind)).toEqual(["run", "more"]);
    const grouped = segments[1];
    expect(grouped.kind === "more" && grouped.count).toBe(3);
    expect(grouped.kind === "more" && grouped.drawn).toBe(10);
  });

  it("names the fold by its first run, so equal amounts cannot leak into the selection", () => {
    const runs = [run("a", 90, "completed", 9), run("b", 5, "completed", 0.5), run("c", 3, "completed", 0.5)];
    const [, grouped] = layoutSegments(runs, NOTHING_LEFT, 100, 6);
    expect(grouped.kind === "more" && grouped.boundary).toEqual({ amount: "0.5", runId: "b" });
  });

  it("folds a contiguous suffix, including a block larger than the first undersized one", () => {
    // A shared-job adjustment can make a later block bigger than an earlier small one.
    const runs = [run("a", 90), run("b", 4), run("c", 40)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 100, 6);
    expect(segments.map(segment => segment.kind)).toEqual(["run", "more"]);
    const grouped = segments[1];
    expect(grouped.kind === "more" && grouped.count).toBe(2);
    expect(grouped.kind === "more" && grouped.boundary?.runId).toBe("b");
  });

  it("keeps a lone undersized block as a block at the minimum size", () => {
    const segments = layoutSegments([run("a", 99), run("b", 1)], NOTHING_LEFT, 200, 6);
    expect(segments.map(segment => segment.kind)).toEqual(["run", "run"]);
    expect(segments[1].size).toBe(6);
  });

  it("merges the server's remainder into the folded suffix", () => {
    const remainder: Remainder = {
      count: 50, amount: "5", failed: 2, running: 1, boundary: { amount: "0.1", run_id: "z" },
    };
    const runs = [run("a", 90), run("b", 4, "failed")];
    const segments = layoutSegments(runs, remainder, 100, 6);
    const grouped = segments[segments.length - 1];
    expect(grouped.kind).toBe("more");
    if (grouped.kind !== "more") return;
    expect(grouped.count).toBe(51);
    expect(grouped.failed).toBe(3);
    expect(grouped.running).toBe(1);
    // The first folded client run starts the selection, not the server's boundary.
    expect(grouped.boundary).toEqual({ amount: "4", runId: "b" });
  });

  it("uses the server's boundary when only the remainder is grouped", () => {
    const remainder: Remainder = {
      count: 50, amount: "20", failed: 0, running: 0, boundary: { amount: "0.1", run_id: "z" },
    };
    const segments = layoutSegments([run("a", 50), run("b", 30)], remainder, 500, 6);
    expect(segments.map(segment => segment.kind)).toEqual(["run", "run", "more"]);
    const grouped = segments[2];
    expect(grouped.kind === "more" && grouped.boundary).toEqual({ amount: "0.1", runId: "z" });
  });

  it("selects a whole column when a boundary would mean nothing", () => {
    const runs = [run("a", 90), run("b", 3), run("c", 2), run("d", 1)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 100, 5, { selectableBoundary: false });
    const grouped = segments[segments.length - 1];
    expect(grouped.kind === "more" && grouped.boundary).toBeNull();
  });

  it("never gives zero or unknown cost a block", () => {
    const runs = [run("a", 50), run("zero", 0), run("unknown", null), run("b", 50)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 400, 6);
    const ids = segments.flatMap(segment => (segment.kind === "run" ? [segment.run.id] : []));
    expect(ids).toEqual(["a", "b"]);
  });

  it("draws nothing when nothing has a positive cost", () => {
    expect(layoutSegments([run("zero", 0), run("unknown", null)], NOTHING_LEFT, 400, 6)).toEqual([]);
    expect(layoutSegments([], NOTHING_LEFT, 400, 6)).toEqual([]);
  });

  it("leaves zero and unknown out of an undersized fold's count", () => {
    const runs = [run("a", 90), run("zero", 0), run("b", 4), run("c", 3)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 100, 6);
    const grouped = segments[segments.length - 1];
    expect(grouped.kind === "more" && grouped.count).toBe(2);
  });

  it("never draws below the minimum, whatever the length", () => {
    const segments = layoutSegments([run("a", 1), run("b", 1)], NOTHING_LEFT, 4, MINIMUM_VERTICAL);
    expect(segments.every(segment => segment.size >= MINIMUM_VERTICAL)).toBe(true);
    const wide = layoutSegments([run("a", 99), run("b", 1), run("c", 1)], NOTHING_LEFT, 600, MINIMUM_HORIZONTAL);
    expect(wide.every(segment => segment.size >= MINIMUM_HORIZONTAL)).toBe(true);
  });

  it("keeps the order it was given, with the grouped segment last", () => {
    const runs = [run("a", 40), run("b", 30), run("c", 2), run("d", 1)];
    const segments = layoutSegments(runs, NOTHING_LEFT, 200, 6);
    expect(segments.map(segment => (segment.kind === "run" ? segment.run.id : "more"))).toEqual([
      "a", "b", "more",
    ]);
  });
});

describe("niceScale", () => {
  it("falls back to a unit scale for nothing to draw", () => {
    expect(niceScale(0)).toEqual({ max: 1, step: 0.25 });
    expect(niceScale(-3)).toEqual({ max: 1, step: 0.25 });
    expect(niceScale(Number.NaN)).toEqual({ max: 1, step: 0.25 });
  });

  it("rounds tiny maxima up to a readable step", () => {
    const scale = niceScale(0.0032);
    expect(scale.max).toBeGreaterThanOrEqual(0.0032);
    expect(scale.max / scale.step).toBeLessThanOrEqual(5);
    expect(scale.step).toBeCloseTo(0.001);
  });

  it("uses 1, 2, 2.5, 5 or 10 times a power of ten", () => {
    for (const [max, step] of [[4, 1], [8, 2], [10, 2.5], [20, 5], [40, 10], [400, 100]]) {
      expect(niceScale(max).step).toBe(step);
    }
  });

  it("covers large maxima with about four ticks", () => {
    const scale = niceScale(123456);
    expect(scale.max).toBeGreaterThanOrEqual(123456);
    expect(scale.max / scale.step).toBeLessThanOrEqual(5);
  });

  it("never lets the scale end below the largest column", () => {
    for (const max of [0.5, 1, 3.7, 25, 99.9, 1000]) {
      expect(niceScale(max).max).toBeGreaterThanOrEqual(max);
    }
  });
});

describe("axisLabelStep", () => {
  it("labels every bucket when there is room", () => {
    expect(axisLabelStep("hour", 60)).toBe(1);
    expect(axisLabelStep("day", 50)).toBe(1);
  });

  it("steps through 1, 2, 3, 4, 6 for hours by a 46px label", () => {
    expect(axisLabelStep("hour", 30)).toBe(2);
    expect(axisLabelStep("hour", 20)).toBe(3);
    expect(axisLabelStep("hour", 12)).toBe(4);
    expect(axisLabelStep("hour", 9)).toBe(6);
  });

  it("steps through 1, 2, 3, 5, 7 for days by a 46px label, month and day", () => {
    expect(axisLabelStep("day", 30)).toBe(2);
    expect(axisLabelStep("day", 20)).toBe(3);
    expect(axisLabelStep("day", 10)).toBe(5);
    expect(axisLabelStep("day", 3)).toBe(7);
  });

  it("stops at the widest step rather than dropping every label", () => {
    expect(axisLabelStep("hour", 1)).toBe(6);
    expect(axisLabelStep("day", 0)).toBe(7);
  });
});

describe("bucketLabel", () => {
  const at = (iso: string) => Date.parse(iso);

  it("names an hour by its day and both ends", () => {
    expect(bucketLabel("hour", at("2026-09-28T15:00:00Z"), at("2026-09-28T16:00:00Z"), "UTC"))
      .toBe("Sep 28, 3 PM–4 PM");
  });

  it("names a day and a week by their first day", () => {
    expect(bucketLabel("day", at("2026-09-28T00:00:00Z"), at("2026-09-29T00:00:00Z"), "UTC"))
      .toBe("Sep 28");
    expect(bucketLabel("week", at("2026-09-21T00:00:00Z"), at("2026-09-28T00:00:00Z"), "UTC"))
      .toBe("Week of Sep 21");
  });

  it("reads the day in the report's timezone", () => {
    expect(bucketLabel(
      "day", at("2026-09-28T04:00:00Z"), at("2026-09-29T04:00:00Z"), "America/New_York",
    )).toBe("Sep 28");
  });
});
