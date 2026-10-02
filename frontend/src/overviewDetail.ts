import { parseWindowId, windowId, windowLabel, type JobWindow } from "./jobsView";

/**
 * What an Overview drawer explains: one block of the chart, for its exact
 * interval, or the whole selected period. It travels in the address as one
 * drawer identifier, so a link reopens the same scope.
 */
export type OverviewScope =
  | { scope: "interval"; category: "runs" | "individual"; window: JobWindow }
  | { scope: "period"; category: "runs" | "tools" };

export function overviewId(descriptor: OverviewScope): string {
  return descriptor.scope === "period"
    ? `period|${descriptor.category}`
    : `interval|${descriptor.category}|${windowId(descriptor.window)}`;
}

export function parseOverviewId(id: string): OverviewScope | null {
  const [scope, category, ...rest] = id.split("|");
  if (scope === "period" && rest.length === 0 && (category === "runs" || category === "tools")) {
    return { scope, category };
  }
  if (scope !== "interval" || (category !== "runs" && category !== "individual")) return null;
  const window = parseWindowId(rest.join("|"));
  return window ? { scope, category, window } : null;
}

/** The request parameters that select a descriptor's scope; the report's own filters come separately. */
export function overviewParams(descriptor: OverviewScope, offset: number, pageSize: number): URLSearchParams {
  const params = new URLSearchParams({ scope: descriptor.scope, kind: descriptor.category });
  if (descriptor.scope === "interval") {
    params.set("window_from", descriptor.window.from);
    params.set("window_to", descriptor.window.to);
    params.set("limit", String(pageSize));
    params.set("offset", String(offset));
  } else {
    params.set("offset", "0");
  }
  return params;
}

/** "Workflow runs · Sep 28" or "Jobs outside workflows · Week of Sep 21". */
export function intervalTitle(descriptor: Extract<OverviewScope, { scope: "interval" }>, timezone: string): string {
  const name = descriptor.category === "runs" ? "Workflow runs" : "Jobs outside workflows";
  return `${name} · ${windowLabel(descriptor.window, timezone)}`;
}

export function intervalNoun(descriptor: Extract<OverviewScope, { scope: "interval" }>): string {
  return `this ${descriptor.window.unit}`;
}
