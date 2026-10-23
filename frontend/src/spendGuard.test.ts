import { describe, expect, it } from "vitest";
import { stateFromUrl, urlQuery } from "./api";
import { minimumSpendLimit, spendLimitPercent, triggersImmediately } from "./spendGuard";
import { batchLimitLabel } from "./vocabulary";

import { GUARD } from "./test/spendGuard";

describe("Batch limit presentation", () => {
  it("fills by recorded spend, clamps overspend and leaves unknown spend unfilled", () => {
    expect(spendLimitPercent({ ...GUARD, limit: "5" })).toBeCloseTo(62.4);
    expect(spendLimitPercent({ ...GUARD, limit: "2" })).toBe(100);
    expect(spendLimitPercent(GUARD)).toBeNull();
    expect(spendLimitPercent({ ...GUARD, limit: "5", source_changed: true })).toBeNull();
    expect(spendLimitPercent({ ...GUARD, limit: "5", snapshot: { ...GUARD.snapshot, amount: null } })).toBeNull();
  });
  it("selects the first whole-cent ceiling strictly above recorded spend", () => {
    expect(minimumSpendLimit("3.120000000001")).toBe("3.13");
    expect(minimumSpendLimit("3.129999999999")).toBe("3.13");
    expect(minimumSpendLimit("3.13")).toBe("3.14");
    expect(minimumSpendLimit("0E-12")).toBe("0.01");
    expect(minimumSpendLimit(null)).toBe("0.01");
  });
  it("compares projected spend without rounding away sub-cent differences", () => {
    expect(triggersImmediately("4.749999999999", "0.25", "5.00")).toBe(false);
    expect(triggersImmediately("4.750000000000", "0.25", "5.00")).toBe(true);
    expect(triggersImmediately("0", "0.25", "0.10")).toBe(true);
    expect(triggersImmediately(null, "0.25", "5.00")).toBe(false);
  });
  it("keeps a reproducible limit URL with the existing report dates", () => {
    const state = stateFromUrl("?view=limit&period=last-month&timezone=UTC");
    expect(state.view).toBe("limit");
    expect(stateFromUrl(`?${urlQuery(state)}`)).toMatchObject({ view: "limit", period: "last-month" });
  });
  it("labels all three masthead states and never turns missing cost into zero", () => {
    expect(batchLimitLabel(GUARD)).toBe("Set a Batch spend limit");
    expect(batchLimitLabel({ ...GUARD, limit: "5" })).toBe("Batch limit $5.00 · $3.12 recorded");
    expect(batchLimitLabel({ ...GUARD, limit: "5", triggered_at: "now" })).toBe("New Batch jobs paused");
    expect(batchLimitLabel({ ...GUARD, limit: "5", snapshot: { ...GUARD.snapshot, amount: null } })).toContain("Not available");
  });
});
