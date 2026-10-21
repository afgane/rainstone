import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { OverheadStatistics, ToolDetail } from "../../api";
import ToolDetails from "./ToolDetails.vue";

function detail(overhead: OverheadStatistics): ToolDetail {
  return {
    key: "tool", name: "Tool", tool_ids: ["tool"], versions: [], amount: "8", job_count: 3,
    incomplete_job_count: 0, known_zero_job_count: 0, category: "ranked", by_status: [],
    contributors: { kind: "ranked", jobs: [], eligible_job_count: 3, excluded_job_count: 0, limit: 5 },
    statistics: { sample_count: 3, excluded_count: 0, mean: "2", median: "2", p95: "4", overhead },
    meta: {} as ToolDetail["meta"],
  };
}

const known: OverheadStatistics = { amount: "2", total_amount: "8", share: "0.25", sample_count: 2, excluded_count: 1 };

describe("historical machine startup costs", () => {
  it("reports the cost-weighted share and the cohort exclusions", () => {
    const wrapper = mount(ToolDetails, { props: { detail: detail(known), periodLabel: "this month" } });
    expect(wrapper.text()).toContain("Machine startup and shutdown accounted for 25% of $8.00");
    expect(wrapper.text()).toContain("2 completed jobs with complete costs and phase timings");
    expect(wrapper.text()).toContain("1 other job not included");
    wrapper.unmount();
  });

  it("does not present unavailable phase attribution as a zero share", () => {
    const wrapper = mount(ToolDetails, { props: {
      detail: detail({ amount: null, total_amount: null, share: null, sample_count: 0, excluded_count: 3 }),
      periodLabel: "this month",
    } });
    expect(wrapper.text()).not.toContain("Machine startup and shutdown accounted");
    wrapper.unmount();
  });

  it("distinguishes a recorded zero overhead from a sub-percent share", () => {
    const wrapper = mount(ToolDetails, { props: {
      detail: detail({ ...known, amount: "0", share: "0" }), periodLabel: "this month",
    } });
    expect(wrapper.text()).toContain("accounted for 0%");
    wrapper.unmount();
  });
});
