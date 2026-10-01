import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import type { ScopedJob } from "../../api";
import ScopedJobRow from "./ScopedJobRow.vue";

function job(overrides: Partial<ScopedJob> = {}): ScopedJob {
  return {
    id: "j1", tool_name: "bwa mem", tool_id: "toolshed/bwa_mem/0.7", tool_version: "0.7", state: "ok",
    amount: "1.25", quality: "complete", capacities: ["dedicated"], created_at: "2026-09-02T00:00:00Z",
    duration_seconds: 125, duration_running: false, ...overrides,
  };
}

describe("a job in a tool or interval drawer", () => {
  it("names its scope in its label and shows no identifier", () => {
    const wrapper = mount(ScopedJobRow, { props: { job: job(), scope: "Cost during this day" } });
    const label = wrapper.find("button").attributes("aria-label")!;
    expect(label).toContain("Cost during this day: $1.25");
    expect(label).toContain("Ran for 2m 05s");
    expect(label).not.toMatch(/job \d|#/);
    expect(wrapper.find(".job-id").exists()).toBe(false);
    expect(wrapper.find(".job-cost").text()).toBe("$1.25");
  });

  it("says a missing duration was not recorded, and a server job added nothing", () => {
    const wrapper = mount(ScopedJobRow, {
      props: { job: job({ duration_seconds: null, quality: "known_zero", amount: "0" }), scope: "Cost in last week" },
    });
    expect(wrapper.find(".job-duration").text()).toBe("—");
    const label = wrapper.find("button").attributes("aria-label")!;
    expect(label).toContain("Duration not recorded");
    expect(label).toContain("$0 extra, used your Galaxy server");
    expect(wrapper.find(".job-cost").text()).toBe("$0 extra");
  });

  it("opens the job", async () => {
    const wrapper = mount(ScopedJobRow, { props: { job: job(), scope: "Cost" } });
    await wrapper.find("button").trigger("click");
    expect(wrapper.emitted("open")).toEqual([["j1"]]);
  });
});
