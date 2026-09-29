import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  collectionCutoff, DEFAULT_RUN_CONTROLS, loadReport, NO_RUN_FILTERS, queryString, runQueryString,
  stateFromUrl, urlQuery, type ReportState,
} from "./api";

const SUMMARY = { revision_id: "rev-1", coverage: {}, amount: "0" };
const EMPTY_LIST = { items: [], total: 0, limit: 50, offset: 0, meta: {} };

function state(view: ReportState["view"] = "overview"): ReportState {
  return {
    view, period: "this-month", mode: "accrued",
    fromTime: "", toTime: "", timezone: "UTC", search: "", owner: "", toolId: "",
    toolVersion: "", invocationId: "", workflowId: "", state: "", runner: "",
    destination: "", capacity: "", quality: "", minCost: "", maxCost: "",
    sort: "created_at", direction: "desc", offset: 0,
    ...NO_RUN_FILTERS, ...DEFAULT_RUN_CONTROLS,
  };
}

const RUN_FIELDS: Partial<ReportState> = {
  workflowKey: "family-7", runStatus: "failed", focusFrom: "2026-09-02T00:00:00.000Z",
  focusTo: "2026-09-03T00:00:00.000Z", maxRunAmount: "1.204", boundaryRunId: "9f0c0000-0000-4000-8000-000000000001",
  runSort: "duration", runDirection: "asc", runChart: "time",
};

/** Records every request path, and answers whatever the endpoint needs. */
function respond(paths: string[], failFirstPinned = false) {
  let pinnedSeen = 0;
  return vi.fn(async (url: string) => {
    paths.push(url);
    const pinned = url.includes("revision=");
    if (pinned && failFirstPinned && ++pinnedSeen === 1) {
      return new Response(JSON.stringify({ detail: "This snapshot is stale" }), { status: 409 });
    }
    const body = url.includes("/summary")
      ? SUMMARY
      : url.includes("/freshness") || url.includes("/me")
        ? {}
        : EMPTY_LIST;
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

describe("loadReport", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("asks for the latest revision, then holds it for the rest of the view", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", respond(paths));

    await loadReport(state());

    const [summary, ...rest] = paths;
    // The first call must not pin: a pin carried in from anywhere else would
    // make a reload ask for a revision that has since been superseded.
    expect(summary).toContain("/summary");
    expect(summary).not.toContain("revision=");
    // Every other part of the view comes from the revision that answered.
    const scoped = rest.filter(path => path.includes("?"));
    expect(scoped.length).toBeGreaterThan(0);
    expect(scoped.every(path => path.includes("revision=rev-1"))).toBe(true);
  });

  it("repeats the load when a recalculation supersedes its snapshot", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", respond(paths, true));

    const result = await loadReport(state());

    // A collector recalculating mid-load is routine, so the reader sees the
    // new snapshot rather than a stale-snapshot error.
    expect(result.summary).toMatchObject({ revision_id: "rev-1" });
    expect(paths.filter(path => path.includes("/summary")).length).toBe(2);
  });
});

describe("collection cutoff", () => {
  const source = (name: string, at: string | null, status = "healthy") => ({
    source: name, status, last_success_at: at, error: null,
  });

  it("is the oldest report source, ignoring the price catalog", () => {
    const result = collectionCutoff({
      overall_status: "healthy", observation_gaps: [],
      sources: [
        source("galaxy_db", "2026-09-23T02:40:16Z"),
        source("gcp_batch", "2026-09-23T02:39:23Z"),
        source("price_catalog", "2026-09-01T00:00:00Z", "historical_snapshot"),
      ],
    });
    expect(result).toEqual({ cutoff: "2026-09-23T02:39:23Z", stale: false });
  });

  it("is stale when any source is, and unknown when a source never succeeded", () => {
    expect(collectionCutoff({
      overall_status: "partial", observation_gaps: [],
      sources: [source("galaxy_db", "2026-09-23T02:40:16Z", "stale")],
    }).stale).toBe(true);
    expect(collectionCutoff({
      overall_status: "partial", observation_gaps: [], sources: [source("kubernetes", null)],
    })).toEqual({ cutoff: null, stale: true });
  });
});


