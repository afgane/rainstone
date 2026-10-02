import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ServerActivity } from "../api";
import ServerActivityPlot from "./ServerActivityPlot.vue";

const activity: ServerActivity = {
  from: "2026-10-01T21:25:00Z", to: "2026-10-01T23:12:00Z", kind: "dots", job_count: 2,
  intervals: [
    { job_id: "local", source_id: "1", from: "2026-10-01T21:38:41Z", to: "2026-10-01T21:39:07Z", running: false },
    { job_id: "k8s", source_id: "2", from: "2026-10-01T21:38:41Z", to: "2026-10-01T23:12:00Z", running: true },
  ],
  steps: [
    { from: "2026-10-01T21:25:00Z", to: "2026-10-01T21:38:41Z", count: 0 },
    { from: "2026-10-01T21:38:41Z", to: "2026-10-01T21:39:07Z", count: 2 },
    { from: "2026-10-01T21:39:07Z", to: "2026-10-01T23:12:00Z", count: 1 },
  ],
};
function plot(value: ServerActivity | null = activity) {
  return mount(ServerActivityPlot, { props: {
    activity: value, startedAt: activity.from, recordedThrough: activity.to, timezone: "UTC", duration: "1 h 47 min",
  } });
}

describe("server job activity", () => {
  it("uses one style for jobs, with true duration lengths and an exact text alternative", async () => {
    const wrapper = plot();
    const marks = wrapper.findAll(".activity-dot");
    expect(marks).toHaveLength(2);
    expect(Number(marks[1].attributes("width"))).toBeGreaterThan(Number(marks[0].attributes("width")));
    expect(marks[0].attributes("y")).not.toBe(marks[1].attributes("y"));
    expect(wrapper.find(".activity-caption").text()).toBe("2 recorded jobs");
    expect(wrapper.find("svg").attributes("aria-hidden")).toBe("true");
    expect(wrapper.find("summary").text()).toBe("Show job activity as a table");
    expect(wrapper.find("tbody").exists()).toBe(false);
    (wrapper.find("details").element as HTMLDetailsElement).open = true;
    await wrapper.find("details").trigger("toggle");
    expect(wrapper.find("tbody").text()).toContain("26 sec");
    expect(wrapper.find("tbody").text()).toContain("Through the last observation");
    expect(wrapper.text()).not.toContain("Idle");
  });

  it("switches long sessions to exact concurrent-job steps", async () => {
    const wrapper = plot({ ...activity, kind: "steps", intervals: [] });
    expect(wrapper.findAll(".activity-dot")).toHaveLength(0);
    expect(wrapper.find(".activity-step").attributes("points")).toBeTruthy();
    expect(wrapper.find(".activity-caption").text()).toContain("Jobs running · peak 2");
    (wrapper.find("details").element as HTMLDetailsElement).open = true;
    await wrapper.find("details").trigger("toggle");
    expect(wrapper.findAll("tbody tr")).toHaveLength(2);
  });

  it("uses steps when overlapping marks would require more than ten rows", () => {
    const crowded = { ...activity, intervals: Array.from({ length: 11 }, (_, index) => ({
      ...activity.intervals[1], job_id: `${index}`, source_id: `${index}`,
    })), job_count: 11 };
    expect(plot(crowded).attributes("data-kind")).toBe("steps");
  });

  it("keeps the interval when activity cannot be plotted, without inventing a peak", () => {
    const missing = plot(null);
    expect(missing.find(".activity-dot").exists()).toBe(false);
    expect(missing.find(".session-timeline").text()).toContain("Recorded through");
    expect(missing.find("details").exists()).toBe(false);
    const empty = plot({ ...activity, kind: "steps", intervals: [], job_count: 0,
      steps: [{ from: activity.from, to: activity.to, count: 0 }] });
    expect(empty.find(".activity-caption").text()).toContain("peak 0");
    const dense = plot({ ...activity, kind: "hidden", intervals: [], steps: [] });
    expect(dense.find(".activity-step").exists()).toBe(false);
    expect(dense.text()).toContain("not plotted at this scale");
  });
});
