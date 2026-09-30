import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { nextTick } from "vue";

import { resetJobs, runDetail, runJob } from "../test/runDetail";
import DetailDrawer from "./DetailDrawer.vue";

const RUN = {
  id: "run-1", workflow_name: "Variant calling, one sample", run_status: "completed",
  started_at: "2026-09-02T10:00:00Z", duration_seconds: 5400, run_job_count: 3, run_total: "1.51",
  run_total_complete: true, amount: "1.51", run_unpriced_job_count: 0, reused_job_count: 0,
  jobs: [], cost_entities: [], children: [],
};

function mounted(props: Record<string, unknown> = {}) {
  const wrapper = mount(DetailDrawer, {
    attachTo: document.body,
    props: {
      kind: "runs", detail: RUN, loading: false, periodLabel: "this month", timezone: "UTC", backLabel: "", ...props,
    },
  });
  mountedDrawers.push(wrapper);
  return wrapper;
}

function cheap() {
  const repeated = [runJob("wig_to_bigWig", "0.004"), runJob("wig_to_bigWig", "0.004"), runJob("wig_to_bigWig", "0.004")];
  const server = { environment: "existing", capacities: ["existing"] };
  const jobs = [runJob("rna star", "0.81"), ...repeated, runJob("bwa", "0", server), runJob("fastqc", "0", server)];
  return { repeated, detail: runDetail(jobs) };
}

const mountedDrawers: Array<ReturnType<typeof mount>> = [];
beforeEach(resetJobs);
afterEach(() => {
  mountedDrawers.splice(0).forEach(wrapper => wrapper.unmount());
  document.body.innerHTML = "";
});

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