describe("query strings", () => {
  const busy = { ...state("runs"), ...RUN_FIELDS } as ReportState;

  it("keeps the run-only fields out of job and tool requests", () => {
    const query = queryString(busy);
    for (const key of ["workflow_key", "run_status", "focus_from", "focus_to", "max_run_amount",
      "boundary_run_id", "run_sort"]) {
      expect(query).not.toContain(key);
    }
  });

  it("adds every run field for the run endpoints", () => {
    const query = new URLSearchParams(runQueryString(busy, { limit: 20, offset: 40 }));
    expect(Object.fromEntries(query)).toMatchObject({
      workflow_key: "family-7", run_status: "failed", focus_from: "2026-09-02T00:00:00.000Z",
      focus_to: "2026-09-03T00:00:00.000Z", max_run_amount: "1.204",
      boundary_run_id: "9f0c0000-0000-4000-8000-000000000001", run_sort: "duration",
      direction: "asc", limit: "20", offset: "40",
    });
  });

  it("sorts runs by their own control, never the job sort", () => {
    const query = new URLSearchParams(runQueryString({ ...busy, sort: "tool_id", direction: "asc", runDirection: "desc" }));
    expect(query.has("sort")).toBe(false);
    expect(query.get("direction")).toBe("desc");
  });

  it("omits empty run fields", () => {
    const query = new URLSearchParams(runQueryString(state("runs")));
    for (const key of ["workflow_key", "run_status", "focus_from", "max_run_amount", "boundary_run_id"]) {
      expect(query.has(key)).toBe(false);
    }
    expect(query.get("run_sort")).toBe("started_at");
  });

  it("carries the shared filters to the run endpoints too", () => {
    const query = new URLSearchParams(runQueryString({ ...busy, search: "rna", quality: "partial" }));
    expect(query.get("search")).toBe("rna");
    expect(query.get("quality")).toBe("partial");
  });
});

describe("the URL of a runs view", () => {
  it("reproduces every run field", () => {
    const original = { ...state("runs"), ...RUN_FIELDS, search: "rna" } as ReportState;
    const restored = stateFromUrl(`?${urlQuery(original)}`);
    for (const key of Object.keys(RUN_FIELDS) as Array<keyof ReportState>) {
      expect(restored[key], key).toEqual(original[key]);
    }
    expect(restored.search).toBe("rna");
    expect(restored.view).toBe("runs");
  });

  it("names the parameters for people", () => {
    const query = urlQuery({ ...state("runs"), ...RUN_FIELDS } as ReportState);
    expect(Object.fromEntries(query)).toMatchObject({
      workflow: "family-7", outcome: "failed", focus_from: "2026-09-02T00:00:00.000Z",
      focus_to: "2026-09-03T00:00:00.000Z", max_amount: "1.204",
      boundary_run_id: "9f0c0000-0000-4000-8000-000000000001", run_sort: "duration",
      run_dir: "asc", chart: "time",
    });
  });

  it("leaves defaults out", () => {
    const query = urlQuery(state("runs"));
    for (const key of ["workflow", "outcome", "focus_from", "focus_to", "max_amount",
      "boundary_run_id", "run_sort", "run_dir", "chart"]) {
      expect(query.has(key), key).toBe(false);
    }
  });

  it("keeps run parameters off other pages' links", () => {
    const query = urlQuery({ ...state("tools"), ...RUN_FIELDS } as ReportState);
    expect(query.has("workflow")).toBe(false);
    expect(query.has("outcome")).toBe(false);
  });

  it("falls back to defaults for values it does not know", () => {
    const restored = stateFromUrl("?view=runs&outcome=paused&run_sort=colour&chart=bars&run_dir=up");
    expect(restored.runStatus).toBe("");
    expect(restored.runSort).toBe("started_at");
    expect(restored.runChart).toBe("workflow");
    expect(restored.runDirection).toBe("desc");
  });

  it("restores a first visit from an empty query", () => {
    const restored = stateFromUrl("");
    expect(restored).toMatchObject({ view: "overview", period: "this-month", ...NO_RUN_FILTERS, ...DEFAULT_RUN_CONTROLS });
  });
});

