import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";
import { job } from "./test/jobDetail";
import { resetJobs, runDetail, runJob } from "./test/runDetail";

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

// The base rule reads a type's parameter name as an unused variable.
// eslint-disable-next-line no-unused-vars
type Custom = (path: string) => Response | Promise<Response> | undefined;

function stubFetch(hold: Set<string> = new Set(), custom?: Custom) {
  const pending: Pending[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const query = new URLSearchParams(url.split("?")[1] ?? "");
    const workflow = query.get("workflow_key") ?? "";
    const path = url.split("?")[0];
    const special = custom?.(path);
    if (special) return Promise.resolve(special);
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

// Every mounted app listens for the browser's history events, so none may outlive its test.
const apps: Array<ReturnType<typeof mount>> = [];

async function mountRuns() {
  history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29");
  const wrapper = mount(App, { attachTo: document.body });
  apps.push(wrapper);
  await flushPromises();
  return wrapper;
}

const figure = (wrapper: ReturnType<typeof mount>) => wrapper.find(".figure.featured .figure-amount").text();
const blocks = (wrapper: ReturnType<typeof mount>) => wrapper.findAll(".wf-name").map(node => node.text()).join("|");
const strip = (wrapper: ReturnType<typeof mount>) => wrapper.find(".zoom-label").text();
const rowName = (wrapper: ReturnType<typeof mount>) => wrapper.find(".run-card strong").text();

beforeEach(() => vi.useRealTimers());
afterEach(() => {
  apps.splice(0).forEach(wrapper => wrapper.unmount());
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

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
    apps.push(wrapper);
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


/* The run drawer: what is open in it is part of the address. */
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** One run per id, so every answer for it names the same jobs. */
const runs = new Map<string, ReturnType<typeof runDetail>>();
function drawerRun(id: string, name: string) {
  const known = runs.get(id);
  if (known) return known;
  const repeated = [runJob("wig_to_bigWig", "0.4"), runJob("wig_to_bigWig", "0.4"), runJob("wig_to_bigWig", "0.4")];
  const made = { ...runDetail([runJob("rna star", "98.8"), ...repeated]), id, workflow_name: name };
  runs.set(id, made);
  return made;
}
const WIG = "tool:tools/wig_to_bigWig|1.0|dedicated";

function jobDetail(id: string) {
  return job({ id, tool_name: "wig_to_bigWig", full_job_amount: "0.4", interval_amount: "0.4" });
}

function stubDrawer(details: Record<string, () => Response | Promise<Response>>) {
  stubFetch(new Set(), path => {
    const detail = /\/invocations\/([^/]+)$/.exec(path)?.[1];
    if (detail && detail !== "breakdown" && detail !== "timeline" && details[detail]) return details[detail]();
    const job = /\/jobs\/([^/]+)$/.exec(path)?.[1];
    return job ? json(jobDetail(job)) : undefined;
  });
}

async function openRun(search: string) {
  history.replaceState({}, "", `/?view=runs&period=custom&from=2026-09-01&to=2026-09-29${search}`);
  const wrapper = mount(App, { attachTo: document.body });
  apps.push(wrapper);
  await flushPromises();
  return wrapper;
}

describe("the run drawer's address", () => {
  beforeEach(() => { runs.clear(); resetJobs(); });

  it("opens the part named in the address, with its jobs", async () => {
    stubDrawer({ a1: () => json(drawerRun("a1", "Alpha workflow")) });
    const wrapper = await openRun(`&detail_kind=runs&detail_id=a1&detail_part=${encodeURIComponent(WIG)}`);
    const pressed = wrapper.findAll("button[data-part][aria-pressed='true']");
    expect(pressed).toHaveLength(1);
    expect(wrapper.findAll("#part-detail .job-row")).toHaveLength(3);
  });

  it("writes a chosen part into the address without adding a history entry", async () => {
    stubDrawer({ a1: () => json(drawerRun("a1", "Alpha workflow")) });
    const wrapper = await openRun("&detail_kind=runs&detail_id=a1");
    const before = history.length;
    await wrapper.find(`button[data-part="${WIG}"]`).trigger("click");
    expect(new URLSearchParams(location.search).get("detail_part")).toBe(WIG);
    expect(history.length).toBe(before);
    await wrapper.find(`button[data-part="${WIG}"]`).trigger("click");
    expect(new URLSearchParams(location.search).has("detail_part")).toBe(false);
  });

  it("clears a part the address names but the run no longer has, and says so", async () => {
    stubDrawer({ a1: () => json(drawerRun("a1", "Alpha workflow")) });
    const wrapper = await openRun("&detail_kind=runs&detail_id=a1&detail_part=tool:gone");
    expect(wrapper.find("#part-detail").exists()).toBe(false);
    expect(new URLSearchParams(location.search).has("detail_part")).toBe(false);
    expect(wrapper.find(".cost-breakdown [role='status']").text()).toBe("The part you had selected is no longer available.");
  });

  it("returns from a job to the same part, the same place and the row that opened it", async () => {
    stubDrawer({ a1: () => json(drawerRun("a1", "Alpha workflow")) });
    const wrapper = await openRun(`&detail_kind=runs&detail_id=a1&detail_part=${encodeURIComponent(WIG)}`);
    const row = wrapper.findAll("#part-detail .job-row")[1];
    const jobId = row.attributes("data-job-id")!;
    await row.trigger("click");
    await flushPromises();
    expect(wrapper.find(".drawer-back").text()).toContain("Back to workflow run");
    expect(wrapper.find("#detail-title").text()).toBe("wig_to_bigWig");
    expect(new URLSearchParams(location.search).get("detail_id")).toBe(jobId);
    expect(new URLSearchParams(location.search).has("detail_part")).toBe(false);

    await wrapper.find(".drawer-back").trigger("click");
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Alpha workflow");
    expect(wrapper.findAll("button[data-part][aria-pressed='true']")).toHaveLength(1);
    expect(new URLSearchParams(location.search).get("detail_part")).toBe(WIG);
    const focused = document.activeElement as HTMLElement;
    expect(focused.getAttribute("data-job-id")).toBe(jobId);
    expect(focused.closest("#part-detail")).not.toBeNull();
  });

  it("does not carry a selection from one run to another", async () => {
    stubDrawer({
      a1: () => json(drawerRun("a1", "Alpha workflow")),
      b1: () => json(drawerRun("b1", "Beta workflow")),
    });
    const wrapper = await openRun(`&detail_kind=runs&detail_id=a1&detail_part=${encodeURIComponent(WIG)}`);
    expect(wrapper.find("#part-detail").exists()).toBe(true);
    await wrapper.find(".run-card").trigger("click");
    await flushPromises();
    // The list's first row is Alpha's own trigger, so a second press closes it; open Beta directly.
    history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await flushPromises();
    history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29&detail_kind=runs&detail_id=b1");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Beta workflow");
    expect(wrapper.find("#part-detail").exists()).toBe(false);
  });

  it("drops an older run's answer that arrives after a newer one", async () => {
    let releaseFirst: () => void = () => {};
    const first = new Promise<Response>(resolve => { releaseFirst = () => resolve(json(drawerRun("a1", "Alpha workflow"))); });
    stubDrawer({ a1: () => first, b1: () => json(drawerRun("b1", "Beta workflow")) });
    const wrapper = await openRun("&detail_kind=runs&detail_id=a1");
    history.replaceState({}, "", "/?view=runs&period=custom&from=2026-09-01&to=2026-09-29&detail_kind=runs&detail_id=b1");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Beta workflow");
    releaseFirst();
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Beta workflow");
  });

  it("offers to try again when a run's details fail to load, and recovers", async () => {
    let calls = 0;
    stubDrawer({
      a1: () => (calls++ === 0 ? json({ detail: "Bad Gateway" }, 502) : json(drawerRun("a1", "Alpha workflow"))),
    });
    const wrapper = await openRun("&detail_kind=runs&detail_id=a1");
    expect(wrapper.find(".drawer [role='alert']").text()).toContain("These details could not be loaded");
    await wrapper.find(".drawer [role='alert'] button").trigger("click");
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Alpha workflow");
    expect(wrapper.find(".drawer [role='alert']").exists()).toBe(false);
  });
});

describe("the Daily cost page", () => {
  it("says a day with no known cost is not available, never $0.00", async () => {
    stubFetch(new Set(), path => (path.endsWith("/daily") ? json({
      items: [
        { date: "2026-09-02", amount: null, currency: "USD", job_count: 2, incomplete_count: 2, provisional: false },
        { date: "2026-09-03", amount: "1.25", currency: "USD", job_count: 1, incomplete_count: 0, provisional: false },
      ],
    }) : undefined));
    history.replaceState({}, "", "/?view=daily&period=custom&from=2026-09-01&to=2026-09-29");
    const wrapper = mount(App, { attachTo: document.body });
    apps.push(wrapper);
    await flushPromises();
    const rows = wrapper.findAll("tbody tr").map(row => row.text());
    expect(rows[0]).toContain("Not available");
    expect(rows[0]).toContain("2 still need cost data");
    expect(rows[0]).not.toContain("$0.00");
    expect(rows[1]).toContain("$1.25");
  });
});

describe("newer figures", () => {
  /** What the server holds now; a test changes it to stand for a later calculation. */
  const latest = { revision: "rev-1", amount: "1.00", jobs: 1 };

  function stubLatest() {
    Object.assign(latest, { revision: "rev-1", amount: "1.00", jobs: 1 });
    return stubFetch(new Set(), path => {
      if (path.endsWith("/freshness")) {
        return json({ overall_status: "healthy", sources: [], observation_gaps: [], revision_id: latest.revision });
      }
      if (path.endsWith("/summary")) {
        return json({
          ...META, revision_id: latest.revision, amount: latest.amount, job_count: latest.jobs,
          unpriced_job_count: 0, demo: false, imported_snapshot: null, can_view_infrastructure: false,
        });
      }
      if (path.endsWith("/daily")) return json({ items: [], meta: META });
      return undefined;
    });
  }

  async function mountDaily() {
    history.replaceState({}, "", "/?view=daily&period=custom&from=2026-09-01&to=2026-09-29");
    const wrapper = mount(App, { attachTo: document.body });
    apps.push(wrapper);
    await flushPromises();
    return wrapper;
  }

  const notice = (wrapper: ReturnType<typeof mount>) => wrapper.find(".newer-figures").text();
  const summaries = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/summary")).length;

  function setVisibility(value: DocumentVisibilityState) {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => value });
    document.dispatchEvent(new Event("visibilitychange"));
  }

  afterEach(() => { Reflect.deleteProperty(document, "visibilityState"); });

  it("offers newer figures without replacing the ones being read", async () => {
    vi.useFakeTimers({ toFake: ["setInterval"] });
    stubLatest();
    const wrapper = await mountDaily();
    Object.assign(latest, { revision: "rev-2", amount: "2.00" });
    vi.advanceTimersByTime(60_000);
    await flushPromises();
    expect(notice(wrapper)).toContain("Newer figures available");
    expect(wrapper.find(".snapshot details .mono").text()).toContain("rev-1");
    const before = summaries();
    await wrapper.find(".newer-figures button").trigger("click");
    await flushPromises();
    expect(summaries()).toBe(before + 1);
    expect(notice(wrapper)).toBe("");
    expect(wrapper.find(".snapshot details .mono").text()).toContain("rev-2");
  });

  it("stays quiet when a newer revision would not change what the page shows", async () => {
    vi.useFakeTimers({ toFake: ["setInterval"] });
    stubLatest();
    const wrapper = await mountDaily();
    latest.revision = "rev-2";
    vi.advanceTimersByTime(60_000);
    await flushPromises();
    expect(notice(wrapper)).toBe("");
    // The same revision is not asked about twice.
    const before = summaries();
    vi.advanceTimersByTime(60_000);
    await flushPromises();
    expect(summaries()).toBe(before);
  });

  it("updates by itself when the page shows no jobs", async () => {
    vi.useFakeTimers({ toFake: ["setInterval"] });
    stubLatest();
    latest.jobs = 0;
    const wrapper = await mountDaily();
    Object.assign(latest, { revision: "rev-2", jobs: 3 });
    vi.advanceTimersByTime(60_000);
    await flushPromises();
    expect(notice(wrapper)).toBe("");
    expect(wrapper.find(".snapshot details .mono").text()).toContain("rev-2");
  });

  it("updates by itself when the reader comes back to the tab", async () => {
    stubLatest();
    const wrapper = await mountDaily();
    setVisibility("hidden");
    Object.assign(latest, { revision: "rev-2", amount: "2.00" });
    setVisibility("visible");
    await flushPromises();
    expect(notice(wrapper)).toBe("");
    expect(wrapper.find(".snapshot details .mono").text()).toContain("rev-2");
  });

  it("does not check while the tab is hidden", async () => {
    vi.useFakeTimers({ toFake: ["setInterval"] });
    stubLatest();
    await mountDaily();
    setVisibility("hidden");
    const before = vi.mocked(fetch).mock.calls.length;
    vi.advanceTimersByTime(180_000);
    await flushPromises();
    expect(vi.mocked(fetch).mock.calls.length).toBe(before);
  });
});


/* Overview: details open over the page, scoped exactly to what was pressed. */
const BLOCK = { from: "2026-09-02T00:00:00+00:00", to: "2026-09-03T00:00:00+00:00" };
const OVERVIEW_TIMELINE = {
  bucket: "day", axis: { from: "2026-09-01T00:00:00+00:00", to: "2026-09-04T00:00:00+00:00" },
  buckets: [{
    ...BLOCK, amount: "8", job_count: 13, run_count: 3, failed_job_count: 0, running_job_count: 0,
    incomplete_job_count: 0, provisional: false, pieces: [
      { key: "runs", kind: "runs", name: "Workflow runs", amount: "6", job_count: 9, run_count: 3, failed: 0, running: 0 },
      { key: "individual", kind: "individual", name: "Individual jobs", amount: "2", job_count: 4, run_count: 0, failed: 0, running: 0 },
    ],
  }],
  totals: { amount: "8", job_count: 13, by_outcome: {}, run_count: 3, workflow_count: 1, individual_job_count: 4 },
  label: "Cost accrued", unplaced: null, meta: META,
};
const RUN_ROW = {
  id: "r1", workflow_name: "Alpha workflow", run_status: "completed", started_at: "2026-09-02T10:00:00Z",
  amount: "6", job_count: 9, incomplete_job_count: 0, shared_job_count: 0, run_total: "9", run_total_complete: true,
};
function overviewDetail(query: URLSearchParams) {
  const kind = query.get("kind");
  const items = kind === "tools"
    ? [{ key: "tools/bwa", name: "bwa", tool_ids: ["tools/bwa"], versions: [], amount: "5", job_count: 4 }]
    : kind === "runs" ? [RUN_ROW] : [];
  return {
    scope: query.get("scope"), kind, from: query.get("window_from"), to: query.get("window_to"),
    amount: kind === "tools" ? "8" : "6", job_count: kind === "tools" ? 13 : 9, incomplete_job_count: 0,
    provisional: false, shared_job_count: 0, run_count: kind === "runs" ? 1 : null,
    tool_count: kind === "tools" ? 1 : null,
    ranking: query.get("scope") === "period" ? { eligible_count: 1, excluded_count: 0, zero_count: 0, limit: 5 } : null,
    items, total: items.length, limit: 20, offset: 0, meta: META,
  };
}

function stubOverview() {
  const asked: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    asked.push(url);
    const [path, search] = url.split("?");
    const query = new URLSearchParams(search ?? "");
    let body: unknown = {};
    if (path.endsWith("/summary")) {
      body = {
        ...META, amount: "8", job_count: 13, unpriced_job_count: 0, demo: false, imported_snapshot: null,
        can_view_infrastructure: false, current_launch: null, undated: null,
      };
    } else if (path.endsWith("/freshness")) body = { overall_status: "healthy", sources: [], observation_gaps: [] };
    else if (path.endsWith("/me")) body = { source_id: "a", label: "A", is_admin: true, auth_mode: "development", attribution: "", capabilities: { infrastructure: false, users: false } };
    else if (path.endsWith("/timeline")) body = OVERVIEW_TIMELINE;
    else if (path.endsWith("/overview/details")) body = overviewDetail(query);
    else if (path.endsWith("/invocations/r1")) body = { ...drawerRun("r1", "Alpha workflow"), amount: "6" };
    return Promise.resolve(json(body));
  }));
  return asked;
}

