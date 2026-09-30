import type { CostBreakdownFacts, CostEntity, RunJob } from "./api";
import { environmentLabel, repeatedToolName } from "./vocabulary";

/**
 * Where a workflow run's cost went, as at most a handful of named parts drawn
 * on a fixed grid of squares.
 *
 * Money is added and divided as scaled integers, never as floating point, so
 * the parts always add up to the run's known cost and the squares to exactly
 * one hundred. Formatting happens last, elsewhere.
 */

export const CELL_COUNT = 100;
export const COLUMNS = 20;

/** Initial defaults, to be judged by eye; they are not fixed by anything but taste. */
export const THRESHOLDS = {
  /** Name parts until they hold this much of the known cost... */
  coveragePercent: 95,
  /** ...but never more than this many, and none below the grid's resolution. */
  maxNamed: 8,
  minimumSharePercent: 1,
  /** A remainder smaller than this is named rather than pooled, when it can be. */
  trivialRemainderPercent: 2,
} as const;

const DECIMAL = /^(-)?(\d+)(?:\.(\d+))?$/;

export function scaleOf(amount: string): number {
  return DECIMAL.exec(amount)?.[3]?.length ?? 0;
}

/** An exact decimal string as an integer count of 10^-scale, or null when it is not a plain decimal. */
export function toScaled(amount: string, scale: number): bigint | null {
  const match = DECIMAL.exec(amount);
  if (!match) return null;
  const [, sign, whole, fraction = ""] = match;
  if (fraction.length > scale) return null;
  const value = BigInt(whole + fraction.padEnd(scale, "0"));
  return sign ? -value : value;
}

