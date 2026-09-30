import type { RunJob } from "./api";
import { sumAmounts } from "./costBreakdown";
import { environmentLabel } from "./vocabulary";

/** Cost evidence a job can still be missing, whatever amount it shows so far. */
const INCOMPLETE = new Set(["partial", "unpriced", "in_progress", "unavailable", "not_started"]);

export interface JobGroup {
  environment: string;
  label: string;
  /** In run order, every distinct job once. */
  jobs: RunJob[];
  /** Whether a cost is said per job here; the server's jobs added none. */
  showsCost: boolean;
  /** The known cost of the group's jobs, or null when none is known. */
  subtotal: string | null;
  /** Jobs whose cost is unknown or still incomplete. */
  incomplete: number;
}

const FIRST = ["dedicated", "existing"];
const LAST = ["multiple", "unknown"];

/** Dedicated compute, then the server, then other verified places, then several, then unknown. */
function rank(environment: string): number {
  const first = FIRST.indexOf(environment);
  if (first >= 0) return first;
  const last = LAST.indexOf(environment);
  return last >= 0 ? 1000 + last : FIRST.length;
}

/**
 * Whether a group states a cost for each job. The server's jobs added none, so
 * a column of zeros would say nothing; anywhere else an unknown cost is shown
 * as unknown rather than dropped, and an unverified place shows the column
 * only when some job's amount can actually be stated.
 */
function statesCost(environment: string, jobs: RunJob[]): boolean {
  if (environment === "existing") return false;
  if (environment === "dedicated" || environment === "elastic_shared") return true;
  return jobs.some(job => job.amount !== null);
}

export function groupJobs(jobs: RunJob[]): JobGroup[] {
  const groups = new Map<string, RunJob[]>();
  for (const job of jobs) {
    const members = groups.get(job.environment);
    if (members) members.push(job);
    else groups.set(job.environment, [job]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0))
    .map(([environment, members]) => {
      const inOrder = [...members].sort((a, b) => a.order - b.order || (a.id < b.id ? -1 : 1));
      return {
        environment, label: environmentLabel(environment), jobs: inOrder,
        showsCost: statesCost(environment, inOrder),
        subtotal: sumAmounts(inOrder.map(job => job.amount)),
        incomplete: inOrder.filter(job => job.amount === null || INCOMPLETE.has(job.quality)).length,
      };
    });
}
