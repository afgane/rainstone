import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { CurrentLaunch, Summary } from "../../api";
import OverviewFigures from "./OverviewFigures.vue";

const LAUNCH = {
  launch_at: "2026-09-03T08:00:00Z", ended_at: null, stale: false, stale_reason: null,
  hourly_rate: "0.3806", elapsed_seconds: "2347200", completeness: "complete", total_since_launch: "198.40", known_subtotal: "198.40",
  as_of: "2026-09-29T12:00:00Z",
} as unknown as CurrentLaunch;
const SUMMARY = {
  amount: "216.74", job_count: 531, unpriced_job_count: 0, can_view_infrastructure: true,
  current_launch: LAUNCH, imported_snapshot: null,
} as unknown as Summary;

function figures(summary: Partial<Summary> = {}, launch: Partial<CurrentLaunch> | null = {}) {
  return mount(OverviewFigures, {
    props: {
      summary: {
        ...SUMMARY, current_launch: launch === null ? null : { ...LAUNCH, ...launch }, ...summary,
      } as Summary,
      periodText: "Sep 1, 2026 – Sep 29, 2026 · UTC",
    },
  });
}

describe("OverviewFigures", () => {
  it("puts run compute and the Galaxy server side by side as peers", () => {
    const wrapper = figures();
    const cards = wrapper.findAll(".cost-card");
    expect(cards).toHaveLength(2);
    expect(cards[0].find(".eyebrow").text()).toBe("Run compute");
    expect(cards[0].find(".figure-amount").text()).toBe("$216.74");
    expect(cards[0].text()).toContain("Sep 1, 2026 – Sep 29, 2026");
    expect(cards[1].find(".eyebrow").text()).toBe("Galaxy server");
    expect(cards[1].find(".figure-amount").text()).toBe("$198.40$0.38/hour while running");
    expect(cards[1].find(".figure-qualifier").text()).toBe("$0.38/hour while running");
    expect(cards[1].text()).toContain("27 days 4 h since launch");
    // Two separately scoped costs: said to be additional, never summed.
    expect(wrapper.find(".cost-relation").text()).toBe(
      "Your compute cost has two parts: run compute, for the machines started to run your jobs, and the Galaxy "
      + "server, which runs whether or not jobs do.",
    );
    expect(wrapper.text()).not.toContain("$414");
    expect(wrapper.text()).not.toContain("=");
  });

  it("says how long the server has been up, not when it launched", () => {
    expect(figures({}, { elapsed_seconds: "18720" }).text()).toContain("5 h 12 min since launch");
    expect(figures({}, { elapsed_seconds: null }).text()).toContain("Time since launch unavailable");
    expect(figures({}, { hourly_rate: null }).find(".figure-qualifier").exists()).toBe(false);
  });

  it("leaves the launch time, cutoff and explanations to the server page", () => {
    const text = figures().text();
    expect(text).not.toContain("Sep 3");
    expect(text).not.toContain("8:00");
    expect(text).not.toContain("idle");
  });

  it("opens the Galaxy server page from Server details", async () => {
    const wrapper = figures();
    await wrapper.find(".cost-card button").trigger("click");
    expect(wrapper.emitted("server")).toHaveLength(1);
  });

  it("says when the run cost leaves out unpriced work", () => {
    const card = figures({ unpriced_job_count: 4, in_progress_job_count: 1, unrecorded_job_count: 3 }).find(".cost-card");
    expect(card.text()).toContain("recorded so far");
    expect(card.text()).toContain("1 job still in progress");
    expect(card.text()).toContain("3 jobs whose cost was not recorded are not included");
    // Nothing the reader could act on is implied.
    expect(card.text()).not.toContain("need cost data");
  });

  it("names only the kinds of missing cost there are", () => {
    const pending = figures({ unpriced_job_count: 2, in_progress_job_count: 2, unrecorded_job_count: 0 }).find(".cost-card");
    expect(pending.text()).toContain("2 jobs still in progress");
    expect(pending.text()).not.toContain("not recorded");
    const settled = figures({ unpriced_job_count: 0, in_progress_job_count: 0, unrecorded_job_count: 1 }).find(".cost-card");
    expect(settled.text()).toContain("1 job whose cost was not recorded is not included");
    expect(settled.text()).not.toContain("in progress");
  });

  it("never shows an unavailable cost as zero, and says so when nothing ran", () => {
    expect(figures({ amount: null, job_count: 4, unpriced_job_count: 4 }).find(".figure-amount").text())
      .toBe("Not available");
    const quiet = figures({ amount: null, job_count: 0 });
    expect(quiet.find(".figure-amount").text()).toBe("No jobs");
    expect(quiet.text()).not.toContain("$0.00");
  });

  it("keeps the server's partial, unavailable and unknown-launch states honest", () => {
    const partial = figures({}, { completeness: "partial", total_since_launch: null, known_subtotal: "12.5" });
    expect(partial.findAll(".cost-card")[1].text()).toContain("$12.50");
    expect(partial.findAll(".cost-card")[1].text()).toContain("recorded so far");
    const missing = figures({}, null);
    expect(missing.findAll(".cost-card")[1].find(".figure-amount").text()).toBe("Not available");
    expect(missing.findAll(".cost-card")[1].text()).toContain("Launch time unavailable");
    const unknown = figures({}, { launch_at: null, completeness: "unavailable", total_since_launch: null });
    expect(unknown.findAll(".cost-card")[1].text()).toContain("Launch time unavailable");
    expect(unknown.findAll(".cost-card")[1].find(".figure-amount").text()).toMatch(/^Not available/);
  });

  it("qualifies a stopped, stale or imported server in a quiet word", () => {
    expect(figures({}, { ended_at: "2026-09-20T00:00:00Z" }).find(".quiet-label").text()).toBe("Stopped");
    expect(figures({}, { stale: true }).find(".quiet-label").text()).toBe("Stale");
    const imported = figures({ imported_snapshot: { captured_at: null } as Summary["imported_snapshot"] }, { stale: true });
    expect(imported.find(".quiet-label").text()).toBe("Snapshot");
    expect(imported.find(".error").exists()).toBe(false);
  });

  it("shows only run compute to a viewer who may not see the server", () => {
    const wrapper = figures({ can_view_infrastructure: false, current_launch: null });
    expect(wrapper.findAll(".cost-card")).toHaveLength(1);
    expect(wrapper.find(".cost-plus").exists()).toBe(false);
    expect(wrapper.find(".cost-relation").exists()).toBe(false);
    expect(wrapper.text()).not.toContain("Galaxy server");
  });
});
