import type { CostBreakdownFacts, CostEntity, InvocationDetail, RunJob } from "../api";
import { fromScaled, scaleOf, toScaled } from "../costBreakdown";

let counter = 0;

export function resetJobs() {
  counter = 0;
}

export function runJob(tool: string, amount: string | null, over: Partial<RunJob> = {}): RunJob {
  counter += 1;
  return {
    id: `job-${counter}`, source_id: String(1000 + counter), tool_id: `tools/${tool}`, tool_name: tool,
    tool_version: "1.0", state: "ok", quality: "complete", amount,
    attribution: amount === null ? "unknown" : Number(amount) > 0 ? "individual" : "known_zero",
    environment: "dedicated", capacities: ["dedicated"], cost_entity_id: null,
    created_at: "2026-09-02T10:00:00Z", started_at: "2026-09-02T10:00:00Z", finished_at: "2026-09-02T10:00:14Z",
    duration_seconds: 14, duration_running: false, attempt_count: 1, reused: false, order: counter,
    steps: [{ invocation_id: "run-1", workflow_name: "Variant calling", step_key: `${counter}:1`, relationship: "direct", nested: false }],
    ...over,
  };
}

/** A run as the detail endpoint answers, with an entity for every job that added cost. */
export function runDetail(jobs: RunJob[], over: Partial<InvocationDetail> = {}, facts: Partial<CostBreakdownFacts> = {}): InvocationDetail {
  const paid = jobs.filter(job => job.amount !== null && Number(job.amount) > 0);
  const entities: CostEntity[] = paid.map(job => ({
    id: `job:${job.id}`, kind: "batch_job", amount: job.amount!, currency: "USD", scope: "run",
    environment: job.environment, complete: job.quality === "complete", job_ids: [job.id],
  }));
  const scale = Math.max(0, ...entities.map(entity => scaleOf(entity.amount)));
  const total = entities.reduce((sum, entity) => sum + toScaled(entity.amount, scale)!, 0n);
  const subtotal = entities.length ? fromScaled(total, scale) : null;
  return {
    id: "run-1", source_id: "1", workflow_id: "wf", workflow_key: "wf", workflow_name: "Variant calling",
    workflow_version: null, parent_id: null, state: "scheduled", run_status: "completed",
    started_at: "2026-09-02T10:00:00Z", finished_at: "2026-09-02T11:30:00Z", duration_seconds: 5400,
    job_count: jobs.length, run_job_count: jobs.length, amount: subtotal, run_total: subtotal,
    run_total_complete: true, currency: "USD", unpriced_job_count: 0, run_unpriced_job_count: 0,
    reused_job_count: 0, timing_unavailable: false, chart_amount: subtotal, shared_job_count: 0,
    jobs, cost_entities: entities, unavailable_step_count: 0, children: [],
    cost_breakdown: {
      status: "available", reason: null, currency: "USD", known_subtotal: subtotal, complete: true,
      job_count: jobs.length, cost_entity_count: entities.length,
      known_zero_job_count: jobs.filter(job => job.attribution === "known_zero").length,
      unknown_job_count: jobs.filter(job => job.attribution === "unknown").length, ...facts,
    },
    meta: {} as InvocationDetail["meta"], ...over,
  };
}
