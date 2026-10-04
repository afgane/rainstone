import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { JobBreakdown, JobTimeline, JobTotals } from "../../api";
import JobsChart from "./JobsChart.vue";

vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });

const NO_TOTALS: JobTotals = {
  amount: null, job_count: 0, tool_count: 0, incomplete_job_count: 0, known_zero_job_count: 0, by_status: [],
};
const NO_SECTION = { tool_count: 0, job_count: 0, groups: [] };

function breakdown(totals: Partial<JobTotals> = {}): JobBreakdown {
  return {
    groups: [], total: 0, ranked_tool_count: 0,
    remainder: { tool_count: 0, job_count: 0, amount: null, incomplete_job_count: 0 },
    scale: null, server: NO_SECTION, zero: NO_SECTION, unavailable: NO_SECTION,
    totals: { ...NO_TOTALS, ...totals }, meta: {} as JobBreakdown["meta"],
  };
}

function chart(props: { chart: "tool" | "time"; breakdown?: JobBreakdown | null; timeline?: JobTimeline | null }) {
  return mount(JobsChart, {
    props: {
      breakdown: null, timeline: null, totals: NO_TOTALS, loadingChart: false, loadingRanking: false,
      toolSearch: "", openKey: "", openWindowFrom: "", periodFrom: "2026-01-05T00:00:00Z",
      periodTo: "2026-01-12T00:00:00Z", axisEnd: "2026-01-12T00:00:00Z", periodLabel: "this week",
      timezone: "UTC", asOf: null, ...props,
    },
  });
}

function onlyPlaceholder(wrapper: ReturnType<typeof chart>, sentence: string) {
  expect(wrapper.find(".chart-empty").text()).toBe(sentence);
  expect(wrapper.find(".chart-foot").exists()).toBe(false);
  expect(wrapper.find(".chart-notes").exists()).toBe(false);
  expect(wrapper.find("details").exists()).toBe(false);
  expect(wrapper.find(".panel-heading p").exists()).toBe(false);
}

describe("JobsChart", () => {
  it("shows only a placeholder when no matching job ran", () => {
    onlyPlaceholder(chart({ chart: "tool", breakdown: breakdown() }), "No tool recorded a cost in this period.");
  });

  it("shows only a placeholder, not an empty axis, when no job had compute", () => {
    const timeline = {
      bucket: "day", buckets: [], axis: null, totals: NO_TOTALS, label: "", unplaced: null, meta: {},
    } as unknown as JobTimeline;
    const wrapper = chart({ chart: "time", timeline });
    onlyPlaceholder(wrapper, "No job had compute in this period.");
    expect(wrapper.find(".tplot").exists()).toBe(false);
  });

  it("keeps the key, notes and table when jobs ran", () => {
    const wrapper = chart({ chart: "tool", breakdown: breakdown({ job_count: 2 }) });
    expect(wrapper.find(".chart-empty").exists()).toBe(false);
    expect(wrapper.find(".chart-foot").exists()).toBe(true);
    expect(wrapper.find("details").exists()).toBe(true);
  });
});
