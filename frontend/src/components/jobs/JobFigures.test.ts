import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { Summary } from "../../api";
import JobFigures from "./JobFigures.vue";

const SUMMARY = {
  amount: "12.50", job_count: 9, unpriced_job_count: 0, in_progress_job_count: 0, unrecorded_job_count: 0,
} as unknown as Summary;

function figures(summary: Partial<Summary> = {}) {
  return mount(JobFigures, {
    props: {
      summary: { ...SUMMARY, ...summary } as Summary,
      totals: null, periodText: "Sep 28, 2026 – Oct 4, 2026 · UTC", toolName: "", narrowed: false,
    },
  });
}

describe("JobFigures", () => {
  it("names cost still to come apart from cost that was never recorded", () => {
    const note = figures({ unpriced_job_count: 4, in_progress_job_count: 1, unrecorded_job_count: 3 })
      .find(".figure-note").text();
    expect(note).toBe(
      "Compute only · USD · 1 job still in progress · 3 jobs whose cost was not recorded are not included",
    );
    expect(note).not.toContain("need cost data");
  });

  it("says nothing about missing cost when none is missing", () => {
    expect(figures().find(".figure-note").text()).toBe("Compute only · USD");
  });
});
