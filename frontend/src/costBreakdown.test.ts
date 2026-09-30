import { describe, expect, it } from "vitest";

import type { CostBreakdownFacts, CostEntity, RunJob } from "./api";
import {
  allocateCells, CELL_COUNT, collidingNames, composeCost, fromScaled, partQualifier, scaleOf, toScaled,
} from "./costBreakdown";

let counter = 0;

function job(tool: string, amount: string | null, over: Partial<RunJob> = {}): RunJob {
  counter += 1;
  return {
    id: `job-${counter}`, source_id: String(counter), tool_id: tool, tool_name: tool, tool_version: "1.0",
    state: "ok", quality: "complete", amount, attribution: amount === null ? "unknown" : "individual",
    environment: "dedicated", capacities: ["dedicated"], cost_entity_id: null,
    created_at: "2026-09-02T10:00:00Z", started_at: null, finished_at: null, duration_seconds: 10,
    duration_running: false, attempt_count: 1, reused: false, order: counter, steps: [], ...over,
  };
}

function entity(source: RunJob): CostEntity {
  return {
    id: `job:${source.id}`, kind: "batch_job", amount: source.amount!, currency: "USD", scope: "run",
    environment: source.environment, complete: true, job_ids: [source.id],
  };
}

function run(jobs: RunJob[], over: Partial<CostBreakdownFacts> = {}, extra: CostEntity[] = []) {
  const entities = [...jobs.filter(each => each.amount && Number(each.amount) > 0).map(entity), ...extra];
  const scale = Math.max(0, ...entities.map(each => scaleOf(each.amount)));
  const total = entities.reduce((sum, each) => sum + toScaled(each.amount, scale)!, 0n);
  return {
    jobs, cost_entities: entities,
    cost_breakdown: {
      status: "available", reason: null, currency: "USD", complete: true,
      known_subtotal: entities.length ? fromScaled(total, scale) : null, job_count: jobs.length,
      cost_entity_count: entities.length, known_zero_job_count: 0, unknown_job_count: 0, ...over,
    } as CostBreakdownFacts,
  };
}

function amounts(values: string[], prefix = "tool") {
  return values.map((value, index) => job(`${prefix}-${index}`, value));
}

describe("exact decimals", () => {
  it("adds without floating point drift", () => {
    const scale = 1;
    expect(fromScaled(toScaled("0.1", scale)! + toScaled("0.2", scale)!, scale)).toBe("0.3");
    expect(fromScaled(toScaled("0.000000000001", 12)!, 12)).toBe("0.000000000001");
    expect(fromScaled(5n, 0)).toBe("5");
    expect(fromScaled(-5n, 1)).toBe("-0.5");
    expect(scaleOf("12.3400")).toBe(4);
  });

  it("refuses what is not a plain decimal", () => {
    expect(toScaled("1e-7", 8)).toBeNull();
    expect(toScaled("NaN", 0)).toBeNull();
    expect(toScaled("1.25", 1)).toBeNull();
  });
});

describe("allocating one hundred squares", () => {
  it("uses the largest remainders and always totals one hundred", () => {
    expect(allocateCells([81n, 50n, 6n, 7n], 144n)).toEqual([56, 35, 4, 5]);
    for (const amounts of [[1n], [1n, 1n, 1n], [33n, 33n, 34n], [999n, 1n], [7n, 7n, 7n, 7n, 7n, 7n, 7n]]) {
      const total = amounts.reduce((a, b) => a + b, 0n);
      const counts = allocateCells(amounts, total);
      expect(counts.reduce((a, b) => a + b, 0)).toBe(CELL_COUNT);
      expect(counts.every(count => count >= 0)).toBe(true);
    }
  });

  it("breaks ties by order, so equal parts do not reshuffle", () => {
    expect(allocateCells([1n, 1n, 1n], 3n)).toEqual([34, 33, 33]);
  });
});

