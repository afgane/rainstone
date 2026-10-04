import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { CurrentLaunch, Infrastructure } from "../api";
import { formatDateTime } from "../vocabulary";
import ServerPanel from "./ServerPanel.vue";

const LAUNCH: CurrentLaunch = {
  scope: "Whole server", currency: "USD", resource_uid: "server-1", name: "galaxy",
  machine_type: "t2d-standard-8", region: "us-east4", zone: "us-east4-a", purchase_model: "on_demand",
  machine_capacity: { vcpu: "8", memory_mib: "32768", gpu: null, source: "published_machine_shape" },
  state: "RUNNING", launch_at: "2026-10-02T01:25:00Z", launch_source: "compute.instances.get lastStartTimestamp",
  ended_at: null, elapsed_seconds: "6420", as_of: "2026-10-02T03:12:00Z",
  stale: true, stale_reason: "This is an imported snapshot; its figures stop at the last observation it holds.",
  hourly_rate: "0.38064", hourly_rate_unavailable_reason: null,
  price: { catalog_id: "catalog-1", effective_from: "2026-09-22T07:00:00Z", observed_at: null, kind: "catalog" },
  total_since_launch: "0.678808", known_subtotal: "0.678808", completeness: "complete",
  unavailable_reason: null, calculation_version: "server-v1", calculation_revision: "rev-1",
};

function panel(overrides: Partial<CurrentLaunch> | null = {}, imported = true, timezone = "UTC") {
  return mount(ServerPanel, { props: {
    server: overrides === null ? null : {
      current_launch: { ...LAUNCH, ...overrides }, items: [], amount: null, scope: "Whole server",
      allocation_reason: "", observation_window: {}, observed_coverage: null,
      activity: null,
    } as Infrastructure,
    imported, timezone, now: new Date("2026-10-04T15:42:10Z"),
  } });
}

describe("Galaxy server session", () => {
  it("leads with cost and whole-server capacity, with provenance collapsed", async () => {
    const wrapper = panel();
    expect(wrapper.find(".server-total").text()).toBe("$0.68");
    expect(wrapper.find(".server-duration").text()).toContain("Time running");
    expect(wrapper.find(".server-duration strong").text()).toBe("1 h 47 min");
    expect(wrapper.find(".server-metrics").text()).toContain("$0.38/hour while running");
    expect(wrapper.find(".server-configuration").text()).toContain("8 vCPUs · 32 GiB memory");
    expect(wrapper.find(".server-explanation").text()).toContain("additional to run compute");
    expect(wrapper.findAll("details").every(details => details.attributes("open") === undefined)).toBe(true);
    expect(wrapper.find(".server-facts").text()).toContain("0.38064 USD/hour");
    await wrapper.find(".server-footer button").trigger("click");
    expect(wrapper.emitted("refresh")).toHaveLength(1);
  });

  it("uses recorded timestamps in the chosen timezone without extrapolating the session", () => {
    const wrapper = panel({}, true, "America/New_York");
    const endpoints = wrapper.findAll(".session-timeline li");
    expect(endpoints[0].text()).toContain(formatDateTime(LAUNCH.launch_at!, "America/New_York"));
    expect(endpoints[1].text()).toContain("1 h 47 min");
    expect(endpoints[2].text()).toContain(formatDateTime(LAUNCH.as_of!, "America/New_York"));
    expect(wrapper.find(".server-state").text()).toContain("Snapshot");
    expect(wrapper.find(".server-state").text()).toContain("Running at the last observation");
    expect(wrapper.find(".server-notice").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("stale");
  });

  it("shows delayed live observations as a notice", () => {
    const wrapper = panel({ stale_reason: "The server was last observed 20 minutes ago; the total stops there." }, false);
    expect(wrapper.find('[role="status"]').text()).toContain("20 minutes ago");
    expect(wrapper.find(".quiet-label").exists()).toBe(false);
  });

  it("keeps partial and unavailable costs distinct from zero", () => {
    const partial = panel({ completeness: "partial", total_since_launch: null, known_subtotal: "0.12",
      unavailable_reason: "Time before the available price is not included." });
    expect(partial.find(".server-total").text()).toBe("$0.12");
    expect(partial.find(".server-cost-label").text()).toContain("recorded so far");
    expect(partial.find(".server-notice").text()).toContain("not included");
    const missing = panel({ completeness: "unavailable", total_since_launch: null, known_subtotal: null,
      hourly_rate: null, hourly_rate_unavailable_reason: "No price recorded", unavailable_reason: "Cost not recorded" });
    expect(missing.find(".server-total").text()).toBe("Not available");
    expect(missing.find(".server-summary").text()).toContain("No price recorded");
    expect(missing.text()).not.toContain("$0.00");
    expect(panel({ total_since_launch: "0.001" }).find(".server-total").text()).toBe("less than $0.01");
    expect(panel({ total_since_launch: "0" }).find(".server-total").text()).toBe("$0.00");
    const noObservation = panel({ completeness: "unavailable", total_since_launch: null, hourly_rate: null,
      unavailable_reason: "No observation recorded", hourly_rate_unavailable_reason: "No observation recorded" });
    expect(noObservation.findAll(".server-notice")).toHaveLength(1);
  });

  it("does not invent capacity or running time when observations are absent", () => {
    const wrapper = panel(null, false);
    expect(wrapper.find(".server-total").text()).toBe("Not available");
    expect(wrapper.find(".server-configuration").text()).toContain("Not available");
    expect(wrapper.find(".server-duration strong").text()).toBe("Not available");
    expect(wrapper.find(".session-timeline").text()).toContain("Start time unavailable");
    expect(wrapper.find(".session-timeline").text()).toContain("No observation available");
    expect(panel({ machine_capacity: null }).find(".server-configuration").text()).toContain("Not available");
  });

  it("describes a stopped session without saying the server is still running", () => {
    const wrapper = panel({ state: "TERMINATED", ended_at: LAUNCH.as_of, stale: false }, false);
    expect(wrapper.find(".server-state").text()).toBe("Stopped");
    expect(wrapper.find(".server-duration strong").text()).toBe("1 h 47 min");
    expect(wrapper.find('[role="status"]').exists()).toBe(false);
  });

  it("gives the current time in UTC beside Refresh, whatever the report's timezone", () => {
    const footer = panel({}, true, "America/New_York").find(".server-footer").text();
    expect(footer).toMatch(/Now .*Oct 4, 2026.*3:42.*UTC/);
    expect(footer).toMatch(/UTC · Refresh$/);
  });
});
