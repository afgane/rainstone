import { describe, expect, it } from "vitest";
import {
  environmentLabel, formatCompactCost, formatJobDuration, formatShare, groupCoverage, groupHeading,
  jobCostLabel, jobDurationLabel, jobStateKind, jobStateLabel, shareBasis,
  acrossWorkflows, capacityLabel, coverageSentence, costExplanation, durationText, focusChipLabel,
  formatAxisCost, formatCost, formatDate, formatDuration, formatRate, formatRateInCents, outcomeMix, outOfRuns,
  jobOutcomes, pieceCounts, qualityLabel, rangeCaption, serverQualifiers, sharedJobsNote, showingOf, sinceLaunch,
  nowInUtc, showMore, topContributors,
  undatedSentence, unplacedSentence,
} from "./vocabulary";

describe("the current time", () => {
  it("is always given in UTC and says so", () => {
    expect(nowInUtc(new Date("2026-10-04T23:30:00Z"))).toMatch(/^Now .*Oct 4, 2026.*11:30.*UTC$/);
  });
});

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
    expect(formatRateInCents("0.3806")).toBe("$0.38/hour while running");
    expect(formatRateInCents("0.004")).toBe("less than $0.01/hour while running");
    expect(formatRateInCents(null)).toBe("Not available");
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
    expect(undatedSentence(1)).toBe("1 job could not be placed in time, so no period includes it.");
    expect(undatedSentence(2)).toBe("2 jobs could not be placed in time, so no period includes them.");
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
  it("qualifies the server's figure in a word, not a paragraph", () => {
    expect(serverQualifiers(null, false)).toEqual([]);
    expect(serverQualifiers({ ended_at: null, stale: false }, false)).toEqual([]);
    expect(serverQualifiers({ ended_at: "2026-09-29T00:00:00Z", stale: false }, false)).toEqual(["Stopped"]);
    expect(serverQualifiers({ ended_at: null, stale: true }, false)).toEqual(["Stale"]);
    expect(serverQualifiers({ ended_at: null, stale: true }, true)).toEqual(["Snapshot"]);
  });

  it("says how long the server has been up in days once it has run a day", () => {
    expect(sinceLaunch(18720)).toBe("5 h 12 min since launch");
    expect(sinceLaunch(86400)).toBe("1 day since launch");
    expect(sinceLaunch(2347200)).toBe("27 days 4 h since launch");
    expect(sinceLaunch(null)).toBe("Time since launch unavailable");
  });

  it("names a ranking as its top contributors, not a complete breakdown", () => {
    expect(topContributors(5, "workflow run")).toBe("Top 5 workflow runs");
    expect(topContributors(1, "tool")).toBe("Top tool");
    expect(sharedJobsNote(1)).toContain("1 job belongs to more than one run; it is counted once");
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

describe("the run drawer's job rows", () => {
  it("keeps seconds in a job's duration and steps up to hours and days", () => {
    expect(formatJobDuration(0.4)).toBe("<1s");
    expect(formatJobDuration(14)).toBe("14s");
    expect(formatJobDuration(128)).toBe("2m 08s");
    expect(formatJobDuration(38 * 60 + 12)).toBe("38m 12s");
    expect(formatJobDuration(3900)).toBe("1h 05m");
    expect(formatJobDuration(2 * 86400 + 3 * 3600 + 59)).toBe("2d 03h");
    expect(formatJobDuration(null)).toBe("—");
  });

  it("says a missing duration and a running one in words", () => {
    expect(jobDurationLabel(null)).toBe("Duration not available");
    expect(jobDurationLabel(90, true)).toBe("1m 30s elapsed so far");
    expect(jobDurationLabel(90)).toBe("1m 30s");
  });

  it("shortens only a positive sub-cent amount, and leaves an unknown one a dash", () => {
    expect(formatCompactCost("0.004")).toBe("<$0.01");
    expect(formatCost("0.004")).toBe("less than $0.01");
    expect(formatCompactCost("0.81")).toBe("$0.81");
    expect(formatCompactCost("0")).toBe("$0.00");
    expect(formatCompactCost(null)).toBe("—");
    expect(jobCostLabel(null)).toBe("Cost not available");
    expect(jobCostLabel("0.004")).toBe("Cost less than $0.01");
  });

  it("gives every state a distinct kind, and an unmapped one its own", () => {
    const kinds = ["ok", "error", "running", "queued", "cancelled", "paused", "new", "deleted", "resubmitted"]
      .map(jobStateKind);
    expect(new Set(kinds).size).toBe(kinds.length);
    expect(jobStateKind("something-new")).toBe("unknown");
    expect(jobStateLabel("something-new")).toBe("something-new");
  });

  it("keeps Deleted and Restarted as they are said, not as Canceled or Running", () => {
    expect(jobStateLabel("deleted")).toBe("Deleted");
    expect(jobStateLabel("resubmitted")).toBe("Restarted");
    expect(jobStateKind("deleted")).not.toBe(jobStateKind("cancelled"));
    expect(jobStateKind("resubmitted")).not.toBe(jobStateKind("running"));
  });

  it("names the places a job ran, several included", () => {
    expect(environmentLabel("dedicated")).toBe("Dedicated cloud compute");
    expect(environmentLabel("existing")).toBe("Your Galaxy server");
    expect(environmentLabel("multiple")).toBe("Multiple environments");
    expect(environmentLabel("unknown")).toBe("Not established");
  });

  it("writes a share so that a tiny one is never a bare zero", () => {
    expect(formatShare(0.001)).toBe("Less than 1%");
    expect(formatShare(0.042)).toBe("4.2%");
    expect(formatShare(0.5625)).toBe("56%");
  });

  it("says what a share is of, without implying a final total that is not known", () => {
    expect(shareBasis(true, false)).toBe("of cost so far");
    expect(shareBasis(false, false)).toBe("of recorded cost");
    expect(shareBasis(false, true)).toBe("of this run's cost");
  });

  it("labels a group with what it holds and what is missing", () => {
    expect(groupHeading("dedicated", 1)).toBe("Dedicated cloud compute · 1 job");
    expect(groupCoverage(true, 0)).toBe("");
    expect(groupCoverage(true, 2)).toBe("Recorded so far · 2 jobs still need cost data");
    expect(groupCoverage(false, 1)).toBe("1 job still needs cost data");
  });
});