describe("composing the parts of a run's cost", () => {
  it("names three parts and pools the rest, in the specification's example", () => {
    const composition = composeCost(run(amounts(["81", "50", "6", "4", "3"])));
    expect(composition.status).toBe("chart");
    expect(composition.parts.map(part => part.name)).toEqual(["tool-0", "tool-1", "tool-2", "Other"]);
    expect(composition.parts.map(part => part.cells)).toEqual([56, 35, 4, 5]);
    const other = composition.parts[3];
    expect(other.amount).toBe("7");
    expect(other.members.map(member => member.name)).toEqual(["tool-3", "tool-4"]);
  });

  it("caps the named parts at eight and keeps every other one drillable", () => {
    const composition = composeCost(run(amounts(Array(20).fill("5"))));
    expect(composition.parts).toHaveLength(9);
    expect(composition.parts.slice(0, 8).every(part => part.cells === 5)).toBe(true);
    const other = composition.parts[8];
    expect(other.cells).toBe(60);
    expect(other.members).toHaveLength(12);
    expect(other.members.reduce((sum, member) => sum + Number(member.amount), 0)).toBe(60);
  });

  it("pools repeated jobs of one tool before any threshold applies", () => {
    const repeated = [job("wig", "0.4"), job("wig", "0.4"), job("wig", "0.4")];
    const composition = composeCost(run([job("star", "98.8"), ...repeated]));
    const group = composition.parts.find(part => part.name === "wig ×3")!;
    expect(group.amount).toBe("1.2");
    expect(group.jobIds).toEqual(repeated.map(each => each.id));
    expect(composition.parts.map(part => part.kind)).toEqual(["tool_group", "tool_group"]);
    expect(group.cells).toBe(1);
  });

  it("counts jobs, not charges, in a group's name", () => {
    const first = job("wig", "1");
    const second = job("wig", "1");
    const composition = composeCost(run([first, second]));
    expect(composition.parts).toHaveLength(1);
    expect(composition.parts[0].name).toBe("wig ×2");
    expect(composition.parts[0].jobIds).toHaveLength(2);
  });

  it("keeps a sub-square remainder selectable with no square of its own", () => {
    const composition = composeCost(run(amounts(["99.9", "0.1"])));
    expect(composition.parts.map(part => part.cells)).toEqual([100, 0]);
    expect(composition.parts[1].kind).toBe("other");
    expect(composition.parts[1].amount).toBe("0.1");
    expect(composition.cellOwners).toHaveLength(100);
    expect(composition.cellOwners.includes("other")).toBe(false);
  });

  it("names a trivial remainder when every piece of it can stand on its own", () => {
    const composition = composeCost(run(amounts(["98.5", "1.5"])));
    expect(composition.parts.map(part => part.kind)).toEqual(["tool_group", "tool_group"]);
    expect(composition.parts.map(part => part.cells)).toEqual([99, 1]);
  });

  it("never drops money to avoid an Other", () => {
    const composition = composeCost(run(amounts(["98.5", "1", "0.5"])));
    const total = composition.parts.reduce((sum, part) => sum + Number(part.amount), 0);
    expect(total).toBe(100);
    expect(composition.parts[composition.parts.length - 1].kind).toBe("other");
  });

  it("gives a single part every square and can still be selected", () => {
    const composition = composeCost(run([job("star", "3")]));
    expect(composition.parts).toHaveLength(1);
    expect(composition.parts[0].cells).toBe(100);
    expect(composition.byKey.get(composition.parts[0].key)).toBe(composition.parts[0]);
  });

  it("orders equal amounts the same way whatever order they arrive in", () => {
    const jobs = amounts(["10", "10", "10", "10"]);
    const forward = composeCost(run(jobs)).parts.map(part => part.key);
    const backward = composeCost(run([...jobs].reverse())).parts.map(part => part.key);
    expect(backward).toEqual(forward);
  });

  it("reconciles the parts with the known whole-run subtotal", () => {
    const composition = composeCost(run(amounts(["0.1", "0.2", "0.30000001"])));
    expect(composition.subtotal).toBe("0.60000001");
    const sum = composition.parts.flatMap(part => (part.members.length ? part.members : [part]));
    expect(sum.reduce((total, part) => total + Number(part.amount), 0)).toBeCloseTo(0.60000001, 10);
  });

  it("shares are of the known cost, from amounts and not from squares", () => {
    const composition = composeCost(run(amounts(["99.9", "0.1"])));
    expect(composition.parts[0].share).toBeCloseTo(0.999, 6);
    expect(composition.parts[1].share).toBeCloseTo(0.001, 6);
  });

  it("does not merge tools by their name, version or place", () => {
    const composition = composeCost(run([
      job("a/tool", "5", { tool_name: "same" }), job("b/tool", "5", { tool_name: "same" }),
      job("a/tool", "5", { tool_name: "same", tool_version: "2.0" }),
      job("a/tool", "5", { tool_name: "same", environment: "elastic_shared" }),
    ]));
    expect(composition.parts).toHaveLength(4);
    expect(collidingNames(composition.parts)).toEqual(new Set(["same"]));
    expect(composition.parts.map(partQualifier)).toContain("version 2.0 · Dedicated cloud compute");
  });

  it("pools parts from several places as multiple environments", () => {
    const composition = composeCost(run([
      job("a", "60"), job("b", "20"), job("c", "10", { environment: "elastic_shared" }),
      job("d", "5"), job("e", "3", { environment: "elastic_shared" }), job("f", "2"),
      job("g", "1", { environment: "elastic_shared" }), job("h", "1"), job("i", "1"), job("j", "1"),
    ]));
    const other = composition.parts.find(part => part.kind === "other")!;
    expect(other.environment).toBe("multiple");
  });

  it("keeps a virtual machine as its own part and never counts its jobs again", () => {
    const users = [job("a", "0", { attribution: "known_zero" }), job("b", "0", { attribution: "known_zero" })];
    const composition = composeCost(run(users, {}, [{
      id: "vm-1", kind: "vm_session", amount: "4", currency: "USD", scope: "run",
      environment: "dedicated_vm", complete: true, job_ids: users.map(each => each.id), label: "Analysis VM",
    }]));
    expect(composition.parts).toHaveLength(1);
    expect(composition.parts[0]).toMatchObject({ kind: "vm_session", name: "Analysis VM", amount: "4" });
    expect(composition.parts[0].jobIds).toEqual(users.map(each => each.id));
  });

  it("marks a part incomplete when any of its charges is", () => {
    const partial = run([job("a", "5"), job("a", "5")]);
    partial.cost_entities[1].complete = false;
    expect(composeCost(partial).parts[0].complete).toBe(false);
  });
});

