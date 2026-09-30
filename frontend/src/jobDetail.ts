/**
 * What a job's drawer derives for display from the API's facts: how long bars
 * are, how quantities read, which timeline events exist and how executions are
 * ordered. Eligibility for a comparison is decided by the backend; nothing here
 * divides a measurement by a request.
 */
import type { JobDetail, JobExecution, JobResourceUse, MachineCapacity } from "./api";
import {
  AVERAGE_CPU, comparisonNote, PEAK_MEMORY, pluralize, jobStateLabel, TIMING_NOTE,
} from "./vocabulary";

const BYTES_PER_MIB = 1024 ** 2;

/** Two amounts are the same when they are the same number, however the decimal is written. */
export function sameAmount(first: string | null, second: string | null): boolean {
  if (first === null || second === null) return first === second;
  return Number(first) === Number(second);
}

/* Comparison bars. */

export interface BarGeometry {
  aboveRequest: boolean;
  /** How far the measured bar reaches, as a percentage of the track. */
  fillPercent: number;
  /** Where the request falls on an expanded track; null when the track ends at the request. */
  markerPercent: number | null;
}

/**
 * The track ends at the request. Use above it stretches that row's track to the
 * measurement plus a little headroom, and the request becomes a marker.
 */
export function barGeometry(fraction: number): BarGeometry {
  const aboveRequest = fraction > 1;
  const scale = aboveRequest ? 1.1 * fraction : 1;
  return {
    aboveRequest,
    fillPercent: (fraction / scale) * 100,
    markerPercent: aboveRequest ? 100 / scale : null,
  };
}

/** Whole percents of the request; a real but tiny use is never rounded to nothing. */
export function formatRequestPercent(fraction: number): string {
  if (fraction === 0) return "0%";
  const percent = fraction * 100;
  return percent < 1 ? "less than 1%" : `${Math.round(percent)}%`;
}

/* Quantities. */

function trimmed(value: number, places: number): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: places });
}

/** Up to two decimals, and "less than 0.01" for a positive amount that would round away. */
function formatQuantity(value: number, places = 2): string {
  if (value > 0 && Number(value.toFixed(places)) === 0) return `less than ${trimmed(10 ** -places, places)}`;
  return trimmed(value, places);
}

export function formatCores(cores: number): string {
  return formatQuantity(cores);
}

export function vcpuWord(count: number): string {
  return count === 1 ? "vCPU" : "vCPUs";
}

type MemoryUnit = "MiB" | "GiB";

/** Binary units throughout; the request's size picks one unit for both figures. */
function memoryUnit(requestedMib: number): MemoryUnit {
  return requestedMib >= 1024 ? "GiB" : "MiB";
}

function inUnit(bytes: number, unit: MemoryUnit): number {
  return bytes / BYTES_PER_MIB / (unit === "GiB" ? 1024 : 1);
}

export function formatMemoryAmount(bytes: number): string {
  const unit = memoryUnit(bytes / BYTES_PER_MIB);
  return `${formatQuantity(inUnit(bytes, unit))} ${unit}`;
}

export function formatMemoryRequest(requestedMib: number): string {
  const unit = memoryUnit(requestedMib);
  return `${formatQuantity(inUnit(requestedMib * BYTES_PER_MIB, unit))} ${unit}`;
}

/** "8 of 32 GiB requested", in the unit the request is measured in. */
function memoryAgainstRequest(peakBytes: number, requestedMib: number): string {
  const unit = memoryUnit(requestedMib);
  return `${formatQuantity(inUnit(peakBytes, unit))} of ${formatQuantity(inUnit(requestedMib * BYTES_PER_MIB, unit))} ${unit} requested`;
}

/** The machine's own size, apart from anything a job asked of it: "8 vCPUs · 64 GiB memory · 1 NVIDIA L4 GPU". */
export function formatMachineCapacity(capacity: Pick<MachineCapacity, "vcpu" | "memory_mib" | "gpu">): string {
  const vcpu = Number(capacity.vcpu);
  const size = `${formatQuantity(vcpu)} ${vcpuWord(vcpu)} · ${formatMemoryRequest(Number(capacity.memory_mib))} memory`;
  if (!capacity.gpu) return size;
  return `${size} · ${pluralize(Number(capacity.gpu.count), `${capacity.gpu.model} GPU`)}`;
}

