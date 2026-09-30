import { describe, expect, it } from "vitest";
import {
  barGeometry, buildLanes, buildTimeline, executionHistory, formatCores, formatMachineCapacity, formatRequestPercent,
  logicalExecutions, resourceUseView, sameAmount,
} from "./jobDetail";
import { emptyUse, execution, job, resource } from "./test/jobDetail";

describe("sameAmount", () => {
  it("compares numbers, not spellings", () => {
    expect(sameAmount("0.77", "0.770000000000")).toBe(true);
    expect(sameAmount("0.77", "0.78")).toBe(false);
    expect(sameAmount(null, null)).toBe(true);
    expect(sameAmount("0", null)).toBe(false);
  });
});

describe("barGeometry", () => {
  it("ends the track at the request when use is at or below it", () => {
    expect(barGeometry(0.3)).toEqual({ aboveRequest: false, fillPercent: 30, markerPercent: null });
    expect(barGeometry(1)).toEqual({ aboveRequest: false, fillPercent: 100, markerPercent: null });
  });

  it("stretches the track past the request and moves the request to a marker", () => {
    const geometry = barGeometry(1.25);
    expect(geometry.aboveRequest).toBe(true);
    expect(geometry.fillPercent).toBeCloseTo((1.25 / 1.375) * 100);
    expect(geometry.markerPercent).toBeCloseTo((1 / 1.375) * 100);
    expect(geometry.markerPercent!).toBeLessThan(geometry.fillPercent);
  });
});

describe("formatting", () => {
  it("rounds to whole percents and never rounds real use to nothing", () => {
    expect(formatRequestPercent(0.3)).toBe("30%");
    expect(formatRequestPercent(1.25)).toBe("125%");
    expect(formatRequestPercent(0.004)).toBe("less than 1%");
    expect(formatRequestPercent(0)).toBe("0%");
  });

  it("keeps two decimals of cores and a tiny positive amount positive", () => {
    expect(formatCores(2.4)).toBe("2.4");
    expect(formatCores(0.004)).toBe("less than 0.01");
  });
});