describe("what is not a chart", () => {
  it("says a run with no jobs has nothing to chart", () => {
    const composition = composeCost(run([]));
    expect(composition).toMatchObject({ status: "empty", emptyReason: "no-jobs" });
  });

  it("does not paint free or unknown work as paid contributors", () => {
    const free = job("a", "0", { attribution: "known_zero" });
    const unknown = job("b", null);
    const composition = composeCost(run([free, unknown], { known_zero_job_count: 1, unknown_job_count: 1 }));
    expect(composition).toMatchObject({
      status: "empty", emptyReason: "none-paid", knownZeroJobs: 1, unknownJobs: 1, cellOwners: [],
    });
  });

  it("refuses a breakdown the backend could not trust", () => {
    const facts = { status: "unavailable", reason: "The parts do not add up to the run total." } as const;
    const composition = composeCost(run(amounts(["1"]), facts));
    expect(composition).toMatchObject({ status: "unavailable", reason: facts.reason, parts: [] });
  });

  it("refuses a negative amount rather than giving it squares", () => {
    const negative = run(amounts(["5"]));
    negative.cost_entities.push({ ...negative.cost_entities[0], id: "job:refund", amount: "-1" });
    expect(composeCost(negative).status).toBe("unavailable");
  });

  it("refuses parts that do not add up to the headline", () => {
    const mismatched = run(amounts(["5", "5"]), { known_subtotal: "11" });
    const composition = composeCost(mismatched);
    expect(composition.status).toBe("unavailable");
    expect(composition.cellOwners).toEqual([]);
  });

  it("refuses a charge whose job is not in the run", () => {
    const orphan = run(amounts(["5"]));
    orphan.cost_entities[0].job_ids = ["missing"];
    expect(composeCost(orphan).status).toBe("unavailable");
  });

  it("refuses a currency it was not asked to combine", () => {
    const foreign = run(amounts(["5"]));
    (foreign.cost_entities[0] as { currency: string }).currency = "EUR";
    expect(composeCost(foreign).status).toBe("unavailable");
  });
});
