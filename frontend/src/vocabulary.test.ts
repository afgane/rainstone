import { describe, expect, it } from "vitest";
import {
  acrossWorkflows, capacityLabel, coverageSentence, costExplanation, durationText, focusChipLabel,
  formatAxisCost, formatCost, formatDate, formatDuration, formatRate, outcomeMix, outOfRuns,
  costChartTitle, jobOutcomes, pieceCounts, qualityLabel, rangeCaption, showingOf, showMore,
  undatedSentence, unplacedSentence,
} from "./vocabulary";

describe("money", () => {
  it("keeps zero, small amounts and unknown distinct", () => {
    expect(formatCost("0")).toBe("$0.00");
    expect(formatCost("0.000004")).toBe("less than $0.01");
    expect(formatCost(null)).toBe("Not available");
    expect(formatCost("12.3456")).toBe("$12.35");
  });

  it("keeps sub-cent precision in an hourly rate", () => {
    expect(formatRate("0.2")).toBe("$0.20/hour while running");
    expect(formatRate("0.168984")).toBe("$0.169/hour while running");
    expect(formatRate(null)).toBe("Not available");
  });
});

describe("vocabulary", () => {
  it("explains a known zero as the existing server rather than free", () => {
    expect(qualityLabel("known_zero")).toContain("Used your Galaxy server");
    expect(costExplanation({ quality: "known_zero", amount: "0" }))
      .toContain("The server continues to incur costs");
  });

  it("says why a cost is missing instead of showing it as zero", () => {
    expect(qualityLabel("unpriced")).toBe("Price unavailable");
    expect(costExplanation({ quality: "unpriced", amount: null }))
      .toContain("unavailable rather than zero");
    expect(costExplanation({ quality: "partial", amount: "1" })).toContain("subtotal");
  });

  it("names where work ran only when the relationship is established", () => {
    expect(capacityLabel(["existing"])).toBe("Your Galaxy server");
    expect(capacityLabel(["dedicated"])).toBe("Dedicated cloud compute");
    expect(capacityLabel(["unknown"])).toBe("Not established");
    expect(capacityLabel([])).toBe("Not established");
  });

  it("counts incomplete coverage next to the amount", () => {
    expect(coverageSentence(5, 2)).toBe("2 jobs still need cost data.");
    expect(coverageSentence(5, 0)).toBe("5 jobs included.");
    expect(coverageSentence(0, 0)).toBe("No jobs in this period.");
  });
});

describe("missing evidence", () => {
  it("never calls finished or paused work running", () => {
    expect(qualityLabel("unavailable")).toBe("Cost data unavailable");
    expect(qualityLabel("not_started")).toBe("Not run yet");
    expect(costExplanation({ quality: "unavailable", amount: null })).not.toContain("running");
    expect(costExplanation({ quality: "unpriced", amount: null })).toContain("when it ran");
  });

  it("says undated work is outside the period rather than in it", () => {
    expect(undatedSentence(1)).toBe("1 job has no usable timing, so it is left out of every period's totals.");
    expect(undatedSentence(41)).toContain("41 jobs have");
  });
});

describe("dates", () => {
  it("follows the report timezone, not the browser's", () => {
    const lateUtc = "2026-09-23T00:58:23.099351Z";
    expect(formatDate(lateUtc, "UTC")).toContain("23");
    expect(formatDate(lateUtc, "America/New_York")).toContain("22");
  });
});

describe("the Workflow runs vocabulary", () => {
  it("writes axis ticks in whole dollars or cents", () => {
    expect(formatAxisCost(5)).toBe("$5");
    expect(formatAxisCost(0.25)).toBe("$0.25");
    expect(formatAxisCost(2.5)).toBe("$2.50");
  });

  it("writes a duration in minutes or hours, and 'so far' while running", () => {
    expect(formatDuration(20)).toBe("1 min");
    expect(formatDuration(2700)).toBe("45 min");
    expect(formatDuration(7500)).toBe("2 h 5 min");
    expect(formatDuration(7200)).toBe("2 h");
    expect(formatDuration(null)).toBe("Not available");
    expect(durationText(600, "running")).toBe("10 min so far");
    expect(durationText(600, "completed")).toBe("10 min");
  });

  it("counts runs and workflows with correct grammar", () => {
    expect(acrossWorkflows(1)).toBe("Across 1 workflow");
    expect(acrossWorkflows(8)).toBe("Across 8 workflows");
    expect(outOfRuns(147)).toBe("Out of 147 runs in this period");
    expect(showingOf(20, 147)).toBe("Showing 20 of 147");
    expect(showMore(20)).toBe("Show 20 more");
  });

  it("names the outcome mix in a fixed order and leaves out what is absent", () => {
    expect(outcomeMix({ failed: 13, completed: 131, running: 3 })).toBe("131 completed · 13 failed · 3 running");
    expect(outcomeMix({})).toBe("");
  });

  it("describes a whole-run range and what it leaves out", () => {
    const range = { minimum: "0.05", maximum: "1.51", included_run_count: 2, excluded_run_count: 0 };
    expect(rangeCaption(range)).toBe("Whole-run totals range from $0.05 to $1.51.");
    expect(rangeCaption({ ...range, minimum: "1.51", included_run_count: 1 })).toBe("One run, $1.51 in total.");
    expect(rangeCaption({ ...range, excluded_run_count: 3 })).toContain("3 runs left out");
    expect(rangeCaption({ minimum: null, maximum: null, included_run_count: 0, excluded_run_count: 1 }))
      .toBe("Whole-run range not available. 1 run left out: still running or missing cost data.");
  });

  it("names a focus window by its day, days or hour", () => {
    expect(focusChipLabel("2026-09-28T00:00:00Z", "2026-09-29T00:00:00Z", "UTC")).toBe("Runs active Sep 28");
    expect(focusChipLabel("2026-09-21T00:00:00Z", "2026-09-28T00:00:00Z", "UTC")).toBe("Runs active Sep 21–Sep 27");
    expect(focusChipLabel("2026-09-28T15:00:00Z", "2026-09-28T16:00:00Z", "UTC")).toBe("Runs active Sep 28, 3 PM–4 PM");
    expect(focusChipLabel("2026-09-28T00:00:00Z", "2026-09-29T00:00:00Z", "UTC", "completed"))
      .toBe("Runs with jobs completed Sep 28");
  });
});

describe("the Overview vocabulary", () => {
  it("titles the chart for its columns", () => {
    expect(costChartTitle("day")).toBe("Daily cost");
    expect(costChartTitle("hour")).toBe("Hourly cost");
    expect(costChartTitle("week")).toBe("Weekly cost");
  });

  it("says what a block holds, leaving out runs for work outside a workflow", () => {
    expect(pieceCounts(3, 9)).toBe("3 runs · 9 jobs");
    expect(pieceCounts(1, 1)).toBe("1 run · 1 job");
    expect(pieceCounts(0, 4)).toBe("4 jobs");
  });

  it("names failed and still-running jobs", () => {
    expect(jobOutcomes(1, 2)).toBe("1 failed, 2 still running");
    expect(jobOutcomes(0, 1)).toBe("1 still running");
    expect(jobOutcomes(0, 0)).toBe("");
  });

  it("writes the unplaced note without stray spaces", () => {
    expect(unplacedSentence(2, "1.5")).toBe("Cannot be placed in time: 2 jobs, $1.50.");
    expect(unplacedSentence(1, null)).toBe("Cannot be placed in time: 1 job.");
  });
});
