import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { JobTimeline } from "../../api";
import JobTimeBars from "./JobTimeBars.vue";

const TOTALS = { amount: "2", job_count: 3, tool_count: 1, incomplete_job_count: 1, known_zero_job_count: 0, by_status: [] };

function timeline(): JobTimeline {
  return {
    bucket: "day", label: "Cost accrued", unplaced: null, totals: TOTALS, meta: {} as JobTimeline["meta"],
    axis: { from: "2026-09-01T00:00:00+00:00", to: "2026-09-04T00:00:00+00:00" },
    buckets: [
      { from: "2026-09-01T00:00:00+00:00", to: "2026-09-02T00:00:00+00:00", amount: "2", job_count: 2,
        incomplete_job_count: 0, provisional: false, by_status: [
          { status: "completed", amount: "1.5", job_count: 1, incomplete_job_count: 0 },
          { status: "failed", amount: "0.5", job_count: 1, incomplete_job_count: 0 },
        ] },
      { from: "2026-09-02T00:00:00+00:00", to: "2026-09-03T00:00:00+00:00", amount: null, job_count: 1,
        incomplete_job_count: 1, provisional: false, by_status: [
          { status: "completed", amount: null, job_count: 1, incomplete_job_count: 1 },
        ] },
    ],
  };
}

function chart(openFrom = "") {
  return mount(JobTimeBars, { props: {
    timeline: timeline(), periodFrom: "2026-09-01T00:00:00.000Z", periodTo: "2026-09-04T00:00:00.000Z",
    axisEnd: "2026-09-05T00:00:00.000Z", openFrom, timezone: "UTC", asOf: "2026-09-10T00:00:00Z",
  } });
}

describe("the Jobs page's time columns", () => {
  it("stacks a column's cost by status, in exact shares", () => {
    const [first] = chart().findAll(".job-col");
    const blocks = first.findAll(".blk");
    expect(blocks.map(block => block.attributes("data-status"))).toEqual(["completed", "failed"]);
    const heights = blocks.map(block => parseFloat(block.attributes("style")!.replace(/[^0-9.]/g, "")));
    expect(heights[0] / heights[1]).toBeCloseTo(3);
  });

  it("marks jobs with no known cost apart from an empty interval", () => {
    const columns = chart().findAll(".job-col");
    expect(columns[1].find(".cost-missing").exists()).toBe(true);
    expect(columns[1].attributes("aria-label")).toContain("Not available");
    expect(columns[2].classes()).toContain("empty");
    expect(columns[2].find(".cost-missing").exists()).toBe(false);
    // An elapsed empty interval can still be opened.
    expect(columns[2].element.tagName).toBe("BUTTON");
  });

  it("does not offer an interval after the period", () => {
    const columns = chart().findAll(".job-col");
    expect(columns).toHaveLength(4);
    expect(columns[3].element.tagName).toBe("DIV");
    expect(columns[3].classes()).toContain("future");
  });

  it("opens an interval clipped to the period, and marks the open one", async () => {
    const wrapper = chart("2026-09-01T00:00:00.000Z");
    const first = wrapper.findAll(".job-col")[0];
    expect(first.attributes("aria-current")).toBe("true");
    await first.trigger("click");
    expect(wrapper.emitted("window")![0][0]).toEqual({
      unit: "day", from: "2026-09-01T00:00:00.000Z", to: "2026-09-02T00:00:00.000Z",
    });
  });
});
