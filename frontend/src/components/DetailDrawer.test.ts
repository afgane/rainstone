import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import DetailDrawer from "./DetailDrawer.vue";

const RUN = {
  id: "run-1", workflow_name: "Variant calling, one sample", run_status: "completed",
  started_at: "2026-09-02T10:00:00Z", duration_seconds: 5400, run_job_count: 3, run_total: "1.51",
  run_total_complete: true, amount: "1.51", run_unpriced_job_count: 0, reused_job_count: 0,
  steps: [], children: [],
};

function mounted(props: Record<string, unknown> = {}) {
  return mount(DetailDrawer, {
    attachTo: document.body,
    props: {
      kind: "runs", detail: RUN, loading: false, periodLabel: "this month", timezone: "UTC", backLabel: "", ...props,
    },
  });
}

afterEach(() => { document.body.innerHTML = ""; });

describe("DetailDrawer", () => {
  it("reads a run's facts in order, with no version, history or period row", () => {
    const wrapper = mounted();
    const terms = wrapper.findAll("dt").map(term => term.text());
    expect(terms).toEqual(["Status", "Started", "Duration", "Workflow jobs"]);
    expect(wrapper.text()).toContain("$1.51");
    expect(wrapper.text()).toContain("1 h 30 min");
    for (const absent of ["Version", "version", "History", "history", "Cost in the selected period", "falls inside"]) {
      expect(wrapper.text()).not.toContain(absent);
    }
  });

  it("calls a running run's total its cost so far", () => {
    const wrapper = mounted({ detail: { ...RUN, run_status: "running", duration_seconds: 600 } });
    expect(wrapper.text()).toContain("Cost so far");
    expect(wrapper.text()).toContain("10 min so far");
  });

  it("is a non-modal dialog that is inert and hidden when closed", () => {
    const closed = mounted({ detail: null });
    const drawer = closed.find(".drawer");
    expect(drawer.attributes("aria-modal")).toBe("false");
    expect(drawer.attributes("data-open")).toBe("false");
    expect(drawer.attributes("aria-hidden")).toBe("true");
    expect(drawer.attributes("inert")).toBeDefined();
    const open = mounted();
    expect(open.find(".drawer").attributes("data-open")).toBe("true");
    expect(open.find(".drawer").attributes("inert")).toBeUndefined();
  });

  it("moves focus to the title when it opens, and again when it swaps", async () => {
    const wrapper = mounted({ detail: null });
    await wrapper.setProps({ detail: RUN });
    await nextTick();
    expect(document.activeElement).toBe(wrapper.find("h2").element);
    (document.activeElement as HTMLElement).blur();
    await wrapper.setProps({ detail: { ...RUN, id: "run-2", workflow_name: "Genome assembly" } });
    await nextTick();
    expect(document.activeElement?.textContent).toBe("Genome assembly");
  });

  it("dismisses on a press anywhere outside it, without asking for focus back", async () => {
    const wrapper = mounted();
    const masthead = document.createElement("header");
    document.body.append(masthead);
    masthead.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    document.body.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    await flushPromises();
    expect(wrapper.emitted("dismiss")).toHaveLength(2);
    expect(wrapper.emitted("close")).toBeUndefined();
  });

  it("does not dismiss on a press inside itself", async () => {
    const wrapper = mounted();
    wrapper.find("h2").element.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    expect(wrapper.emitted("dismiss")).toBeUndefined();
  });

  it("leaves a press on another run's trigger to that trigger, so it can swap", () => {
    const wrapper = mounted();
    const trigger = document.createElement("button");
    trigger.setAttribute("data-detail-trigger", "");
    const inner = document.createElement("span");
    trigger.append(inner);
    document.body.append(trigger);
    inner.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    expect(wrapper.emitted("dismiss")).toBeUndefined();
  });

  it("closes on Escape and on the close button, which return focus to the opener", async () => {
    const wrapper = mounted();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await wrapper.find("button.icon-close").trigger("click");
    expect(wrapper.emitted("close")).toHaveLength(2);
  });

  it("ignores Escape while it is closed", () => {
    const wrapper = mounted({ detail: null });
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(wrapper.emitted("close")).toBeUndefined();
  });

  it("keeps a job's content as it was", () => {
    const wrapper = mounted({
      kind: "tool-runs", periodLabel: "the selected dates",
      detail: {
        tool_name: "goseq", full_job_amount: "0.10", interval_amount: "0.04", state: "ok",
        created_at: "2026-09-19T13:28:00Z", quality: "complete", reason: "", capacities: ["dedicated"],
        resources: [], attempts: [], tool_id: "t", source_id: "9", revision_id: "r",
      },
    });
    expect(wrapper.text()).toContain("falls inside the selected dates");
    expect(wrapper.text()).toContain("Where it ran");
  });
});

describe("DetailDrawer back button", () => {
  it("is absent when the drawer was opened from outside", () => {
    expect(mounted().find(".drawer-back").exists()).toBe(false);
  });

  it("leads back to the run a job was opened from", async () => {
    const wrapper = mounted({ backLabel: "Back to workflow run" });
    const back = wrapper.find(".drawer-back");
    expect(back.text()).toContain("Back to workflow run");
    await back.trigger("click");
    expect(wrapper.emitted("back")).toHaveLength(1);
  });
});