describe("resourceUseView", () => {
  const cpu = (overrides = {}) => ({
    ...emptyUse().cpu, status: "available" as const, cpu_seconds: "1440", duration_seconds: "600",
    average_cores: "2.4", request_fraction: "0.3", ...overrides,
  });
  const memory = (overrides = {}) => ({
    ...emptyUse().memory, status: "available" as const, peak_bytes: String(8 * 1024 ** 3), source: "memory.peak",
    request_fraction: "0.25", ...overrides,
  });

  it("states the two comparisons with their values beside them", () => {
    const view = resourceUseView(emptyUse({ cpu: cpu(), memory: memory() }));
    const [cpuRow, memoryRow] = view.rows;
    expect(cpuRow.label).toBe("Average CPU use");
    expect(cpuRow.comparison?.values).toBe("2.4 of 8 requested vCPUs");
    expect(cpuRow.comparison?.percent).toBe("30% on average");
    expect(memoryRow.label).toBe("Peak memory use");
    expect(memoryRow.comparison?.values).toBe("8 of 32 GiB requested");
    expect(memoryRow.comparison?.percent).toBe("25% at peak");
  });

  it("keeps the exact ratio above the request and marks the request", () => {
    const view = resourceUseView(emptyUse({ cpu: cpu({ average_cores: "10", request_fraction: "1.25" }), memory: memory() }));
    const comparison = view.rows[0].comparison!;
    expect(comparison.percent).toBe("125% of request on average");
    expect(comparison.aboveRequest).toBe(true);
    expect(comparison.markerPercent).not.toBeNull();
  });

  it("says nothing was recorded once, and still states what was requested", () => {
    const view = resourceUseView(emptyUse());
    expect(view.unrecorded).toBe(true);
    expect(view.rows).toEqual([]);
    expect(view.requested).toEqual(["8 vCPUs", "32 GiB"]);
  });

  it("keeps a measured value and explains the missing bar, never drawing zero", () => {
    const view = resourceUseView(emptyUse({
      cpu: cpu({ status: "request_unavailable", reason: "request_missing", requested_vcpu: null, request_fraction: null }),
      memory: emptyUse().memory,
    }));
    const [cpuRow, memoryRow] = view.rows;
    expect(cpuRow.comparison).toBeNull();
    expect(cpuRow.facts).toEqual(["2.4 vCPUs used on average"]);
    expect(cpuRow.note).toContain("No request was recorded");
    expect(memoryRow.comparison).toBeNull();
    expect(memoryRow.note).toBe("Memory use not recorded.");
  });

  it("gives a peak with no request as a plain fact", () => {
    const view = resourceUseView(emptyUse({
      cpu: emptyUse().cpu,
      memory: memory({ status: "request_unavailable", reason: "request_missing", requested_memory_mib: null, request_fraction: null }),
    }));
    expect(view.rows[1].facts).toEqual(["8 GiB at peak"]);
  });

  it("attributes nothing of a Galaxy server's counters to the job", () => {
    const view = resourceUseView(emptyUse({
      measurement_scope: "unestablished", scope_reason: "galaxy_server",
      cpu: { ...emptyUse().cpu, status: "unsupported_scope", reason: "galaxy_server" },
    }));
    expect(view.serverJob).toBe(true);
    expect(view.rows).toEqual([]);
  });

  it("explains a retry's unmatched counters", () => {
    const view = resourceUseView(emptyUse({
      measurement_scope: "unestablished", scope_reason: "several_executions",
      cpu: { ...emptyUse().cpu, status: "unsupported_scope", reason: "several_executions", cpu_seconds: "100" },
      memory: emptyUse().memory,
    }));
    expect(view.rows[0].facts).toEqual(["100 CPU-seconds used", "8 vCPUs requested"]);
    expect(view.rows[0].note).toContain("more than once");
  });
});

describe("buildTimeline", () => {
  it("draws submission, start and finish at their real positions", () => {
    const timeline = buildTimeline(job());
    expect(timeline.drawn).toBe(true);
    expect(timeline.events.map(event => event.key)).toEqual(["submitted", "started", "finished"]);
    expect(timeline.startPercent).toBeCloseTo(60);
  });

  it("ends a running job at the snapshot, never at a finish", () => {
    const timeline = buildTimeline(job({
      state: "running", finished_at: null, duration_running: true, duration_cutoff: "2026-09-29T01:30:00Z",
      attempts: [execution({ tool_finished_at: null, duration_running: true })],
    }));
    expect(timeline.running).toBe(true);
    expect(timeline.events.map(event => event.key)).toEqual(["submitted", "started", "recorded"]);
  });

  it("does not invent an execution for work that has not started", () => {
    const timeline = buildTimeline(job({
      state: "queued", started_at: null, finished_at: null, duration_seconds: null, before_start_seconds: null, attempts: [],
    }));
    expect(timeline.waiting).toBe(true);
    expect(timeline.drawn).toBe(false);
    expect(timeline.events).toHaveLength(1);
  });

  it("lists the facts that are not contradicted when times are out of order", () => {
    const timeline = buildTimeline(job({ timing_issue: "finished_before_started", duration_seconds: null }));
    expect(timeline.drawn).toBe(false);
    expect(timeline.note).toContain("earlier than the recorded start");
  });

  it("lists events without a span when the finish was not recorded", () => {
    const timeline = buildTimeline(job({ finished_at: null, duration_seconds: null }));
    expect(timeline.drawn).toBe(false);
    expect(timeline.events.map(event => event.key)).toEqual(["submitted", "started"]);
    expect(timeline.note).toContain("finish was not recorded");
  });

  it("summarises several executions in order without drawing continuous activity", () => {
    const timeline = buildTimeline(job({
      attempts: [execution(), execution({ id: "a2", role: "repeat", attempt_ordinal: 2 })],
    }));
    expect(timeline.drawn).toBe(false);
    expect(timeline.events.map(event => event.key)).toEqual(["submitted", "first-started", "last-finished"]);
  });
});