/* The resource use rows. */

export interface Comparison {
  /** Measured and requested, in words: "2.4 of 8 requested vCPUs". */
  values: string;
  /** The ratio, in words: "30% on average". */
  percent: string;
  fillPercent: number;
  markerPercent: number | null;
  aboveRequest: boolean;
  /** The bar's meaning for the tooltip; everything in it is also visible as text. */
  explanation: string;
}

export interface UseRow {
  key: "cpu" | "memory";
  label: string;
  comparison: Comparison | null;
  /** Measured or requested values stated as plain facts when there is no comparison. */
  facts: string[];
  /** Why there is no comparison. */
  note: string | null;
}

function number(value: string | null): number | null {
  return value === null ? null : Number(value);
}

function cpuRow(use: JobResourceUse["cpu"]): UseRow {
  const cores = number(use.average_cores);
  const requested = number(use.requested_vcpu);
  const fraction = number(use.request_fraction);
  const row: UseRow = { key: "cpu", label: AVERAGE_CPU, comparison: null, facts: [], note: null };
  if (use.status === "available" && cores !== null && requested !== null && fraction !== null) {
    const geometry = barGeometry(fraction);
    const percent = formatRequestPercent(fraction);
    const seconds = Number(use.cpu_seconds);
    const elapsed = Number(use.duration_seconds);
    return {
      ...row,
      comparison: {
        values: `${formatCores(cores)} of ${formatQuantity(requested)} requested ${vcpuWord(requested)}`,
        percent: geometry.aboveRequest ? `${percent} of request on average` : `${percent} on average`,
        fillPercent: geometry.fillPercent,
        markerPercent: geometry.markerPercent,
        aboveRequest: geometry.aboveRequest,
        explanation: `An average over the run: ${formatQuantity(seconds)} CPU-seconds used over ${formatQuantity(elapsed)} seconds, compared with ${formatQuantity(requested)} requested ${vcpuWord(requested)}.`,
      },
    };
  }
  if (cores !== null) row.facts.push(`${formatCores(cores)} ${vcpuWord(cores)} used on average`);
  else if (use.cpu_seconds !== null) row.facts.push(`${formatQuantity(Number(use.cpu_seconds))} CPU-seconds used`);
  if (requested !== null) row.facts.push(`${formatQuantity(requested)} ${vcpuWord(requested)} requested`);
  row.note = comparisonNote("cpu", use.status, use.reason);
  return row;
}

function memoryRow(use: JobResourceUse["memory"]): UseRow {
  const peak = number(use.peak_bytes);
  const requestedMib = number(use.requested_memory_mib);
  const fraction = number(use.request_fraction);
  const row: UseRow = { key: "memory", label: PEAK_MEMORY, comparison: null, facts: [], note: null };
  if (use.status === "available" && peak !== null && requestedMib !== null && fraction !== null) {
    const geometry = barGeometry(fraction);
    const percent = formatRequestPercent(fraction);
    return {
      ...row,
      comparison: {
        values: memoryAgainstRequest(peak, requestedMib),
        percent: geometry.aboveRequest ? `${percent} of request at peak` : `${percent} at peak`,
        fillPercent: geometry.fillPercent,
        markerPercent: geometry.markerPercent,
        aboveRequest: geometry.aboveRequest,
        explanation: `The most memory the run held at once, ${formatMemoryAmount(peak)}, compared with ${formatMemoryRequest(requestedMib)} requested.`,
      },
    };
  }
  if (peak !== null) row.facts.push(`${formatMemoryAmount(peak)} at peak`);
  if (requestedMib !== null) row.facts.push(`${formatMemoryRequest(requestedMib)} requested`);
  row.note = comparisonNote("memory", use.status, use.reason);
  return row;
}

