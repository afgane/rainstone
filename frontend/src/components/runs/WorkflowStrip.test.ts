import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { BreakdownGroup, BreakdownRun } from "../../api";
import WorkflowStrip from "./WorkflowStrip.vue";

function run(id: string, chart: string | null, status = "completed"): BreakdownRun {
  return {
    id, amount: chart, run_total: chart, chart_amount: chart, shared_job_count: 0,
    run_total_complete: true, status, started_at: "2026-09-02T00:00:00Z", duration_seconds: 600,
  };
}

function group(overrides: Partial<BreakdownGroup> = {}): BreakdownGroup {
  return {
    key: "family-7", name: "Variant calling, one sample", run_count: 2, by_status: {}, amount: "3",
    incomplete_run_count: 0, runs: [run("a", "2"), run("b", "1")],
    remainder: { count: 0, amount: "0", failed: 0, running: 0, boundary: null },
    whole_run_range: { minimum: "0.05", maximum: "1.51", included_run_count: 2, excluded_run_count: 0 },
    ...overrides,
  };
}

function strip(value: BreakdownGroup | null) {
  return mount(WorkflowStrip, {
    props: { group: value, openRunId: "", hoverRunId: "", timezone: "UTC" },
  });
}

describe("WorkflowStrip", () => {
  it("is always present, with a hint when no workflow is chosen", () => {
    const wrapper = strip(null);
    expect(wrapper.find(".wf-row.zoom").exists()).toBe(true);
    expect(wrapper.text()).toContain("Every run, at its own scale");
    expect(wrapper.text()).toContain("Choose a workflow");
  });

  it("states the whole-run range the server computed", () => {
    expect(strip(group()).text()).toContain("Whole-run totals range from $0.05 to $1.51.");
  });

  it("gives one eligible run's total when only one qualifies", () => {
    const wrapper = strip(group({
      whole_run_range: { minimum: "1.51", maximum: "1.51", included_run_count: 1, excluded_run_count: 0 },
    }));
    expect(wrapper.text()).toContain("One run, $1.51 in total.");
  });

  it("reports the runs left out of the range, even when none are drawn individually", () => {
    // Every eligible run is beyond the 200 the server sends: the chart holds only the remainder.
    const wrapper = strip(group({
      runs: [], run_count: 300,
      remainder: {
        count: 300, amount: "30", failed: 0, running: 0, boundary: { amount: "0.1", run_id: "z" },
      },
      whole_run_range: { minimum: "0.05", maximum: "1.51", included_run_count: 290, excluded_run_count: 10 },
    }));
    const caption = wrapper.find(".strip-caption").text();
    expect(caption).toContain("range from $0.05 to $1.51");
    expect(caption).toContain("10 runs left out");
  });

  it("says the range is not available, with the count left out, when no run qualifies", () => {
    const wrapper = strip(group({
      whole_run_range: { minimum: null, maximum: null, included_run_count: 0, excluded_run_count: 2 },
    }));
    expect(wrapper.text()).toContain("Whole-run range not available.");
    expect(wrapper.text()).toContain("2 runs left out");
  });

  it("keeps the caption line in every state", () => {
    for (const value of [null, group(), group({ amount: null, runs: [] })]) {
      expect(strip(value).find(".strip-caption").exists()).toBe(true);
    }
  });

  it("draws the selected workflow's cost as its value", () => {
    expect(strip(group()).find(".total").text()).toBe("$3.00");
  });
});
