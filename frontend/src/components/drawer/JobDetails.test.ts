import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import type { JobDetail } from "../../api";
import { emptyUse, execution, job, resource } from "../../test/jobDetail";
import JobDetails from "./JobDetails.vue";

const mounted: Array<ReturnType<typeof mount>> = [];
afterEach(() => mounted.splice(0).forEach(wrapper => wrapper.unmount()));

function view(detail: JobDetail = job(), periodLabel = "this month") {
  const wrapper = mount(JobDetails, { attachTo: document.body, props: { detail, timezone: "UTC", periodLabel } });
  mounted.push(wrapper);
  return wrapper;
}

const available = {
  cpu: {
    ...emptyUse().cpu, status: "available" as const, cpu_seconds: "1440", duration_seconds: "600",
    average_cores: "2.4", request_fraction: "0.3",
  },
  memory: {
    ...emptyUse().memory, status: "available" as const, peak_bytes: String(8 * 1024 ** 3), source: "memory.peak",
    request_fraction: "0.25",
  },
};

/** The value beside a timing fact's label. */
function fact(wrapper: ReturnType<typeof view>, label: string) {
  const at = wrapper.findAll(".job-facts dt").map(each => each.text()).indexOf(label);
  return wrapper.findAll(".job-facts dd")[at];
}

function headings(wrapper: ReturnType<typeof view>): string[] {
  return wrapper.findAll("h3").map(each => each.text());
}