export function fromScaled(value: bigint, scale: number): string {
  const negative = value < 0n;
  const digits = (negative ? -value : value).toString().padStart(scale + 1, "0");
  const whole = digits.slice(0, digits.length - scale);
  const fraction = digits.slice(digits.length - scale).replace(/0+$/, "");
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

/** The exact sum of the amounts that are known; null when none is. */
export function sumAmounts(amounts: Array<string | null>): string | null {
  const known = amounts.filter((amount): amount is string => amount !== null);
  if (!known.length) return null;
  const scale = Math.max(...known.map(scaleOf));
  const total = known.reduce((sum, amount) => sum + (toScaled(amount, scale) ?? 0n), 0n);
  return fromScaled(total, scale);
}

export type PartKind = "tool_group" | "vm_session" | "other";

export interface Part {
  /** Stable across reloads, so a link can name the part it opened. */
  key: string;
  kind: PartKind;
  name: string;
  /** Exact, as a plain decimal. */
  amount: string;
  /** Of the known cost, from exact amounts; the squares never feed back into it. */
  share: number;
  cells: number;
  /** Distinct jobs behind the part, in run order. */
  jobIds: string[];
  entityIds: string[];
  toolId: string | null;
  toolVersion: string | null;
  /** One verified environment, or "multiple". */
  environment: string;
  complete: boolean;
  /** What a pooled "Other" holds; empty for any other part. */
  members: Part[];
}

export type EmptyReason = "no-jobs" | "none-paid";

export interface CostComposition {
  /** A chart, nothing to chart, or a breakdown that cannot be trusted. */
  status: "chart" | "empty" | "unavailable";
  reason: string | null;
  emptyReason: EmptyReason | null;
  parts: Part[];
  /** Every part, pooled ones included, by key. */
  byKey: Map<string, Part>;
  /** Each square's part, in the order squares are filled. */
  cellOwners: string[];
  subtotal: string | null;
  knownZeroJobs: number;
  unknownJobs: number;
}

interface Draft {
  key: string;
  kind: PartKind;
  name: string;
  amount: bigint;
  jobIds: string[];
  entityIds: string[];
  toolId: string | null;
  toolVersion: string | null;
  environment: string;
  complete: boolean;
  members: Draft[];
}

const unavailable = (reason: string, facts: CostBreakdownFacts): CostComposition => ({
  status: "unavailable", reason, emptyReason: null, parts: [], byKey: new Map(), cellOwners: [],
  subtotal: null, knownZeroJobs: facts.known_zero_job_count, unknownJobs: facts.unknown_job_count,
});

function byAmountThenKey(a: Draft, b: Draft): number {
  if (a.amount !== b.amount) return a.amount > b.amount ? -1 : 1;
  return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
}

function toolKey(job: RunJob): string {
  return `tool:${job.tool_id}|${job.tool_version ?? ""}|${job.environment}`;
}

/** Gather charges into parts: repeated jobs of one tool pool, a virtual machine stands alone. */
function draftsFrom(entities: CostEntity[], jobs: Map<string, RunJob>, scale: number): Draft[] | string {
  const drafts = new Map<string, Draft>();
  const seen = new Set<string>();
  for (const entity of entities) {
    if (seen.has(entity.id)) continue;
    seen.add(entity.id);
    const amount = toScaled(entity.amount, scale);
    if (amount === null || amount < 0n) return "Some amounts are adjustments that a breakdown cannot show.";
    if (amount === 0n) continue;
    if (entity.currency !== "USD") return "The parts are not all in the same currency.";
    if (entity.kind === "vm_session") {
      drafts.set(`vm:${entity.id}`, {
        key: `vm:${entity.id}`, kind: "vm_session", name: entity.label || "Virtual machine",
        amount, jobIds: [...new Set(entity.job_ids)], entityIds: [entity.id], toolId: null,
        toolVersion: null, environment: entity.environment, complete: entity.complete, members: [],
      });
      continue;
    }
    const job = jobs.get(entity.job_ids[0]);
    if (!job) return "A charge points at a job that is not in this run.";
    const key = toolKey(job);
    const draft = drafts.get(key);
    if (draft) {
      draft.amount += amount;
      draft.entityIds.push(entity.id);
      if (!draft.jobIds.includes(job.id)) draft.jobIds.push(job.id);
      draft.complete &&= entity.complete;
    } else {
      drafts.set(key, {
        key, kind: "tool_group", name: job.tool_name, amount, jobIds: [job.id],
        entityIds: [entity.id], toolId: job.tool_id, toolVersion: job.tool_version,
        environment: job.environment, complete: entity.complete, members: [],
      });
    }
  }
  return [...drafts.values()];
}

function pooled(members: Draft[]): Draft {
  const environments = new Set(members.map(member => member.environment));
  return {
    key: "other", kind: "other", name: "Other",
    amount: members.reduce((sum, member) => sum + member.amount, 0n),
    jobIds: [...new Set(members.flatMap(member => member.jobIds))],
    entityIds: members.flatMap(member => member.entityIds), toolId: null, toolVersion: null,
    environment: environments.size === 1 ? [...environments][0] : "multiple",
    complete: members.every(member => member.complete), members,
  };
}

/** Name the parts that matter; pool the rest, unless the rest is trivial and every piece can stand alone. */
function chooseParts(sorted: Draft[], total: bigint): Draft[] {
  const named: Draft[] = [];
  let covered = 0n;
  for (const draft of sorted) {
    if (named.length >= THRESHOLDS.maxNamed) break;
    if (covered * 100n >= BigInt(THRESHOLDS.coveragePercent) * total) break;
    if (draft.amount * 100n < BigInt(THRESHOLDS.minimumSharePercent) * total) break;
    named.push(draft);
    covered += draft.amount;
  }
  const rest = sorted.slice(named.length);
  if (!rest.length) return named;
  const remainder = rest.reduce((sum, draft) => sum + draft.amount, 0n);
  const trivial = remainder * 100n < BigInt(THRESHOLDS.trivialRemainderPercent) * total;
  const standAlone = named.length + rest.length <= THRESHOLDS.maxNamed
    && rest.every(draft => draft.amount * 100n >= BigInt(THRESHOLDS.minimumSharePercent) * total);
  return trivial && standAlone ? [...named, ...rest] : [...named, pooled(rest)];
}

/** Largest-remainder apportionment: floors first, then the biggest fractions take what is left. */
export function allocateCells(amounts: bigint[], total: bigint, cells = CELL_COUNT): number[] {
  const scaled = amounts.map(amount => amount * BigInt(cells));
  const counts = scaled.map(value => Number(value / total));
  let left = cells - counts.reduce((sum, count) => sum + count, 0);
  const order = scaled.map((value, index) => ({ index, fraction: value % total }))
    .sort((a, b) => (a.fraction === b.fraction ? a.index - b.index : a.fraction > b.fraction ? -1 : 1));
  for (const { index } of order) {
    if (left <= 0) break;
    counts[index] += 1;
    left -= 1;
  }
  if (left !== 0 || counts.some(count => count < 0) || counts.reduce((a, b) => a + b, 0) !== cells) {
    throw new Error("The squares could not be allocated exactly.");
  }
  return counts;
}

function share(amount: bigint, total: bigint): number {
  return Number((amount * 1_000_000_000n) / total) / 1e9;
}

export function composeCost(input: {
  jobs: RunJob[]; cost_entities: CostEntity[]; cost_breakdown: CostBreakdownFacts;
}): CostComposition {
  const facts = input.cost_breakdown;
  if (facts.status === "unavailable") return unavailable(facts.reason || "", facts);
  const empty = (emptyReason: EmptyReason): CostComposition => ({
    status: "empty", reason: null, emptyReason, parts: [], byKey: new Map(), cellOwners: [],
    subtotal: null, knownZeroJobs: facts.known_zero_job_count, unknownJobs: facts.unknown_job_count,
  });
  if (!input.jobs.length) return empty("no-jobs");
  const scale = Math.max(
    0, ...input.cost_entities.map(entity => scaleOf(entity.amount)),
    scaleOf(facts.known_subtotal ?? "0"),
  );
  const jobs = new Map(input.jobs.map(job => [job.id, job]));
  const drafts = draftsFrom(input.cost_entities, jobs, scale);
  if (typeof drafts === "string") return unavailable(drafts, facts);
  if (!drafts.length) return empty("none-paid");

  const total = drafts.reduce((sum, draft) => sum + draft.amount, 0n);
  const expected = facts.known_subtotal === null ? null : toScaled(facts.known_subtotal, scale);
  if (expected !== null && expected !== total) {
    return unavailable("The parts do not add up to the run total.", facts);
  }

  const order = new Map(input.jobs.map(job => [job.id, job.order]));
  const inRunOrder = (draft: Draft) => {
    draft.jobIds.sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0));
    draft.members.forEach(inRunOrder);
  };
  const sorted = [...drafts].sort(byAmountThenKey);
  const chosen = chooseParts(sorted, total);
  chosen.forEach(inRunOrder);

  let counts: number[];
  try {
    counts = allocateCells(chosen.map(draft => draft.amount), total);
  } catch (error) {
    return unavailable((error as Error).message, facts);
  }
  const byKey = new Map<string, Part>();
  const build = (draft: Draft, cells: number): Part => {
    const part: Part = {
      key: draft.key, kind: draft.kind,
      name: draft.kind === "tool_group" ? repeatedToolName(draft.name, draft.jobIds.length) : draft.name,
      amount: fromScaled(draft.amount, scale), share: share(draft.amount, total), cells,
      jobIds: draft.jobIds, entityIds: draft.entityIds, toolId: draft.toolId,
      toolVersion: draft.toolVersion, environment: draft.environment, complete: draft.complete,
      members: draft.members.map(member => build(member, 0)),
    };
    byKey.set(part.key, part);
    return part;
  };
  const parts = chosen.map((draft, index) => build(draft, counts[index]));
  const cellOwners = parts.flatMap(part => Array<string>(part.cells).fill(part.key));
  return {
    status: "chart", reason: null, emptyReason: null, parts, byKey, cellOwners,
    subtotal: fromScaled(total, scale),
    knownZeroJobs: facts.known_zero_job_count, unknownJobs: facts.unknown_job_count,
  };
}

/** Names that two parts share, so the reader can be told which version or place is which. */
export function collidingNames(parts: Part[]): Set<string> {
  const counts = new Map<string, number>();
  for (const part of parts.flatMap(each => [each, ...each.members])) {
    counts.set(part.name, (counts.get(part.name) ?? 0) + 1);
  }
  return new Set([...counts].filter(([, count]) => count > 1).map(([name]) => name));
}

export function partQualifier(part: Part): string {
  return [part.toolVersion ? `version ${part.toolVersion}` : "", environmentLabel(part.environment)]
    .filter(Boolean).join(" · ");
}
