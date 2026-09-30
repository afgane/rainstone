import { describe, expect, it } from "vitest";

import type { RunJob } from "./api";
import { groupJobs } from "./runJobs";

function job(order: number, environment: string, amount: string | null, over: Partial<RunJob> = {}): RunJob {
  return {
    id: `job-${order}`, source_id: String(order), tool_id: "t", tool_name: "t", tool_version: null,
    state: "ok", quality: "complete", amount, attribution: amount === null ? "unknown" : "individual",
    environment, capacities: [environment], cost_entity_id: null, created_at: "2026-09-02T10:00:00Z",
    started_at: null, finished_at: null, duration_seconds: 1, duration_running: false, attempt_count: 1,
    reused: false, order, steps: [], ...over,
  };
}

describe("grouping a run's jobs by where they ran", () => {
  it("puts dedicated compute first, the server next, and not established last", () => {
    const groups = groupJobs([
      job(1, "unknown", null), job(2, "existing", "0"), job(3, "multiple", "1"),
      job(4, "elastic_shared", "1"), job(5, "dedicated", "1"),
    ]);
    expect(groups.map(group => group.environment)).toEqual([
      "dedicated", "existing", "elastic_shared", "multiple", "unknown",
    ]);
    expect(groups.map(group => group.label)).toContain("Not established");
  });

  it("lists every job once, in run order, however they arrive", () => {
    const [group] = groupJobs([job(3, "dedicated", "1"), job(1, "dedicated", "2"), job(2, "dedicated", "3")]);
    expect(group.jobs.map(each => each.order)).toEqual([1, 2, 3]);
  });

  it("keeps repeated tools as separate rows", () => {
    const [group] = groupJobs([job(1, "dedicated", "0.001"), job(2, "dedicated", "0.001")]);
    expect(group.jobs).toHaveLength(2);
  });

  it("states no cost for the server's jobs, and never adds them to anything", () => {
    const groups = groupJobs([job(1, "existing", "0"), job(2, "existing", "0")]);
    expect(groups[0].showsCost).toBe(false);
  });

  it("states a cost for dedicated compute even when none is known yet", () => {
    const [group] = groupJobs([job(1, "dedicated", null)]);
    expect(group.showsCost).toBe(true);
    expect(group.subtotal).toBeNull();
    expect(group.incomplete).toBe(1);
  });

  it("states a cost in an unverified place only when a job's amount can be", () => {
    expect(groupJobs([job(1, "unknown", null)])[0].showsCost).toBe(false);
    expect(groupJobs([job(1, "unknown", "0.5"), job(2, "unknown", null)])[0].showsCost).toBe(true);
    expect(groupJobs([job(1, "multiple", null)])[0].showsCost).toBe(false);
  });

  it("adds a group's known cost exactly and counts what is missing", () => {
    const [group] = groupJobs([
      job(1, "dedicated", "0.1"), job(2, "dedicated", "0.2"), job(3, "dedicated", null),
      job(4, "dedicated", "0.05", { quality: "partial" }),
    ]);
    expect(group.subtotal).toBe("0.35");
    expect(group.incomplete).toBe(2);
  });

  it("does not count a known zero as missing", () => {
    const [group] = groupJobs([job(1, "existing", "0", { quality: "known_zero" })]);
    expect(group.incomplete).toBe(0);
    expect(group.subtotal).toBe("0");
  });
});