export interface ResourceUseView {
  rows: UseRow[];
  /** Neither measurement was recorded, so there is one sentence instead of two empty rows. */
  unrecorded: boolean;
  /** What was asked for, stated when there is nothing measured to set beside it. */
  requested: string[];
  /** The measurements describe a Galaxy server, so none is attributed to the job. */
  serverJob: boolean;
}

export function resourceUseView(use: JobResourceUse): ResourceUseView {
  const serverJob = use.scope_reason === "galaxy_server";
  const unrecorded = use.cpu.status === "not_recorded" && use.memory.status === "not_recorded";
  const requested = [
    use.cpu.requested_vcpu !== null
      ? `${formatQuantity(Number(use.cpu.requested_vcpu))} ${vcpuWord(Number(use.cpu.requested_vcpu))}` : "",
    use.memory.requested_memory_mib !== null ? formatMemoryRequest(Number(use.memory.requested_memory_mib)) : "",
  ].filter(Boolean);
  return {
    rows: serverJob || unrecorded ? [] : [cpuRow(use.cpu), memoryRow(use.memory)],
    unrecorded: unrecorded && !serverJob,
    requested,
    serverJob,
  };
}

/* The execution timeline. */

export type TimelineEventKey = "submitted" | "started" | "finished" | "first-started" | "last-finished" | "recorded";

export interface TimelineEvent { key: TimelineEventKey; at: string }

export interface Timeline {
  /** Draw the shallow graphic; otherwise only the events are listed. */
  drawn: boolean;
  events: TimelineEvent[];
  /** Where the tool started on a graphic from submission (0) to the end (100). */
  startPercent: number;
  /** The end is the snapshot's time, not a finish. */
  running: boolean;
  /** Why the span is not drawn, when something is missing or out of order. */
  note: string | null;
  /** The job has not begun, so there is no execution to draw. */
  waiting: boolean;
}

/** Executions Galaxy and a provider both observed are one; observations are not extra. */
export function logicalExecutions(detail: Pick<JobDetail, "attempts">): JobExecution[] {
  return detail.attempts.filter(attempt => attempt.role !== "observation");
}

const WAITING_STATES = new Set(["new", "queued", "paused"]);

/** A job still waiting has no execution, so nothing about its duration is unavailable. */
export function neverStarted(state: string): boolean {
  return WAITING_STATES.has(state);
}

export function buildTimeline(detail: JobDetail): Timeline {
  const submitted: TimelineEvent = { key: "submitted", at: detail.created_at };
  const base = { drawn: false, events: [submitted], startPercent: 0, running: false, note: null, waiting: false };
  if (detail.timing_issue) return { ...base, events: availableEvents(detail, submitted), note: TIMING_NOTE[detail.timing_issue] };
  if (!detail.started_at) {
    return WAITING_STATES.has(detail.state)
      ? { ...base, waiting: true }
      : { ...base, note: TIMING_NOTE.not_recorded };
  }
  if (logicalExecutions(detail).length > 1) {
    const last = detail.finished_at
      ? { key: "last-finished" as const, at: detail.finished_at }
      : detail.duration_running && detail.duration_cutoff
        ? { key: "recorded" as const, at: detail.duration_cutoff } : null;
    return {
      ...base, running: detail.duration_running,
      events: [submitted, { key: "first-started", at: detail.started_at }, ...(last ? [last] : [])],
    };
  }
  const end: TimelineEvent | null = detail.finished_at
    ? { key: "finished", at: detail.finished_at }
    : detail.duration_running && detail.duration_cutoff ? { key: "recorded", at: detail.duration_cutoff } : null;
  const events: TimelineEvent[] = [submitted, { key: "started", at: detail.started_at }, ...(end ? [end] : [])];
  if (!end) return { ...base, events, note: TIMING_NOTE.no_finish };
  const span = Date.parse(end.at) - Date.parse(submitted.at);
  if (!(span > 0)) return { ...base, events, running: detail.duration_running };
  const startPercent = ((Date.parse(detail.started_at) - Date.parse(submitted.at)) / span) * 100;
  return { drawn: true, events, startPercent, running: detail.duration_running, note: null, waiting: false };
}

