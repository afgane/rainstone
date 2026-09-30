import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { RunTotals } from "../../api";
import RunFigures from "./RunFigures.vue";

const TOTALS: RunTotals = {
  amount: "216.74", incomplete_run_count: 0, shared_job_count: 0, run_count: 147,
  by_status: { completed: 131, failed: 13, running: 3 }, workflow_count: 8, unfiltered_run_count: 147,
};

function figures(totals: Partial<RunTotals> = {}, props: Record<string, unknown> = {}) {
  return mount(RunFigures, {
    props: {
      totals: { ...TOTALS, ...totals }, periodText: "Sep 1, 2026 – Sep 29, 2026 · UTC",
      workflowName: "", narrowed: false, ...props,
    },
  });
}

const lines = (wrapper: ReturnType<typeof figures>) => wrapper.findAll("section").map(card => card.findAll("p").length);

describe("RunFigures", () => {
  it("reads the period's total from the server's figures", () => {
    const wrapper = figures();
    expect(wrapper.text()).toContain("$216.74");
    expect(wrapper.text()).toContain("Estimated run compute cost");
    expect(wrapper.text()).toContain("Compute only · USD");
    expect(wrapper.text()).toContain("147");
    expect(wrapper.text()).toContain("131 completed · 13 failed · 3 running");
    expect(wrapper.text()).toContain("Across 8 workflows");
  });

  it("does not change when more rows load, because it never reads them", () => {
    const before = figures().text();
    // The list is not even a prop: nothing about how many rows are loaded reaches the cards.
    expect(figures().text()).toBe(before);
  });

  it("has the same lines in every state, and no blank ones", () => {
    const states = [
      figures(),
      figures({ amount: "5.00", run_count: 1, by_status: { failed: 1 }, unfiltered_run_count: 147 }, { narrowed: true }),
      figures({}, { workflowName: "Variant calling, one sample" }),
      figures({ amount: null, run_count: 0, by_status: {}, workflow_count: 0 }, { narrowed: true }),
    ];
    const counts = states.map(lines);
    for (const count of counts) expect(count).toEqual(counts[0]);
    for (const state of states) {
      for (const line of state.findAll("p")) expect(line.text().trim()).not.toBe("");
    }
  });

  it("puts a coverage note on the existing line, so the card's height does not change", () => {
    const plain = figures();
    const noted = figures({ incomplete_run_count: 2, shared_job_count: 3 });
    expect(lines(noted)).toEqual(lines(plain));
    expect(noted.text()).toContain("Compute only · USD · 2 runs still need cost data · Jobs shared");
  });

  it("narrows the second card to the filtered runs out of the period's", () => {
    const wrapper = figures(
      { run_count: 13, by_status: { failed: 13 }, unfiltered_run_count: 147 }, { narrowed: true },
    );
    expect(wrapper.text()).toContain("13 failed");
    expect(wrapper.text()).toContain("Out of 147 runs in this period");
    expect(wrapper.text()).toContain("Matching workflows");
    expect(wrapper.text()).not.toContain("Across");
  });

  it("names the chosen workflow as the scope", () => {
    const wrapper = figures({}, { workflowName: "Variant calling, one sample" });
    expect(wrapper.find(".figure-scope").text()).toBe("Variant calling, one sample");
    expect(wrapper.text()).toContain("Out of 147 runs in this period");
  });

  it("never shows an unavailable total as zero", () => {
    const unavailable = figures({ amount: null, run_count: 4, incomplete_run_count: 4 });
    expect(unavailable.find(".figure-amount").text()).toContain("Not available");
    expect(unavailable.text()).not.toContain("$0.00");
    const empty = figures({ amount: null, run_count: 0, by_status: {} }, { narrowed: true });
    expect(empty.text()).toContain("No matching runs");
    expect(empty.text()).toContain("No runs match");
    expect(empty.text()).not.toContain("$0.00");
  });

  it("shows an observed zero as $0.00", () => {
    expect(figures({ amount: "0.000000000000" }).find(".figure-amount").text()).toContain("$0.00");
  });

  it("says so when the total leaves out unpriced work", () => {
    const wrapper = figures({ incomplete_run_count: 4 });
    expect(wrapper.find(".figure-amount").text()).toContain("recorded so far");
    expect(wrapper.text()).toContain("4 runs still need cost data");
    expect(figures({ incomplete_run_count: 1 }).text()).toContain("1 run still needs cost data");
    expect(figures().text()).not.toContain("recorded so far");
  });

  it("says jobs shared by runs are counted once", () => {
    expect(figures({ shared_job_count: 2 }).text()).toContain("Jobs shared by these runs are counted once");
    expect(figures().text()).not.toContain("counted once");
  });
});