describe("DetailDrawer for a workflow run's cost and jobs", () => {
  it("reads in order: summary, cost breakdown, parts, jobs, then child workflows", () => {
    const wrapper = mounted({
      detail: { ...cheap().detail, children: [{ id: "c1", workflow_name: "Sub", run_job_count: 2, run_total: "0.10" }] },
    });
    const html = wrapper.html();
    const at = (text: string) => html.indexOf(text);
    expect(at("Run total")).toBeLessThan(at("Cost breakdown"));
    expect(at("Cost breakdown")).toBeLessThan(at("part-list"));
    expect(at("part-list")).toBeLessThan(at('id="run-jobs-heading"'));
    expect(at('id="run-jobs-heading"')).toBeLessThan(at("Child workflows"));
  });

  it("puts the whole-run total in the headline and never mixes in a period figure", () => {
    const wrapper = mounted({ detail: { ...cheap().detail, amount: "0.20", run_total: "0.822" } });
    expect(wrapper.find(".dialog-amount").text()).toContain("$0.82");
    expect(wrapper.text()).not.toContain("falls inside");
  });

  it("keeps the incomplete-cost and reused-output notes", () => {
    const wrapper = mounted({
      detail: { ...cheap().detail, run_unpriced_job_count: 2, run_total_complete: false, reused_job_count: 1 },
    });
    expect(wrapper.text()).toContain("2 steps still need cost data, so this total is a subtotal.");
    expect(wrapper.text()).toContain("1 step reused earlier outputs and added no new compute.");
    expect(wrapper.text()).toContain("recorded so far");
  });

  it("shows the no-jobs message and no fingerprint for a run with none", () => {
    const wrapper = mounted({ detail: runDetail([]) });
    expect(wrapper.text()).toContain("No jobs are recorded for this run yet.");
    expect(wrapper.findAll(".fp-cell")).toHaveLength(0);
    expect(wrapper.find("#run-jobs-heading").exists()).toBe(false);
  });

  it("lists every distinct job below the fingerprint, whatever part is open", () => {
    const { detail, repeated } = cheap();
    const key = `tool:tools/wig_to_bigWig|1.0|dedicated`;
    const wrapper = mounted({ detail, part: key });
    const all = wrapper.findAll(".job-groups .job-row");
    expect(all).toHaveLength(detail.jobs.length);
    expect(wrapper.findAll("#part-detail .job-row")).toHaveLength(repeated.length);
  });

  it("groups jobs by where they ran and gives the server's jobs no cost column", () => {
    const wrapper = mounted({ detail: cheap().detail });
    const groups = wrapper.findAll(".job-group");
    expect(groups.map(group => group.find("h4").text())).toEqual([
      "Dedicated cloud compute · 4 jobs", "Your Galaxy server · 2 jobs",
    ]);
    expect(groups[1].findAll(".job-cost")).toHaveLength(0);
    expect(groups[0].findAll(".job-cost")).toHaveLength(4);
  });

  it("relays the part chosen, and a job pressed with the place the reader was", async () => {
    const { detail } = cheap();
    const wrapper = mounted({ detail });
    await wrapper.find("button[data-part]").trigger("click");
    expect(wrapper.emitted("select")![0][1]).toBe("");
    const row = wrapper.find(".job-groups .job-row");
    await row.trigger("click");
    const [kind, id, scrollTop] = wrapper.emitted("open")![0] as [string, string, number];
    expect(kind).toBe("tool-runs");
    expect(id).toBe(row.attributes("data-job-id"));
    expect(scrollTop).toBe(0);
  });

  it("opens a child workflow the same way", async () => {
    const wrapper = mounted({
      detail: { ...cheap().detail, children: [{ id: "c1", workflow_name: "Sub", run_job_count: 2, run_total: "0.10" }] },
    });
    await wrapper.find("[data-run-id='c1']").trigger("click");
    expect(wrapper.emitted("open")![0].slice(0, 2)).toEqual(["runs", "c1"]);
  });

  it("counts steps whose job the viewer cannot see without describing them", () => {
    const wrapper = mounted({ detail: { ...cheap().detail, unavailable_step_count: 2 } });
    expect(wrapper.text()).toContain("2 steps of this run have no job you can see.");
  });

  it("puts a returning reader back on the row that opened the other page", async () => {
    const { detail } = cheap();
    const wrapper = mounted({ detail: null });
    const target = detail.jobs[2];
    await wrapper.setProps({ detail: detail as unknown as Record<string, unknown>, restore: { scrollTop: 0, focusId: target.id } });
    await flushPromises();
    expect(document.activeElement?.getAttribute("data-job-id")).toBe(target.id);
    expect(wrapper.emitted("restored")).toHaveLength(1);
  });

  it("falls back to the title when the row it left is not there", async () => {
    const wrapper = mounted({ detail: null });
    await wrapper.setProps({ detail: cheap().detail as unknown as Record<string, unknown>, restore: { scrollTop: 0, focusId: "gone" } });
    await flushPromises();
    expect(document.activeElement).toBe(wrapper.find("h2").element);
  });

  it("clears a tooltip on the first Escape and closes on the second", async () => {
    const wrapper = mounted({ detail: cheap().detail });
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    expect(wrapper.find(".fp-tip").exists()).toBe(true);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }));
    await flushPromises();
    expect(wrapper.find(".fp-tip").exists()).toBe(false);
    expect(wrapper.emitted("close")).toBeUndefined();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(wrapper.emitted("close")).toHaveLength(1);
  });

  it("does not take a press on its own tooltip for an outside press", async () => {
    const wrapper = mounted({ detail: cheap().detail });
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    wrapper.find(".fp-tip").element.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    expect(wrapper.emitted("dismiss")).toBeUndefined();
  });

  it("offers to try again when the details could not be loaded", async () => {
    const wrapper = mounted({ detail: null, error: "Network down" });
    expect(wrapper.find(".drawer").attributes("data-open")).toBe("true");
    expect(wrapper.find("[role='alert']").text()).toContain("Network down");
    await wrapper.find("[role='alert'] button").trigger("click");
    expect(wrapper.emitted("retry")).toHaveLength(1);
  });

  it("leaves the headline and the jobs when the breakdown cannot be trusted", () => {
    const { detail } = cheap();
    detail.cost_breakdown = { ...detail.cost_breakdown, status: "unavailable", reason: "The parts do not add up to the run total." };
    const wrapper = mounted({ detail });
    expect(wrapper.text()).toContain("Cost breakdown unavailable");
    expect(wrapper.find(".dialog-amount").exists()).toBe(true);
    expect(wrapper.findAll(".job-groups .job-row")).toHaveLength(detail.jobs.length);
  });
});
