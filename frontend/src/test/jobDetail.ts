/** Builders for a job's drawer tests: a finished, single-execution job on its own machine. */
import type { JobDetail, JobExecution, JobResource, JobResourceUse } from "../api";

export function execution(overrides: Partial<JobExecution> = {}): JobExecution {
  return {
    id: "a1", source_attempt_id: "attempt-1", runner: "gcp_batch", outcome: "ok", provider_outcome: null,
    exit_code: 0, task_index: 0, attempt_ordinal: 1,
    tool_started_at: "2026-09-29T01:06:00Z", tool_finished_at: "2026-09-29T01:16:00Z",
    duration_seconds: 600, duration_running: false, role: "first", resource_keys: ["vm-1"], amount: null,
    amount_shared_with_attempts: [], ...overrides,
  };
}

export function resource(overrides: Partial<JobResource> = {}): JobResource {
  return {
    lifetime_id: "l1", resource_key: "vm-1", resource_uid: "vm-1", provider: "gcp",
    machine_type: "n2-standard-8",
    machine_capacity: { vcpu: "8", memory_mib: "32768", gpu: null, source: "published_machine_shape" }, region: "us-central1", zone: null, purchase_model: "on_demand",
    capacity_relationship: "dedicated", resource_started_at: "2026-09-29T01:05:00Z",
    resource_finished_at: "2026-09-29T01:20:00Z", timing_method: "compute_insert_complete_to_delete_request",
    requested_vcpu: "8.000000000000", requested_memory_mib: "32768.000000", amount: "0.77",
    quality: "complete", reason: "", shared_attempt_ids: ["a1"], shared_attempt_count: 1, ...overrides,
  };
}

export function emptyUse(overrides: Partial<JobResourceUse> = {}): JobResourceUse {
  return {
    measurement_scope: "single_execution", scope_reason: null,
    cpu: {
      status: "not_recorded", reason: null, cpu_seconds: null, duration_seconds: null, average_cores: null,
      requested_vcpu: "8.000000000000", request_fraction: null,
    },
    memory: {
      status: "not_recorded", reason: null, peak_bytes: null, source: null,
      requested_memory_mib: "32768.000000", request_fraction: null,
    },
    metrics: [], ...overrides,
  };
}

export function job(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    id: "j1", source_id: "42", tool_id: "toolshed/bwa_mem/0.7", tool_name: "bwa mem", tool_key: "toolshed/bwa_mem/0.7", tool_version: "0.7",
    owner: "alice", owner_id: "alice", state: "ok", runner: "gcp_batch", destination: null,
    created_at: "2026-09-29T00:51:00Z", amount: "0.77", currency: "USD", quality: "complete", reason: "",
    cost_lines: 1, attempt_count: 1, repeat_attempt_count: 0, attempt_evidence: "provider",
    capacities: ["dedicated"], temporally_unattributed: false, revision_id: "r1", basis: "additional",
    interval_amount: "0.77", full_job_amount: "0.77", full_quality: "complete", full_reason: "",
    full_capacities: ["dedicated"], started_at: "2026-09-29T01:06:00Z", finished_at: "2026-09-29T01:16:00Z",
    duration_seconds: 600, duration_running: false, duration_cutoff: null, before_start_seconds: 900,
    timing_issue: null, attempts: [execution()], resources: [resource()], resource_use: emptyUse(),
    ...overrides,
  };
}