describe("buildLanes", () => {
  it("places tool execution inside the machine's lifetime on one scale", () => {
    const lanes = buildLanes(job())!;
    expect(lanes.compute.startPercent).toBe(0);
    expect(lanes.compute.endPercent).toBe(100);
    expect(lanes.tool.startPercent).toBeCloseTo((1 / 15) * 100);
    expect(lanes.tool.endPercent).toBeCloseTo((11 / 15) * 100);
  });

  it("is not drawn for the Galaxy server, several machines, or an unknown end", () => {
    expect(buildLanes(job({ resources: [resource({ capacity_relationship: "existing" })] }))).toBeNull();
    expect(buildLanes(job({ resources: [resource(), resource({ lifetime_id: "l2" })] }))).toBeNull();
    expect(buildLanes(job({ resources: [resource({ resource_finished_at: null })] }))).toBeNull();
  });

  it("ends an ongoing machine at the snapshot", () => {
    const lanes = buildLanes(job({
      state: "running", finished_at: null, duration_running: true, duration_cutoff: "2026-09-29T01:30:00Z",
      resources: [resource({ resource_finished_at: null })],
    }))!;
    expect(lanes.computeOngoing).toBe(true);
  });
});

describe("executionHistory", () => {
  it("needs none for one execution, and ignores duplicate observations", () => {
    expect(executionHistory(job())).toBeNull();
    const observed = job({ attempts: [execution(), execution({ id: "a2", role: "observation" })] });
    expect(logicalExecutions(observed)).toHaveLength(1);
    expect(executionHistory(observed)).toBeNull();
  });

  it("calls retries runs and states how the job ended", () => {
    const history = executionHistory(job({
      attempts: [
        execution({ id: "a2", role: "repeat", attempt_ordinal: 2, tool_started_at: "2026-09-29T01:30:00Z" }),
        execution(),
      ],
    }))!;
    expect(history.heading).toBe("Runs");
    expect(history.summary).toBe("Completed after 2 runs");
    expect(history.rows.map(row => row.title)).toEqual(["Run 1", "Run 2"]);
  });

  it("does not call parallel tasks retries", () => {
    const history = executionHistory(job({
      attempts: [execution({ task_index: 0 }), execution({ id: "a2", task_index: 1 })],
    }))!;
    expect(history.heading).toBe("Runs");
    expect(history.summary).toBe("2 runs, in parallel");
    expect(history.rows.map(row => row.title)).toEqual(["Run 1", "Run 2"]);
  });

  it("keeps undated executions, last, with their timing unavailable", () => {
    const history = executionHistory(job({
      attempts: [
        execution({ id: "a1", outcome: "error", tool_started_at: null, tool_finished_at: null, duration_seconds: null, role: "repeat" }),
        execution({ id: "a2", attempt_ordinal: 2 }),
      ],
    }))!;
    expect(history.rows.map(row => row.dated)).toEqual([true, false]);
    expect(history.rows[1].execution.outcome).toBe("error");
  });
});

describe("formatMachineCapacity", () => {
  it("names vCPUs and memory in binary units", () => {
    expect(formatMachineCapacity({ vcpu: "8", memory_mib: "65536" })).toBe("8 vCPUs · 64 GiB memory");
    expect(formatMachineCapacity({ vcpu: "1", memory_mib: "4096" })).toBe("1 vCPU · 4 GiB memory");
    expect(formatMachineCapacity({ vcpu: "2", memory_mib: "1536" })).toBe("2 vCPUs · 1.5 GiB memory");
  });
});
