import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GUARD } from "../test/spendGuard";
import SpendLimitPage from "./SpendLimitPage.vue";

afterEach(() => vi.unstubAllGlobals());

describe("Batch limit page", () => {
  it("explains an early pause without calling the unused ceiling spendable", () => {
    const page = mount(SpendLimitPage, { props: { guard: { ...GUARD, limit: "2",
      triggered_at: "2026-10-23T15:37:55Z", trigger: { amount: "1.255114888284", margin: "0.802796158334" },
      snapshot: { ...GUARD.snapshot, amount: "1.236248995708" },
    }, error: "", timezone: "UTC" } });
    expect(page.get(".limit-pause-explanation").text()).toContain("Batch paused at $1.26 recorded");
    expect(page.get(".limit-pause-explanation").text()).toContain("$0.80 reserved");
    expect(page.get(".limit-budget-readout").text()).toContain("Recorded spend $1.24");
    expect(page.get(".limit-budget-readout").text()).toContain("Below ceiling $0.76");
    expect(page.get(".limit-budget-readout").text()).not.toContain("Remaining");
    page.unmount();
  });
  it("saves the cumulative ceiling directly with the selected job behavior", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...GUARD, revision: 1, limit: "5.00", stop_jobs: true })));
    vi.stubGlobal("fetch", fetch);
    const page = mount(SpendLimitPage, { props: { guard: GUARD, error: "", timezone: "UTC" } });
    expect(page.text()).toContain("including what you’ve already spent");
    expect(page.text()).toContain("$3.12");
    expect(page.get("details").attributes("open")).toBeUndefined();
    await page.get("#batch-limit-amount").setValue("5.00");
    expect(page.get(".limit-budget-readout").text()).toContain("Remaining $1.88");
    expect((page.get("#batch-limit-slider").element as HTMLInputElement).value).toBe("5");
    await page.get('[role="switch"]').setValue(true);
    expect(page.get("#limit-job-effect").text()).toContain("Unfinished work is lost");
    await page.get("form").trigger("submit");
    await flushPromises();
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ revision: 0, limit: "5.00", stop_jobs: true });
    expect(page.emitted("saved")?.[0][0]).toMatchObject({ limit: "5.00" });
    expect(page.get('[role="status"]').text()).toContain("saved");
    await page.setProps({ guard: { ...GUARD, limit: "5.00", revision: 1 } });
    expect(page.get('button[type="submit"]').text()).toBe("Update limit");
    page.unmount();
  });

  it("clamps dragging above spend and extends the scale for typed ceilings", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const page = mount(SpendLimitPage, { props: { guard: GUARD, error: "", timezone: "UTC" } });
    await page.get("#batch-limit-slider").setValue("0");
    expect((page.get("#batch-limit-amount").element as HTMLInputElement).value).toBe("3.13");
    expect((page.get("#batch-limit-slider").element as HTMLInputElement).value).toBe("3.13");
    await page.get("#batch-limit-amount").setValue("3.12");
    await page.get("form").trigger("submit");
    expect(fetch).not.toHaveBeenCalled();
    expect(page.get('[role="alert"]').text()).toContain("at least $3.13");
    await page.get("#batch-limit-amount").setValue("5000");
    expect(Number(page.get("#batch-limit-slider").attributes("max"))).toBeGreaterThan(5000);
    const maximum = page.get("#batch-limit-slider").attributes("max");
    await page.get("#batch-limit-slider").setValue("4000");
    expect(page.get("#batch-limit-slider").attributes("max")).toBe(maximum);
    expect((page.get("#batch-limit-amount").element as HTMLInputElement).value).toBe("4000.00");
    page.unmount();
  });

  it("preserves edits and the original revision when refreshed data conflicts", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "Limit changed" }), { status: 409 }));
    vi.stubGlobal("fetch", fetch);
    const page = mount(SpendLimitPage, { props: { guard: GUARD, error: "", timezone: "UTC" } });
    await page.get("#batch-limit-amount").setValue("10");
    await page.setProps({ guard: { ...GUARD, revision: 2, limit: "20" } });
    await page.get("form").trigger("submit");
    await flushPromises();
    expect(JSON.parse(fetch.mock.calls[0][1].body).revision).toBe(0);
    expect(page.get('[role="alert"]').text()).toContain("Reload saved limit");
    expect((page.get("#batch-limit-amount").element as HTMLInputElement).value).toBe("10");
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