async function openOverviewPage(search = "") {
  history.replaceState({}, "", `/?view=overview&period=custom&from=2026-09-01&to=2026-09-03${search}`);
  const wrapper = mount(App, { attachTo: document.body });
  apps.push(wrapper);
  await flushPromises();
  return wrapper;
}

const asking = (asked: string[], path: string) => asked
  .filter(url => url.split("?")[0].endsWith(path))
  .map(url => new URLSearchParams(url.split("?")[1]));

describe("Overview's details", () => {
  beforeEach(() => { runs.clear(); resetJobs(); });

  it("loads the chart alone; nothing ranks tools or runs until asked", async () => {
    const asked = stubOverview();
    await openOverviewPage();
    expect(asked.some(url => url.includes("/tools") || url.includes("/invocations"))).toBe(false);
  });

  it("opens a block's exact interval and category over the page, pinned to its revision", async () => {
    const asked = stubOverview();
    const wrapper = await openOverviewPage();
    const figures = wrapper.find(".cost-cards").html();
    await wrapper.find('.blk[data-kind="runs"]').trigger("click");
    await flushPromises();
    const [query] = asking(asked, "/overview/details");
    expect(query.get("scope")).toBe("interval");
    expect(query.get("kind")).toBe("runs");
    expect(query.get("window_from")).toBe("2026-09-02T00:00:00.000Z");
    expect(query.get("window_to")).toBe("2026-09-03T00:00:00.000Z");
    expect(query.get("revision")).toBe("rev-1");
    expect(query.has("workflow_key") || query.has("run_status")).toBe(false);
    expect(wrapper.find("#detail-title").text()).toBe("Workflow runs · Sep 2");
    expect(wrapper.find(".drawer").text()).toContain("Counted here");
    expect(new URLSearchParams(location.search).get("detail_kind")).toBe("overview");
    // The page under the drawer stays as it was.
    expect(new URLSearchParams(location.search).get("view")).toBe("overview");
    expect(wrapper.find(".cost-cards").html()).toBe(figures);
    expect(wrapper.find('.blk[data-kind="runs"]').attributes("aria-current")).toBe("true");
  });

  it("opens a run with its share of that interval, and goes back to the interval", async () => {
    const asked = stubOverview();
    const wrapper = await openOverviewPage();
    await wrapper.find('.blk[data-kind="runs"]').trigger("click");
    await flushPromises();
    await wrapper.find('.drawer [data-run-id="r1"]').trigger("click");
    await flushPromises();
    const [run] = asking(asked, "/invocations/r1");
    expect(run.get("from")).toBe("2026-09-02T00:00:00.000Z");
    expect(run.get("to")).toBe("2026-09-03T00:00:00.000Z");
    expect(wrapper.find(".drawer").text()).toContain("Inside Sep 2: $6.00 of this run's cost.");
    expect(wrapper.find(".drawer-back").text()).toContain("Back to selected day");
    expect(new URLSearchParams(location.search).get("detail_parent_kind")).toBe("overview");

    // A reload of that address keeps the way back.
    window.dispatchEvent(new PopStateEvent("popstate"));
    await flushPromises();
    expect(wrapper.find(".drawer-back").text()).toContain("Back to selected day");
    await wrapper.find(".drawer-back").trigger("click");
    await flushPromises();
    expect(wrapper.find("#detail-title").text()).toBe("Workflow runs · Sep 2");
    expect(document.activeElement?.getAttribute("data-run-id")).toBe("r1");
  });

  it("explores the whole period in two tabs that replace each other in place", async () => {
    const asked = stubOverview();
    const wrapper = await openOverviewPage();
    await wrapper.find(".chart-panel .panel-heading button").trigger("click");
    await flushPromises();
    expect(asking(asked, "/overview/details").at(-1)?.get("kind")).toBe("runs");
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe("Workflow runs");
    const before = history.length;
    await wrapper.find('[role="tab"][data-tab="tools"]').trigger("click");
    await flushPromises();
    const query = asking(asked, "/overview/details").at(-1)!;
    expect(query.get("scope")).toBe("period");
    expect(query.get("kind")).toBe("tools");
    expect(query.has("window_from")).toBe(false);
    expect(history.length).toBe(before);
    expect(wrapper.find('[role="tab"][aria-selected="true"]').text()).toBe("Tools");
    expect(wrapper.find(".drawer").text()).toContain("bwa");
    expect(document.activeElement?.getAttribute("data-tab")).toBe("tools");
  });

  it("closes the drawer when the report's dates change", async () => {
    stubOverview();
    const wrapper = await openOverviewPage();
    await wrapper.find('.blk[data-kind="individual"]').trigger("click");
    await flushPromises();
    expect(wrapper.find(".drawer").attributes("data-open")).toBe("true");
    await wrapper.findAll(".sidebar button").find(button => button.text() === "Last week")!.trigger("click");
    await flushPromises();
    expect(wrapper.find(".drawer").attributes("data-open")).toBe("false");
    expect(new URLSearchParams(location.search).has("detail_kind")).toBe(false);
  });

  it("dismisses an address that names no Overview scope, without an error", async () => {
    const asked = stubOverview();
    const wrapper = await openOverviewPage("&detail_kind=overview&detail_id=interval%7Cruns%7Cfortnight%7Cx%7Cy");
    expect(wrapper.find(".drawer").attributes("data-open")).toBe("false");
    expect(new URLSearchParams(location.search).has("detail_kind")).toBe(false);
    expect(asking(asked, "/overview/details")).toHaveLength(0);
  });
});