describe("JobDetails hierarchy", () => {
  it("reads headline, timing, execution, compute, use, then two collapsed disclosures", () => {
    const wrapper = view(job({ resource_use: emptyUse(available) }));
    const html = wrapper.html();
    const at = (text: string) => html.indexOf(text);
    const order = ["dialog-amount", "Ran for", "job-execution-heading", "job-compute-heading", "job-use-heading",
      "How this cost was estimated", "Technical details"];
    const positions = order.map(at);
    expect(positions.every(position => position >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
    const disclosures = wrapper.findAll("details.job-disclosure");
    expect(disclosures).toHaveLength(2);
    expect(disclosures.every(each => each.attributes("open") === undefined)).toBe(true);
  });

  it("has no runs section for one run and states the job's cost once", () => {
    const wrapper = view();
    expect(headings(wrapper)).not.toContain("Runs");
    expect(wrapper.text().match(/\$0\.77/g)).toHaveLength(1);
  });

  it("puts timing facts in a compact grid, with seconds kept and unavailable never zero", () => {
    const terms = () => view().findAll(".job-facts dt").map(each => each.text());
    expect(terms()).toEqual(["Submitted", "Waited to start", "Ran for"]);
    const wrapper = view(job({ duration_seconds: 612 }));
    expect(fact(wrapper, "Ran for").text()).toContain("10m 12s");
    const unknown = view(job({ duration_seconds: null, before_start_seconds: null }));
    expect(fact(unknown, "Ran for").text()).toContain("—");
    expect(fact(unknown, "Ran for").find(".sr-only").text()).toBe("Duration not available");
  });

  it("shows no duration for work that has not started", () => {
    const wrapper = view(job({
      state: "queued", started_at: null, finished_at: null, duration_seconds: null, before_start_seconds: null,
      attempts: [], resources: [], full_quality: "in_progress", full_job_amount: null,
    }));
    expect(wrapper.findAll(".job-facts dt").map(each => each.text())).toEqual(["Submitted"]);
    expect(wrapper.text()).toContain("Waiting to start");
    expect(wrapper.find(".timeline-graphic").exists()).toBe(false);
  });

  it("calls a running job's elapsed time so far", () => {
    const wrapper = view(job({
      state: "running", finished_at: null, duration_running: true, duration_cutoff: "2026-09-29T01:30:00Z",
      duration_seconds: 1440, full_quality: "in_progress", attempts: [execution({ tool_finished_at: null, duration_running: true })],
    }));
    expect(fact(wrapper, "Ran for").text()).toContain("so far");
    expect(wrapper.text()).toContain("Recorded so far");
    expect(wrapper.text()).toContain("Cost so far");
  });
});

describe("JobDetails cost", () => {
  it("leads with the whole job and compares the period's share numerically", () => {
    const same = view(job({ full_job_amount: "0.77", interval_amount: "0.770000000000" }));
    expect(same.text()).not.toContain("falls inside");
    const part = view(job({ full_job_amount: "0.77", interval_amount: "0.04" }), "the selected dates");
    expect(part.find(".dialog-amount strong").text()).toBe("$0.77");
    expect(part.text()).toContain("$0.04 of it falls inside the selected dates.");
  });

  it("says when the period's share is unknown rather than showing zero", () => {
    const wrapper = view(job({ interval_amount: null }), "the selected dates");
    expect(wrapper.text()).toContain("Its cost inside the selected dates is not available.");
  });

  it("keeps the reason a cost is missing beside the figure, not inside a disclosure", () => {
    const wrapper = view(job({ full_quality: "unavailable", full_job_amount: null, resources: [] }));
    expect(wrapper.find(".dialog-amount strong").text()).toBe("Not available");
    expect(wrapper.find(".explanation").text()).toContain("unavailable rather than zero");
  });

  it("calls an incomplete subtotal what it is", () => {
    const wrapper = view(job({ full_quality: "partial" }));
    expect(wrapper.find(".dialog-amount span").text()).toContain("recorded so far");
    expect(wrapper.find(".explanation").text()).toContain("subtotal");
  });

  it("explains known-zero work on the Galaxy server in its own words", () => {
    const wrapper = view(job({
      full_quality: "known_zero", full_job_amount: "0.000000000000",
      resources: [resource({ capacity_relationship: "existing", machine_type: null, amount: "0" })],
    }));
    expect(wrapper.find(".dialog-amount span").text()).toBe("$0 extra compute · Used your Galaxy server");
    expect(wrapper.find(".explanation").text()).toContain("added no compute charge");
  });

  it("needs no sentence beside a complete estimate", () => {
    expect(view().find(".explanation").exists()).toBe(false);
  });

  it("states the estimate's method and exclusions once, inside its disclosure", () => {
    const text = view().find("details.job-disclosure").text();
    expect(text).toContain("How this cost was estimated");
    expect(text.match(/compute only, in USD/g)).toHaveLength(1);
    expect(text).toContain("Exact amount: 0.77 USD");
  });

  it("draws the tool run beside the machine's lifetime, with the times as text", () => {
    const wrapper = view();
    const lanes = wrapper.findAll(".lane");
    expect(lanes.map(each => each.find(".lane-label").text())).toEqual(["Tool run", "Compute lifetime"]);
    expect(lanes[0].find(".lane-times").text()).toContain("1:06");
    // Same day: the end names no date again.
    expect(lanes[0].find(".lane-times").text().match(/Sep/g)).toHaveLength(1);
    expect(lanes.every(each => each.find(".lane-track").attributes("aria-hidden") === "true")).toBe(true);
  });

  it("breaks several resources into components that say they are parts of the whole", () => {
    const wrapper = view(job({
      resources: [resource({ amount: "0.50" }), resource({ lifetime_id: "l2", resource_key: "vm-2", amount: "0.27" })],
    }));
    expect(wrapper.find("details.job-disclosure").text()).toContain("parts of the job's cost above");
    expect(wrapper.findAll(".resource-amount").map(each => each.text())).toEqual(["$0.50", "$0.27"]);
    expect(wrapper.find(".lanes").exists()).toBe(false);
  });
});

describe("JobDetails compute", () => {
  it("names the verified environment, machine and purchase model", () => {
    const wrapper = view();
    expect(wrapper.find(".compute-environment").text()).toBe("Dedicated cloud compute");
    expect(wrapper.find(".compute-machine").text()).toBe("n2-standard-8 · On-demand");
  });

  it("states the machine's own size apart from what the job requested", () => {
    const wrapper = view(job({
      resources: [resource({
        machine_type: "n2-highmem-8",
        machine_capacity: { vcpu: "8", memory_mib: "65536", gpu: null, source: "published_machine_shape" },
        requested_vcpu: "1", requested_memory_mib: "4096",
      })],
    }));
    expect(wrapper.find(".compute-list").text()).toContain("n2-highmem-8 · On-demand");
    expect(wrapper.find(".compute-list").text()).toContain("Machine capacity: 8 vCPUs · 64 GiB memory");
  });

  it("names a machine's GPUs and says its price includes them", () => {
    const wrapper = view(job({
      resources: [resource({
        machine_type: "g2-standard-4",
        machine_capacity: {
          vcpu: "4", memory_mib: "16384", gpu: { count: "1", model: "NVIDIA L4" }, source: "published_machine_shape",
        },
      })],
    }));
    expect(wrapper.find(".compute-list").text()).toContain("Machine capacity: 4 vCPUs · 16 GiB memory · 1 NVIDIA L4 GPU");
    expect(wrapper.find("details.job-disclosure").text()).toContain("The machine's price includes its GPUs.");
  });

  it("does not mention GPUs for a machine without them", () => {
    expect(view().find("details.job-disclosure").text()).not.toContain("GPU");
  });

  it("gives a machine no size when its type is not a published shape", () => {
    const wrapper = view(job({ resources: [resource({ machine_type: "e2-standard-4", machine_capacity: null })] }));
    expect(wrapper.find(".compute-list").text()).not.toContain("Machine capacity");
  });

  it("keeps the recorded machine, never substituting the server for a missing one", () => {
    const wrapper = view(job({ resources: [resource({ machine_type: null, purchase_model: null })] }));
    expect(wrapper.find(".compute-machine").text()).toBe("Machine type not recorded");
    expect(wrapper.find(".compute-environment").text()).toBe("Dedicated cloud compute");
  });

  it("keeps a purchase model it does not know as recorded", () => {
    expect(view(job({ resources: [resource({ purchase_model: "committed_use" })] })).text()).toContain("committed_use");
  });

  it("says so when no evidence of where it ran was collected", () => {
    const wrapper = view(job({ resources: [] }));
    expect(wrapper.text()).toContain("No evidence of where this ran was collected.");
  });

  it("identifies several machines and what used each", () => {
    const wrapper = view(job({
      resources: [resource(), resource({ lifetime_id: "l2", resource_key: "vm-2", shared_attempt_count: 2 })],
    }));
    expect(wrapper.text()).toContain("This job used 2 machines.");
    expect(wrapper.findAll(".compute-list li")).toHaveLength(2);
    expect(wrapper.text()).toContain("charged once");
  });
});

describe("JobDetails resource use", () => {
  it("shows both comparisons with values, percentages and an average/peak label", () => {
    const wrapper = view(job({ resource_use: emptyUse(available) }));
    const rows = wrapper.findAll(".use-row");
    expect(rows.map(each => each.find(".use-name").text())).toEqual(["Average CPU use", "Peak memory use"]);
    expect(rows[0].text()).toContain("2.4 of 8 requested vCPUs");
    expect(rows[0].text()).toContain("30% on average");
    expect(rows[1].text()).toContain("8 of 32 GiB requested");
    expect(rows[1].text()).toContain("25% at peak");
  });

  it("draws static bars that assistive technology does not see as progress", () => {
    const wrapper = view(job({ resource_use: emptyUse(available) }));
    expect(wrapper.find("[role='progressbar']").exists()).toBe(false);
    expect(wrapper.findAll(".use-track").every(each => each.attributes("aria-hidden") === "true")).toBe(true);
    expect(wrapper.findAll(".use-row").every(each => each.element.tagName === "FIGURE")).toBe(true);
  });

  it("stretches a row past the request and labels the request, keeping the true ratio", () => {
    const wrapper = view(job({
      resource_use: emptyUse({ ...available, cpu: { ...available.cpu, average_cores: "10", request_fraction: "1.25" } }),
    }));
    const row = wrapper.find("[data-row='cpu']");
    expect(row.text()).toContain("125% of request on average");
    expect(row.find(".use-marker").exists()).toBe(true);
    expect(row.find(".use-marker-label").text()).toBe("Requested");
    expect(row.find(".sr-only").text()).toContain("scale is extended");
    expect(wrapper.find("[data-row='memory'] .use-marker").exists()).toBe(false);
    expect(wrapper.text()).toContain("stretched to fit it");
  });

  it("says once that nothing was recorded, rather than drawing two empty bars", () => {
    const wrapper = view();
    expect(wrapper.text()).toContain("Usage measurements were not recorded.");
    expect(wrapper.text()).toContain("Requested: 8 vCPUs · 32 GiB");
    expect(wrapper.find(".use-track").exists()).toBe(false);
  });

  it("renders the one measurement there is and gives the other its own reason", () => {
    const wrapper = view(job({ resource_use: emptyUse({ memory: available.memory }) }));
    expect(wrapper.find("[data-row='memory'] .use-track").exists()).toBe(true);
    expect(wrapper.find("[data-row='cpu'] .use-track").exists()).toBe(false);
    expect(wrapper.find("[data-row='cpu']").text()).toContain("CPU use not recorded.");
  });

  it("keeps a valid measurement when there is no request to compare with", () => {
    const wrapper = view(job({
      resource_use: emptyUse({
        cpu: { ...available.cpu, status: "request_unavailable", reason: "request_missing", requested_vcpu: null, request_fraction: null },
      }),
    }));
    const row = wrapper.find("[data-row='cpu']");
    expect(row.text()).toContain("2.4 vCPUs used on average");
    expect(row.text()).toContain("No request was recorded");
    expect(row.find(".use-track").exists()).toBe(false);
  });

  it("does not compare a retried job's counters", () => {
    const wrapper = view(job({
      resource_use: emptyUse({
        measurement_scope: "unestablished", scope_reason: "several_executions",
        cpu: { ...emptyUse().cpu, status: "unsupported_scope", reason: "several_executions", cpu_seconds: "100" },
      }),
    }));
    expect(wrapper.find("[data-row='cpu']").text()).toContain("more than once");
    expect(wrapper.find(".use-track").exists()).toBe(false);
  });

  it("attributes none of a Galaxy server's usage to the job", () => {
    const wrapper = view(job({
      resource_use: emptyUse({ measurement_scope: "unestablished", scope_reason: "galaxy_server" }),
    }));
    expect(wrapper.find("#job-use-heading").exists()).toBe(true);
    expect(wrapper.text()).toContain("not attributed to individual jobs");
    expect(wrapper.find(".use-row").exists()).toBe(false);
  });

  it("offers a native disclosure for what the measurements mean, for touch and keyboard", () => {
    const wrapper = view(job({ resource_use: emptyUse(available) }));
    const summary = wrapper.findAll("summary").find(each => each.text() === "About these measurements");
    expect(summary).toBeDefined();
    expect(summary!.element.parentElement?.tagName).toBe("DETAILS");
  });
});

describe("JobDetails timeline", () => {
  it("lists every event with its exact time for a screen reader", () => {
    const wrapper = view();
    const events = wrapper.findAll(".timeline-events li");
    expect(events.map(each => each.find(".timeline-label").text())).toEqual(["Submitted", "Started", "Finished"]);
    expect(events[1].find(".sr-only").text()).toContain("1:06:00");
    expect(events[1].find("time").attributes("datetime")).toBe("2026-09-29T01:06:00Z");
    expect(wrapper.find(".timeline-graphic").attributes("aria-hidden")).toBe("true");
  });

  it("names the date wherever the day changes, and the timezone once", () => {
    const wrapper = view(job({
      created_at: "2026-09-28T23:50:00Z", started_at: "2026-09-29T00:10:00Z", finished_at: "2026-09-29T00:40:00Z",
      attempts: [execution({ tool_started_at: "2026-09-29T00:10:00Z", tool_finished_at: "2026-09-29T00:40:00Z" })],
    }));
    const shown = wrapper.findAll(".timeline-events time [aria-hidden]").map(each => each.text());
    expect(shown[0]).toContain("Sep 28");
    expect(shown[1]).toContain("Sep 29");
    expect(shown[2]).not.toContain("Sep");
    expect(wrapper.text()).toContain("Times are shown in UTC.");
  });

  it("lists events without a span, and says why, when times are out of order", () => {
    const wrapper = view(job({ timing_issue: "finished_before_started", duration_seconds: null }));
    expect(wrapper.find(".timeline-graphic").exists()).toBe(false);
    expect(wrapper.text()).toContain("earlier than the recorded start");
    expect(wrapper.findAll(".job-facts dt").map(each => each.text())).not.toContain("Waited to start");
  });

  it("summarizes several executions instead of drawing continuous activity", () => {
    const wrapper = view(job({ attempts: [execution(), execution({ id: "a2", role: "repeat", attempt_ordinal: 2 })] }));
    expect(wrapper.find(".timeline-graphic").exists()).toBe(false);
    expect(wrapper.findAll(".timeline-label").map(each => each.text())).toEqual(["Submitted", "First started", "Last finished"]);
  });
});

describe("JobDetails runs", () => {
  const retried = () => job({
    state: "ok",
    attempts: [
      execution({ id: "a1", outcome: "error", exit_code: 1, provider_outcome: "FAILED", duration_seconds: 30 }),
      execution({
        id: "a2", role: "repeat", attempt_ordinal: 2, tool_started_at: "2026-09-29T01:30:00Z",
        tool_finished_at: "2026-09-29T01:40:00Z",
      }),
      execution({ id: "obs", role: "observation" }),
    ],
  });

  it("summarizes retries and lists each attempt once, never the duplicate observation", () => {
    const wrapper = view(retried());
    expect(headings(wrapper)).toContain("Runs");
    expect(wrapper.text()).toContain("Completed after 2 runs");
    expect(wrapper.findAll(".execution-row")).toHaveLength(2);
  });

  it("opens one attempt in place, with its exact facts, and closes it again", async () => {
    const wrapper = view(retried());
    const [first, second] = wrapper.findAll(".execution-row");
    expect(first.attributes("aria-expanded")).toBe("false");
    await first.trigger("click");
    expect(first.attributes("aria-expanded")).toBe("true");
    expect(wrapper.find(`#${first.attributes("aria-controls")}`).text()).toContain("Exit code1");
    await second.trigger("click");
    expect(first.attributes("aria-expanded")).toBe("false");
    expect(wrapper.findAll(".execution-facts")).toHaveLength(1);
    await second.trigger("click");
    expect(wrapper.find(".execution-facts").exists()).toBe(false);
  });

  it("does not change the job's cost or use when an attempt is opened", async () => {
    const wrapper = view(retried());
    const before = wrapper.find(".dialog-amount").text();
    await wrapper.find(".execution-row").trigger("click");
    expect(wrapper.find(".dialog-amount").text()).toBe(before);
  });

  it("keeps an undated failure in the list, last, saying its timing is not recorded", () => {
    const wrapper = view(job({
      attempts: [
        execution({ id: "lost", outcome: "error", tool_started_at: null, tool_finished_at: null, duration_seconds: null, role: "repeat" }),
        execution({ id: "a2", attempt_ordinal: 2 }),
      ],
    }));
    const rows = wrapper.findAll(".execution-row");
    expect(rows).toHaveLength(2);
    expect(rows[1].text()).toContain("Timing not recorded");
    expect(rows[1].text()).toContain("Failed");
  });

  it("names parallel work as runs too, and says they were in parallel", () => {
    const wrapper = view(job({ attempts: [execution({ task_index: 0 }), execution({ id: "a2", task_index: 1 })] }));
    expect(headings(wrapper)).toContain("Runs");
    expect(wrapper.text()).toContain("2 runs, in parallel");
  });

  it("states a single failed run's recorded outcome without a history", () => {
    const wrapper = view(job({
      state: "error", attempts: [execution({ outcome: "error", exit_code: 137, provider_outcome: "OOM" })],
    }));
    const terms = wrapper.findAll(".job-facts dt").map(each => each.text());
    expect(terms).toContain("Exit code");
    expect(terms).toContain("Provider outcome");
    expect(headings(wrapper)).not.toContain("Runs");
  });
});

describe("JobDetails technical details", () => {
  it("keeps the cost lines' own wording here and not in the plain-language explanation", () => {
    const wrapper = view(job({ full_reason: "Dedicated VM compute; excludes disk | Second line" }));
    const [estimate, technical] = wrapper.findAll("details.job-disclosure");
    expect(estimate.text()).not.toContain("excludes disk");
    expect(technical.text()).toContain("Cost basis");
    expect(technical.text()).toContain("Dedicated VM compute; excludes disk");
    expect(technical.text()).toContain("Second line");
  });

  it("keeps the full identity, evidence and raw metrics with their units", () => {
    const wrapper = view(job({
      resource_use: emptyUse({
        metrics: [{ plugin: "cgroup", name: "memory.peak", value: "8589934592", unit: "bytes" }],
      }),
    }));
    const text = wrapper.findAll("details.job-disclosure")[1].text();
    expect(text).toContain("toolshed/bwa_mem/0.7");
    expect(text).toContain("vm-1");
    expect(text).toContain("compute_insert_complete_to_delete_request");
    expect(text).toContain("cgroup.memory.peak");
    expect(text).toContain("8589934592 bytes");
    expect(text).toContain("r1");
  });
});