/** Whatever timestamps are not contradicted, in the order the job lived them. */
function availableEvents(detail: JobDetail, submitted: TimelineEvent): TimelineEvent[] {
  const events = [submitted];
  if (detail.started_at) events.push({ key: "started", at: detail.started_at });
  if (detail.finished_at) events.push({ key: "finished", at: detail.finished_at });
  return events;
}

/* The cost disclosure's two span lanes. */

export interface Lane { startPercent: number; endPercent: number; start: string; end: string }

export interface Lanes {
  tool: Lane;
  compute: Lane;
  /** The compute lane ends at the snapshot because the machine was still in use. */
  computeOngoing: boolean;
}

/**
 * Tool execution beside the machine's observed lifetime, on one time scale. Only
 * drawn where one execution belongs to one machine that is not the Galaxy server.
 */
export function buildLanes(detail: JobDetail): Lanes | null {
  const [resource] = detail.resources;
  if (detail.resources.length !== 1 || !resource.resource_started_at) return null;
  if (resource.capacity_relationship === "existing") return null;
  if (logicalExecutions(detail).length !== 1 || detail.timing_issue) return null;
  if (!detail.started_at) return null;
  const toolEnd = detail.finished_at ?? (detail.duration_running ? detail.duration_cutoff : null);
  const computeOngoing = !resource.resource_finished_at && detail.duration_running;
  const computeEnd = resource.resource_finished_at ?? (computeOngoing ? detail.duration_cutoff : null);
  if (!toolEnd || !computeEnd) return null;
  const moments = [detail.started_at, toolEnd, resource.resource_started_at, computeEnd].map(Date.parse);
  if (moments.some(Number.isNaN)) return null;
  const from = Math.min(...moments);
  const span = Math.max(...moments) - from;
  if (!(span > 0)) return null;
  const lane = (start: string, end: string): Lane => ({
    start, end,
    startPercent: ((Date.parse(start) - from) / span) * 100,
    endPercent: ((Date.parse(end) - from) / span) * 100,
  });
  if (Date.parse(toolEnd) < Date.parse(detail.started_at) || Date.parse(computeEnd) < Date.parse(resource.resource_started_at)) return null;
  return { tool: lane(detail.started_at, toolEnd), compute: lane(resource.resource_started_at, computeEnd), computeOngoing };
}

/* Executions. */

export interface ExecutionRow {
  execution: JobExecution;
  title: string;
  /** Its timing is recorded; undated executions sort last and say so. */
  dated: boolean;
}

export interface ExecutionHistory {
  heading: "Runs";
  summary: string;
  rows: ExecutionRow[];
}

function executionOrder(first: JobExecution, second: JobExecution): number {
  const dated = (execution: JobExecution) => (execution.tool_started_at === null ? 1 : 0);
  return dated(first) - dated(second)
    || (first.tool_started_at ?? "").localeCompare(second.tool_started_at ?? "")
    || (first.task_index ?? 0) - (second.task_index ?? 0)
    || (first.attempt_ordinal ?? 0) - (second.attempt_ordinal ?? 0)
    || first.id.localeCompare(second.id);
}

/**
 * The job's logical executions, or null when one execution needs no history.
 * Several tasks of one submission are parallel work, not retries.
 */
export function executionHistory(detail: JobDetail): ExecutionHistory | null {
  const executions = logicalExecutions(detail).sort(executionOrder);
  if (executions.length < 2) return null;
  const parallel = new Set(executions.map(execution => execution.task_index)).size > 1;
  const rows = executions.map((execution, position) => ({
    execution, title: `Run ${position + 1}`, dated: execution.tool_started_at !== null,
  }));
  return {
    heading: "Runs",
    summary: parallel
      ? `${pluralize(executions.length, "run")}, in parallel`
      : `${jobStateLabel(detail.state)} after ${pluralize(executions.length, "run")}`,
    rows,
  };
}
