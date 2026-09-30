import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { Summary, WorkloadTotals } from "../../api";
import OverviewFigures from "./OverviewFigures.vue";

const SUMMARY = {
  amount: "216.74", job_count: 531, unpriced_job_count: 0,
} as unknown as Summary;
const WORKLOAD: WorkloadTotals = {
  amount: "216.74", job_count: 531, by_outcome: { completed: 507, failed: 21, running: 3 },
  run_count: 151, workflow_count: 8, individual_job_count: 40,
};

function figures(summary: Partial<Summary> = {}, workload: Partial<WorkloadTotals> = {}) {
  return mount(OverviewFigures, {
    props: {
      summary: { ...SUMMARY, ...summary } as Summary, workload: { ...WORKLOAD, ...workload },
      periodText: "Sep 1, 2026 – Sep 29, 2026 · UTC",
    },
  });
}

describe("OverviewFigures", () => {
  it("has a cost summary on the left and a workload summary on the right", () => {
    const cards = figures().findAll("section");
    expect(cards).toHaveLength(2);
    expect(cards[0].text()).toContain("Estimated run compute cost");
    expect(cards[0].text()).toContain("$216.74");
    expect(cards[0].text()).toContain("Compute only · USD");
    expect(cards[1].text()).toContain("Workload");
    // Jobs and workflow runs each get a shaded block of their own, with their own details.
    const [jobs, runs] = cards[1].findAll(".workload-group");
    expect(jobs.find(".workload-label").text()).toBe("Jobs");
    expect(jobs.find(".figure-amount").text()).toBe("531");
    expect(jobs.text()).toContain("507 completed · 21 failed · 3 running");
    expect(runs.find(".workload-label").text()).toBe("Workflow runs");
    expect(runs.find(".figure-amount").text()).toBe("151");
    expect(runs.text()).toContain("Across 8 workflows");
    expect(jobs.text()).not.toContain("Across");
  });

  it("says when the cost leaves out unpriced work", () => {
    const wrapper = figures({ unpriced_job_count: 4 });
    expect(wrapper.text()).toContain("recorded so far");
    expect(wrapper.text()).toContain("4 jobs still need cost data");
  });

  it("never shows an unavailable total as zero, and says so when nothing ran", () => {
    expect(figures({ amount: null, job_count: 4, unpriced_job_count: 4 }).text()).toContain("Not available");
    const quiet = figures({ amount: null, job_count: 0 }, { job_count: 0, by_outcome: {}, run_count: 0, workflow_count: 0 });
    expect(quiet.text()).toContain("No jobs");
    expect(quiet.text()).toContain("No jobs in this period.");
    expect(quiet.text()).not.toContain("$0.00");
    expect(quiet.findAll(".workload-group .figure-amount").map(node => node.text())).toEqual(["0", "0"]);
    expect(quiet.text()).toContain("Across 0 workflows");
  });

  it("uses the right words at one", () => {
    const wrapper = figures({}, { job_count: 1, run_count: 1, workflow_count: 1, by_outcome: { completed: 1 } });
    expect(wrapper.findAll(".workload-label").map(node => node.text())).toEqual(["Job", "Workflow run"]);
    expect(wrapper.text()).toContain("Across 1 workflow");
  });
});

describe("OverviewFigures job count", () => {
  it("counts every job, whether or not it ran in a workflow", () => {
    const wrapper = mount(OverviewFigures, {
      props: {
        summary: SUMMARY, periodText: "",
        workload: { ...WORKLOAD, job_count: 542, run_count: 151, individual_job_count: 40 },
      },
    });
    expect(wrapper.find(".workload-group .figure-amount").text()).toBe("542");
  });
});
