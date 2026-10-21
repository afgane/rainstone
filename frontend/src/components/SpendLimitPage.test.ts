import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GUARD } from "../test/spendGuard";
import SpendLimitPage from "./SpendLimitPage.vue";

afterEach(() => vi.unstubAllGlobals());

describe("Batch limit page", () => {
  it("requires an explicit choice and confirmation before saving a cumulative limit", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...GUARD, revision: 1, limit: "5.00" })));
    vi.stubGlobal("fetch", fetch);
    const page = mount(SpendLimitPage, { props: { guard: GUARD, error: "", timezone: "UTC" } });
    expect(page.text()).toContain("Batch compute only");
    expect(page.text()).toContain("$3.12");
    expect(page.text()).toContain("Earlier costs");
    expect(page.text()).toContain("Workflow runs containing stopped jobs stay failed");
    await page.get("#batch-limit-amount").setValue("5.00");
    await page.get("form").trigger("submit");
    expect(page.get('[role="alert"]').text()).toContain("Choose whether");
    await page.get('input[value="finish"]').setValue();
    await page.get("form").trigger("submit");
    expect(fetch).not.toHaveBeenCalled();
    expect(page.get(".limit-confirmation").text()).toContain("including $3.12 recorded so far");
    expect(page.get(".limit-confirmation").text()).toContain("without an upper bound");
    await page.get(".limit-confirmation .primary").trigger("click");
    await flushPromises();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ revision: 0, limit: "5.00", stop_jobs: false });
    expect(page.emitted("saved")?.[0][0]).toMatchObject({ limit: "5.00" });
    expect(page.get('[role="status"]').text()).toContain("saved");
    page.unmount();
  });

  it("keeps missing cost, stale evidence and incomplete cleanup explicit", () => {
    const page = mount(SpendLimitPage, { props: { guard: { ...GUARD, limit: "5", stop_jobs: true,
      triggered_at: "2026-10-21T12:01:00Z", stale: true,
      snapshot: { ...GUARD.snapshot, amount: null, incomplete_jobs: 2, unpriced_running_resources: 1 },
      cancellations: [{ job_id: "job", requested_at: "now", verified_at: null, error: "Waiting for Batch VM cleanup", attempts: 2, cost_reconciled: false }],
    }, error: "", timezone: "UTC" } });
    expect(page.text()).toContain("Not available");
    expect(page.text()).toContain("2 jobs need cost data");
    expect(page.text()).toContain("out of date");
    expect(page.text()).toContain("Spending may continue");
    expect(page.text()).not.toContain("cleanup verified for");
    expect(page.get('button[type="submit"]').attributes("disabled")).toBeDefined();
    page.unmount();
  });
});
