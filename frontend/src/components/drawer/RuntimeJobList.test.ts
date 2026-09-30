import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { resetJobs, runJob } from "../../test/runDetail";
import RuntimeJobList from "./RuntimeJobList.vue";

function list(jobs: ReturnType<typeof runJob>[]) {
  return mount(RuntimeJobList, { attachTo: document.body, props: { jobs } });
}
const headings = (wrapper: ReturnType<typeof list>) => wrapper.findAll("h4").map(node => node.text());

beforeEach(resetJobs);
afterEach(() => { document.body.innerHTML = ""; });

describe("the jobs of a run, grouped by where they ran", () => {
  it("orders the places and counts the jobs in each", () => {
    const wrapper = list([
      runJob("a", null, { environment: "unknown", capacities: [] }),
      runJob("b", "0", { environment: "existing", capacities: ["existing"] }),
      runJob("c", "1"), runJob("d", "2"),
    ]);
    expect(headings(wrapper)).toEqual([
      "Dedicated cloud compute · 2 jobs", "Your Galaxy server · 1 job", "Not established · 1 job",
    ]);
  });

  it("lists three repeated jobs of one tool as three separate rows", () => {
    const wrapper = list([runJob("wig_to_bigWig", "0.004"), runJob("wig_to_bigWig", "0.004"), runJob("wig_to_bigWig", "0.004")]);
    const rows = wrapper.findAll(".job-row");
    expect(rows).toHaveLength(3);
    expect(new Set(rows.map(each => each.attributes("data-job-id"))).size).toBe(3);
    expect(wrapper.text()).not.toContain("×3");
  });

  it("keeps run order within a group", () => {
    const second = runJob("second", "1", { order: 2 });
    const first = runJob("first", "1", { order: 1 });
    const wrapper = list([second, first]);
    expect(wrapper.findAll(".job-title").map(node => node.text())).toEqual(["first", "second"]);
  });

  it("gives dedicated compute a cost column and a subtotal", () => {
    const wrapper = list([runJob("a", "0.81"), runJob("b", "0.19")]);
    expect(wrapper.find(".job-list").attributes("data-with-cost")).toBe("true");
    expect(wrapper.findAll(".job-cost").map(node => node.text())).toEqual(["$0.81", "$0.19"]);
    // The figure sits on the heading's line, not on a row of its own.
    expect(wrapper.find(".group-head .group-cost").text()).toContain("$1.00");
    expect(wrapper.find(".group-summary").exists()).toBe(false);
  });

  it("says once, and shows no cost column, for the jobs that used the server", () => {
    const server = { environment: "existing", capacities: ["existing"] };
    const wrapper = list([runJob("a", "0", server), runJob("b", "0", server), runJob("c", "0", server)]);
    expect(wrapper.find(".job-list").attributes("data-with-cost")).toBe("false");
    expect(wrapper.findAll(".job-cost")).toHaveLength(0);
    expect(wrapper.text()).not.toContain("$0.00");
    expect(wrapper.find(".group-cost").exists()).toBe(false);
    expect(wrapper.text().match(/added no compute charge/g)).toHaveLength(1);
  });

  it("labels a subtotal that leaves out unpriced work", () => {
    const wrapper = list([runJob("a", "0.50"), runJob("b", null)]);
    expect(wrapper.find(".group-head .group-cost").text()).toContain("$0.50");
    expect(wrapper.find(".group-summary").text()).toBe("Recorded so far · 1 job still needs cost data");
    expect(wrapper.findAll(".job-cost").map(node => node.text())).toEqual(["$0.50", "—"]);
  });

  it("does not claim a known zero for a place that has not been verified", () => {
    const wrapper = list([runJob("a", null, { environment: "unknown", capacities: [] })]);
    expect(wrapper.text()).not.toContain("no compute charge");
    expect(wrapper.find(".group-summary").text()).toBe("1 job still needs cost data");
    expect(wrapper.find(".job-list").attributes("data-with-cost")).toBe("false");
  });

  it("puts a job that ran in several places in one group of its own", () => {
    const wrapper = list([runJob("a", "2", { environment: "multiple", capacities: ["dedicated", "existing"] })]);
    expect(headings(wrapper)).toEqual(["Multiple environments · 1 job"]);
    expect(wrapper.findAll(".job-row")).toHaveLength(1);
  });

  it("shows a large group a page at a time and keeps every job reachable", async () => {
    const wrapper = list(Array.from({ length: 230 }, (_, index) => runJob(`tool ${index}`, "0.01")));
    expect(wrapper.findAll(".job-row")).toHaveLength(100);
    expect(wrapper.text()).toContain("Showing 100 of 230 jobs");
    await wrapper.find("button.link-button").trigger("click");
    expect(wrapper.findAll(".job-row")).toHaveLength(200);
    await wrapper.find("button.link-button").trigger("click");
    expect(wrapper.findAll(".job-row")).toHaveLength(230);
    expect(wrapper.find("button.link-button").exists()).toBe(false);
  });

  it("opens the job that was pressed", async () => {
    const job = runJob("a", "1");
    const wrapper = list([job]);
    await wrapper.find(".job-row").trigger("click");
    expect(wrapper.emitted("open")).toEqual([[job.id]]);
  });
});