describe("what each view requests", () => {
  function record(paths: string[]) {
    return vi.fn(async (url: string) => {
      paths.push(url);
      const body = url.includes("/summary") ? SUMMARY
        : url.includes("/freshness") || url.includes("/me") ? {}
          : { ...EMPTY_LIST, groups: [], buckets: [] };
      return new Response(JSON.stringify(body), { status: 200 });
    });
  }

  it("asks only the Jobs page for a job list", async () => {
    for (const view of ["overview", "runs", "tools", "daily"] as const) {
      const paths: string[] = [];
      vi.stubGlobal("fetch", record(paths));
      await loadReport(state(view));
      expect(paths.some(path => path.includes("/jobs")), view).toBe(false);
    }
    const paths: string[] = [];
    vi.stubGlobal("fetch", record(paths));
    await loadReport(state("tool-runs"));
    expect(paths.some(path => path.includes("/jobs?"))).toBe(true);
  });

  it("asks the runs page for its list and active chart, and no job list", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", record(paths));
    await loadReport(state("runs"));
    expect(paths.some(path => path.includes("/jobs"))).toBe(false);
    expect(paths.some(path => path.includes("/invocations?"))).toBe(true);
    expect(paths.some(path => path.includes("/invocations/breakdown"))).toBe(true);
    expect(paths.some(path => path.includes("/invocations/timeline"))).toBe(false);
    for (const path of paths.filter(path => path.includes("/invocations"))) {
      expect(path).toContain("revision=rev-1");
    }
  });

  it("asks the time tab for the timeline, and the strip's breakdown when a workflow is chosen", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", record(paths));
    await loadReport({ ...state("runs"), runChart: "time" });
    expect(paths.some(path => path.includes("/invocations/timeline"))).toBe(true);
    expect(paths.some(path => path.includes("/invocations/breakdown"))).toBe(false);

    paths.length = 0;
    await loadReport({ ...state("runs"), runChart: "time", workflowKey: "family-7" });
    expect(paths.some(path => path.includes("/invocations/timeline"))).toBe(true);
    expect(paths.filter(path => path.includes("/invocations/breakdown"))).toHaveLength(1);
  });

  it("keeps every workflow on the chart when one is chosen, and asks for it alone for the strip", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", record(paths));
    await loadReport({
      ...state("runs"), workflowKey: "family-7", runStatus: "failed",
      maxRunAmount: "1.204", boundaryRunId: "9f0c0000-0000-4000-8000-000000000001",
    });
    const asks = paths.filter(path => path.includes("/invocations/breakdown"))
      .map(path => new URLSearchParams(path.split("?")[1]));
    expect(asks).toHaveLength(2);
    const chart = asks.find(query => !query.has("workflow_key"))!;
    const strip = asks.find(query => query.has("workflow_key"))!;
    // The chart still honours every other filter.
    expect(chart.get("run_status")).toBe("failed");
    expect(chart.has("boundary_run_id")).toBe(false);
    expect(strip.get("workflow_key")).toBe("family-7");
    expect(strip.get("boundary_run_id")).toBe("9f0c0000-0000-4000-8000-000000000001");
  });

  it("asks Overview for the period's four most expensive runs, whatever the runs page filters", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", record(paths));
    await loadReport({ ...state("overview"), ...RUN_FIELDS, search: "rna" } as ReportState);
    const top = new URLSearchParams(paths.find(path => path.includes("/invocations?"))!.split("?")[1]);
    expect(top.get("run_sort")).toBe("amount");
    expect(top.get("direction")).toBe("desc");
    expect(top.get("limit")).toBe("4");
    expect(top.has("workflow_key")).toBe(false);
    expect(top.has("run_status")).toBe(false);
    expect(top.has("search")).toBe(false);
  });
});
