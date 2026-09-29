import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

const META = {
  basis: "additional", currency: "USD", revision_id: "rev-1", as_of: "2026-09-29T12:00:00Z",
  calculation_version: "v", priced_subtotal: "0", observation_window: {
    from: null, to: null, timezone: "UTC", semantics: "[from, to)", mode: "accrued",
  },
  coverage: { jobs: 0, priced: 0, incomplete: 0, known_zero: 0, temporally_unattributed: 0 }, undated: null,
};

const WORKFLOWS = [
  { key: "alpha", name: "Alpha workflow", run_count: 3 },
  { key: "beta", name: "Beta workflow", run_count: 1 },
];

/** What the run endpoints answer for a workflow filter: every part describes the same runs. */
function answer(path: string, workflow: string) {
  const beta = workflow === "beta";
  const name = beta ? "Beta workflow" : "Alpha workflow";
  const amount = beta ? "5.00" : "15.00";
  const run = {
    id: beta ? "b1" : "a1", source_id: "s", workflow_id: "w", workflow_key: workflow || "alpha",
    workflow_name: name, workflow_version: null, parent_id: null, state: "scheduled",
    run_status: "completed", started_at: "2026-09-02T10:00:00Z", finished_at: "2026-09-02T11:00:00Z",
    duration_seconds: 3600, job_count: 1, run_job_count: 1, amount, run_total: amount,
    run_total_complete: true, currency: "USD", unpriced_job_count: 0, run_unpriced_job_count: 0,
    reused_job_count: 0, timing_unavailable: false, chart_amount: amount, shared_job_count: 0,
  };
  if (path.includes("/invocations/breakdown")) {
    const group = (key: string, label: string, value: string) => ({
      key, name: label, run_count: 1, by_status: { completed: 1 }, amount: value,
      incomplete_run_count: 0,
      runs: [{ ...run, id: `${key}-run`, status: "completed", amount: value, chart_amount: value }],
      remainder: { count: 0, amount: "0", failed: 0, running: 0, boundary: null },
      whole_run_range: { minimum: value, maximum: value, included_run_count: 1, excluded_run_count: 0 },
    });
    // With a workflow chosen the request is for that workflow alone (the strip);
    // without one it is for every workflow (the chart).
    return {
      groups: workflow
        ? [group(workflow, name, amount)]
        : [group("alpha", "Alpha workflow", "15.00"), group("beta", "Beta workflow", "5.00")],
      meta: META,
    };
  }
  return {
    items: [run], total: 1, limit: 20, offset: 0,
    totals: {
      amount, incomplete_run_count: 0, shared_job_count: 0, run_count: 1,
      by_status: { completed: 1 }, workflow_count: 1, unfiltered_run_count: 4,
    },
    filter_options: { by_status: { completed: 4 }, workflows: WORKFLOWS },
    meta: META,
  };
}

interface Pending { workflow: string; resolve: () => void }

function stubFetch(hold: Set<string> = new Set()) {
  const pending: Pending[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const workflow = query.get("workflow_key") ?? "";
    const path = url.split("?")[0];
    let body: unknown = {};
    if (path.endsWith("/summary")) body = { ...META, amount: "0", job_count: 0, unpriced_job_count: 0, demo: false, imported_snapshot: null, can_view_infrastructure: false, undated: null };
    else if (path.endsWith("/freshness")) body = { overall_status: "healthy", sources: [], observation_gaps: [] };
    else if (path.endsWith("/me")) body = { source_id: "a", label: "A", is_admin: true, auth_mode: "development", attribution: "", capabilities: { infrastructure: false, users: false } };
    else if (path.includes("/invocations")) body = answer(path, workflow);
    const respond = () => new Response(JSON.stringify(body), { status: 200 });
    if (!hold.has(workflow) || !path.includes("/invocations")) return Promise.resolve(respond());
    return new Promise<Response>(resolve => pending.push({ workflow, resolve: () => resolve(respond()) }));
  }));
  return pending;
}

async function mountRuns() {
  history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29");
  const wrapper = mount(App, { attachTo: document.body });
  await flushPromises();
  return wrapper;
}

const figure = (wrapper: ReturnType<typeof mount>) => wrapper.find(".figure.featured .figure-amount").text();
const blocks = (wrapper: ReturnType<typeof mount>) => wrapper.findAll(".wf-name").map(node => node.text()).join("|");
const strip = (wrapper: ReturnType<typeof mount>) => wrapper.find(".zoom-label").text();
const rowName = (wrapper: ReturnType<typeof mount>) => wrapper.find(".run-card strong").text();

beforeEach(() => vi.useRealTimers());
afterEach(() => { document.body.innerHTML = ""; vi.unstubAllGlobals(); });

describe("the Workflow runs page", () => {
  it("draws the figures, the chart and the list from one load", async () => {
    stubFetch();
    const wrapper = await mountRuns();
    expect(figure(wrapper)).toContain("$15.00");
    expect(blocks(wrapper)).toBe("Alpha workflow|Beta workflow");
    expect(rowName(wrapper)).toBe("Alpha workflow");
  });

  it("keeps the old picture until the new figures, chart and list arrive together", async () => {
    const pending = stubFetch(new Set(["beta"]));
    const wrapper = await mountRuns();
    await wrapper.find(".page-filters select").setValue("beta");
    await flushPromises();
    // The answer for Beta is still on its way: nothing has half-changed.
    expect(wrapper.find(".refetching").exists()).toBe(true);
    expect(figure(wrapper)).toContain("$15.00");
    expect(strip(wrapper)).toContain("Every run, at its own scale");
    expect(rowName(wrapper)).toBe("Alpha workflow");

    pending.forEach(item => item.resolve());
    await flushPromises();
    expect(wrapper.find(".refetching").exists()).toBe(false);
    expect(figure(wrapper)).toContain("$5.00");
    expect(strip(wrapper)).toContain("Beta workflow");
    expect(rowName(wrapper)).toBe("Beta workflow");
    // Choosing a workflow leaves the others on the chart, the chosen one marked.
    expect(blocks(wrapper)).toBe("Alpha workflow|Beta workflow");
    expect(wrapper.findAll(".wf-label").map(node => node.attributes("aria-pressed"))).toEqual(["false", "true"]);
  });

  it("drops an older answer that arrives after a newer one", async () => {
    const pending = stubFetch(new Set(["alpha", "beta"]));
    // The first load is held too, so release it before choosing anything.
    history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29");
    const wrapper = mount(App, { attachTo: document.body });
    await flushPromises();
    pending.splice(0).forEach(item => item.resolve());
    await flushPromises();

    const select = wrapper.find(".page-filters select");
    await select.setValue("alpha");
    await flushPromises();
    const alpha = pending.splice(0);
    await select.setValue("beta");
    await flushPromises();
    const beta = pending.splice(0);

    beta.forEach(item => item.resolve());
    await flushPromises();
    alpha.forEach(item => item.resolve());
    await flushPromises();
    expect(figure(wrapper)).toContain("$5.00");
    expect(strip(wrapper)).toContain("Beta workflow");
  });

  it("says how many of the runs the list shows", async () => {
    stubFetch();
    const wrapper = await mountRuns();
    expect(wrapper.text()).toContain("Showing 1 of 1");
  });
});
