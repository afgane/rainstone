import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetJobs, runJob } from "../../test/runDetail";
import JobRow from "./JobRow.vue";

const mounted: Array<ReturnType<typeof mount>> = [];

function row(job = runJob("rna star", "0.81", { duration_seconds: 38 * 60 + 12 }), props = {}) {
  const wrapper = mount(JobRow, { attachTo: document.body, props: { job, showCost: true, ...props } });
  mounted.push(wrapper);
  return wrapper;
}

beforeEach(resetJobs);
afterEach(() => {
  mounted.splice(0).forEach(wrapper => wrapper.unmount());
  document.body.innerHTML = "";
});

describe("a job row", () => {
  it("is one button for the whole row, with name, state, duration and cost", () => {
    const wrapper = row();
    expect(wrapper.findAll("button")).toHaveLength(1);
    expect(wrapper.find("a").exists()).toBe(false);
    expect(wrapper.find(".job-title").text()).toBe("rna star");
    expect(wrapper.find(".job-duration").text()).toBe("38m 12s");
    expect(wrapper.find(".job-cost").text()).toBe("$0.81");
  });

  it("opens the job when the row is pressed", async () => {
    const job = runJob("rna star", "0.81");
    const wrapper = row(job);
    await wrapper.find("button").trigger("click");
    expect(wrapper.emitted("open")).toEqual([[job.id]]);
  });

  it("gives a complete name that does not depend on the truncated text", () => {
    const wrapper = row(runJob("a very long tool name that will be cut off on screen", "0.004"));
    const name = wrapper.find("button").attributes("aria-label")!;
    expect(name).toContain("a very long tool name that will be cut off on screen");
    expect(name).toContain("job 1001");
    expect(name).toContain("Completed");
    expect(name).toContain("14s");
    expect(name).toContain("Cost less than $0.01");
  });

  it("shortens a sub-cent cost on screen only", () => {
    const wrapper = row(runJob("wig", "0.004"));
    expect(wrapper.find(".job-cost").text()).toBe("<$0.01");
  });

  it("shows a dash and says so when a cost or duration is unknown", () => {
    const wrapper = row(runJob("wig", null, { duration_seconds: null, state: "queued" }));
    expect(wrapper.find(".job-cost").text()).toBe("—");
    expect(wrapper.find(".job-duration").text()).toBe("—");
    const name = wrapper.find("button").attributes("aria-label")!;
    expect(name).toContain("Cost not available");
    expect(name).toContain("Duration not available");
  });

  it("has no cost column, and never announces a zero, where the group states none", () => {
    const wrapper = row(runJob("bwa", "0"), { showCost: false });
    expect(wrapper.find(".job-cost").exists()).toBe(false);
    expect(wrapper.find("button").attributes("aria-label")).not.toContain("Cost");
    expect(wrapper.text()).not.toContain("$0.00");
  });

  it("says a running job's duration is elapsed so far", () => {
    const wrapper = row(runJob("bwa", "0.1", { state: "running", duration_running: true }));
    expect(wrapper.find("button").attributes("aria-label")).toContain("elapsed so far");
  });

  it("marks a job that reused an earlier output", () => {
    const wrapper = row(runJob("bwa", "0", { reused: true }));
    expect(wrapper.find(".job-flag").text()).toBe("reused");
    expect(wrapper.find("button").attributes("aria-label")).toContain("reused earlier output");
  });

  it("names the job by its identifier where equal names must be told apart", () => {
    expect(row(runJob("wig", "1"), { showId: true }).find(".job-id").text()).toBe("#1001");
    expect(row(runJob("wig", "1")).find(".job-id").exists()).toBe(false);
  });

  it("hides the state icon from assistive technology because the row's name says it", () => {
    const wrapper = row();
    expect(wrapper.find(".state-icon").attributes("aria-hidden")).toBe("true");
    expect(wrapper.find(".state-icon").attributes("data-kind")).toBe("completed");
  });

  it("shows its tooltip on hover and clears it on Escape before anything else hears it", async () => {
    const wrapper = row(runJob("wig", "1", { reused: true }));
    let heard = false;
    const spy = () => { heard = true; };
    document.addEventListener("keydown", spy);
    await wrapper.find("button").trigger("mouseenter");
    expect(wrapper.find(".job-tip").exists()).toBe(true);
    expect(wrapper.find(".job-tip").attributes("aria-hidden")).toBe("true");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".job-tip").exists()).toBe(false);
    expect(heard).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(heard).toBe(true);
    document.removeEventListener("keydown", spy);
  });

  it("is not an extra tab stop for its icon or tooltip", () => {
    const wrapper = row();
    expect(wrapper.findAll("[tabindex]")).toHaveLength(0);
  });
});
