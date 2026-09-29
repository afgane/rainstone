import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { CostBucket, CostPiece, CostTimeline } from "../../api";
import OverviewCostChart from "./OverviewCostChart.vue";

function piece(overrides: Partial<CostPiece> = {}): CostPiece {
  return {
    key: "runs", kind: "runs", name: "Workflow runs", amount: "6",
    job_count: 9, run_count: 3, failed: 1, running: 0, ...overrides,
  };
}

const INDIVIDUAL = piece({
  key: "individual", kind: "individual", name: "Individual jobs", amount: "2", job_count: 4, run_count: 0,
  failed: 0, running: 1,
});

function bucket(pieces: CostPiece[], day = "02"): CostBucket {
  return {
    from: `2026-09-${day}T00:00:00+00:00`, to: `2026-09-${String(Number(day) + 1).padStart(2, "0")}T00:00:00+00:00`,
    amount: "8", job_count: 13, run_count: 3, failed_job_count: 1, running_job_count: 1,
    incomplete_job_count: 0, provisional: false, pieces,
  };
}

function timeline(buckets: CostBucket[] = [bucket([piece(), INDIVIDUAL])]): CostTimeline {
  return {
    bucket: "day", buckets, axis: { from: "2026-09-01T00:00:00+00:00", to: "2026-09-05T00:00:00+00:00" },
    totals: {
      amount: "8", job_count: 13, by_outcome: {}, run_count: 3, workflow_count: 1,
      individual_job_count: 4,
    },
    label: "Cost accrued", unplaced: null, meta: {} as CostTimeline["meta"],
  };
}

function chart(value: CostTimeline = timeline()) {
  return mount(OverviewCostChart, {
    props: {
      timeline: value, timezone: "UTC", asOf: "2026-09-03T00:00:00Z",
      periodFrom: "2026-09-01T00:00:00Z", periodTo: "2026-09-05T00:00:00Z",
      axisEnd: "2026-09-05T00:00:00Z",
    },
    attachTo: document.body,
  });
}

const hover = (node: { element: Element }) =>
  node.element.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientX: 40, clientY: 40 }));

describe("OverviewCostChart", () => {
  it("names every day of the period, month included, whether or not anything cost", () => {
    const wrapper = chart();
    expect(wrapper.findAll(".xaxis .xl")).toHaveLength(4);
    const labels = wrapper.findAll(".xaxis .xl span").map(node => node.text());
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) expect(label).toMatch(/^Sep \d+$/);
    expect(wrapper.find("h2").text()).toBe("Daily cost");
  });

  it("draws one block for all the workflow runs and one for the individual jobs, told apart by texture", () => {
    const blocks = chart().findAll(".blk");
    expect(blocks.map(block => block.attributes("data-kind")).sort()).toEqual(["individual", "runs"]);
    expect(chart().find(".chart-foot").text()).toContain("Jobs outside any workflow");
  });

  it("opens the workflow runs page from the runs block, for that column's dates", async () => {
    const wrapper = chart();
    await wrapper.find('.blk[data-kind="runs"]').trigger("click");
    expect(wrapper.emitted("runs")).toEqual([[{
      from: "2026-09-02T00:00:00+00:00", to: "2026-09-03T00:00:00+00:00",
    }]]);
    expect(wrapper.emitted("jobs")).toBeUndefined();
  });

  it("opens the jobs from the individual jobs' block", async () => {
    const wrapper = chart();
    await wrapper.find('.blk[data-kind="individual"]').trigger("click");
    expect(wrapper.emitted("jobs")).toEqual([[{
      from: "2026-09-02T00:00:00+00:00", to: "2026-09-03T00:00:00+00:00",
    }]]);
  });

  it("does nothing when a column, rather than a block, is pressed", async () => {
    const wrapper = chart();
    await wrapper.find(".col:not(.empty)").trigger("click");
    expect(wrapper.emitted("runs")).toBeUndefined();
    expect(wrapper.emitted("jobs")).toBeUndefined();
  });

  it("explains a block in an overlay: cost, counts and outcomes", async () => {
    const wrapper = chart();
    hover(wrapper.find('.blk[data-kind="runs"]'));
    await wrapper.vm.$nextTick();
    const tip = wrapper.find(".chart-tip").text();
    expect(tip).toContain("$6.00");
    expect(tip).toContain("Workflow runs");
    expect(tip).toContain("3 runs · 9 jobs");
    expect(tip).toContain("1 failed");
    expect(tip).toContain("Select to see the runs");
    hover(wrapper.find('.blk[data-kind="individual"]'));
    await wrapper.vm.$nextTick();
    const jobs = wrapper.find(".chart-tip").text();
    expect(jobs).toContain("4 jobs");
    expect(jobs).toContain("1 still running");
    expect(jobs).toContain("Select to see the jobs");
  });

  it("summarises a whole column in an overlay too", async () => {
    const wrapper = chart();
    hover(wrapper.find(".col:not(.empty)"));
    await wrapper.vm.$nextTick();
    const tip = wrapper.find(".chart-tip").text();
    expect(tip).toContain("$8.00");
    expect(tip).toContain("Sep 2");
    expect(tip).toContain("3 runs · 13 jobs");
  });

  it("keeps the same information in a table, with a way to open each row", async () => {
    const wrapper = chart();
    const rows = wrapper.findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].text()).toContain("Workflow runs");
    expect(rows[1].text()).toContain("Individual jobs");
    await rows[0].find("button").trigger("click");
    await rows[1].find("button").trigger("click");
    expect(wrapper.emitted("runs")).toHaveLength(1);
    expect(wrapper.emitted("jobs")).toHaveLength(1);
    expect(wrapper.find("table").text()).not.toContain("Day\nDay");
  });

  it("shows the dates and says so when nothing cost anything", () => {
    const wrapper = chart(timeline([]));
    expect(wrapper.find(".plot-empty").text()).toBe("No cost was recorded in this period.");
    expect(wrapper.findAll(".xaxis .xl")).toHaveLength(4);
  });

  it("draws the coming days of an open week, muted", () => {
    const wrapper = mount(OverviewCostChart, {
      props: {
        timeline: timeline(), timezone: "UTC", asOf: "2026-09-02T12:00:00Z",
        periodFrom: "2026-09-01T00:00:00Z", periodTo: "2026-09-03T00:00:00Z",
        axisEnd: "2026-09-08T00:00:00Z",
      },
    });
    expect(wrapper.findAll(".xaxis .xl")).toHaveLength(7);
    expect(wrapper.findAll(".xaxis .xl.future").length).toBeGreaterThanOrEqual(4);
  });

  it("reports cost that cannot be placed in time", () => {
    const value = { ...timeline(), unplaced: { job_count: 2, amount: "1.5" } };
    expect(chart(value).find(".chart-notes").text()).toContain("Cannot be placed in time: 2 jobs, $1.50");
  });
});
