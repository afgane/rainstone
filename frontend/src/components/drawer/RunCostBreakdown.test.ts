import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetJobs, runDetail, runJob } from "../../test/runDetail";
import RunCostBreakdown from "./RunCostBreakdown.vue";

type Detail = ReturnType<typeof runDetail>;

const mounted: Array<ReturnType<typeof mount>> = [];

function breakdown(detail: Detail, props: Record<string, unknown> = {}) {
  const wrapper = mount(RunCostBreakdown, {
    attachTo: document.body, props: { detail, selected: "", member: "", running: false, ...props },
  });
  mounted.push(wrapper);
  return wrapper;
}

/** Five tools whose costs make three named parts and one pooled one. */
function example(): Detail {
  return runDetail(["81", "50", "6", "4", "3"].map((amount, index) => runJob(`tool ${index}`, amount)));
}
const cellsOf = (wrapper: ReturnType<typeof breakdown>, key: string) =>
  wrapper.findAll(".fp-cell").filter(cell => cell.attributes("data-part") === key).length;
const keyOf = (name: string) => `tool:tools/${name}|1.0|dedicated`;

beforeEach(resetJobs);
afterEach(() => {
  // A tooltip listens for Escape on the document until it is gone, so leave none behind.
  mounted.splice(0).forEach(wrapper => wrapper.unmount());
  document.body.innerHTML = "";
});

describe("the fingerprint", () => {
  it("draws exactly one hundred squares, however few or many jobs there are", () => {
    expect(breakdown(example()).findAll(".fp-cell")).toHaveLength(100);
    expect(breakdown(runDetail([runJob("only", "3")])).findAll(".fp-cell")).toHaveLength(100);
    const many = runDetail(Array.from({ length: 300 }, (_, index) => runJob(`t${index}`, "0.01")));
    expect(breakdown(many).findAll(".fp-cell")).toHaveLength(100);
  });

  it("gives each part one run of squares, in order, other last", () => {
    const wrapper = breakdown(example());
    expect(cellsOf(wrapper, keyOf("tool 0"))).toBe(56);
    expect(cellsOf(wrapper, keyOf("tool 1"))).toBe(35);
    expect(cellsOf(wrapper, keyOf("tool 2"))).toBe(4);
    expect(cellsOf(wrapper, "other")).toBe(5);
    const order = wrapper.findAll(".fp-cell").map(cell => cell.attributes("data-part"));
    const changes = order.filter((key, index) => index === 0 || key !== order[index - 1]);
    expect(changes).toEqual([keyOf("tool 0"), keyOf("tool 1"), keyOf("tool 2"), "other"]);
  });

  it("keeps every square on one grid of twenty columns, all the same size", () => {
    const wrapper = breakdown(example());
    expect(wrapper.find(".fingerprint-cells").attributes("style")).toContain("repeat(20");
    expect(wrapper.findAll(".fp-row")).toHaveLength(0);
    expect(wrapper.findAll(".fp-cell")).toHaveLength(100);
  });

  it("puts one diamond square between tools, and none inside a tool or at the ends", () => {
    const wrapper = breakdown(example());
    const slots = wrapper.find(".fingerprint-cells").element.children;
    const kinds = Array.from(slots).map(slot => (slot.classList.contains("fp-gap") ? "gap" : slot.getAttribute("data-part")));
    expect(kinds).toHaveLength(103);
    expect(kinds[0]).not.toBe("gap");
    expect(kinds[kinds.length - 1]).not.toBe("gap");
    const gaps = kinds.flatMap((kind, index) => (kind === "gap" ? [index] : []));
    expect(gaps).toHaveLength(3);
    for (const index of gaps) {
      expect(kinds[index - 1]).not.toBe(kinds[index + 1]);
      expect(kinds[index - 1]).not.toBe("gap");
    }
    // A gap is decoration: hidden from assistive technology and not a part to choose.
    expect(wrapper.findAll(".fp-gap").every(gap => gap.attributes("aria-hidden") === "true")).toBe(true);
  });

  it("adds no gap where a tool ends exactly at the end of a row", () => {
    const wrapper = breakdown(runDetail([runJob("a", "20"), runJob("b", "80")]));
    expect(wrapper.findAll(".fp-gap")).toHaveLength(0);
    expect(wrapper.find(".fingerprint-cells").element.children).toHaveLength(100);
  });

  it("is a figure with a name, not a hundred things to read or tab to", () => {
    const wrapper = breakdown(example());
    const figure = wrapper.find(".fingerprint-cells");
    expect(figure.attributes("role")).toBe("img");
    expect(figure.attributes("aria-label")).toContain("100 squares");
    expect(wrapper.findAll(".fp-cell[tabindex]")).toHaveLength(0);
    expect(wrapper.findAll("button")).toHaveLength(4);
  });

  it("explains that one square is about one percent", () => {
    expect(breakdown(example()).find(".fingerprint-caption").text()).toContain("about 1%");
  });

  it("paints the place the work ran, and a pattern where several places are pooled", () => {
    const detail = runDetail([
      runJob("a", "60"), runJob("b", "20", { environment: "elastic_shared", capacities: ["elastic_shared"] }),
    ]);
    const wrapper = breakdown(detail);
    const places = new Set(wrapper.findAll(".fp-cell").map(cell => cell.attributes("data-environment")));
    expect(places).toEqual(new Set(["dedicated", "elastic_shared"]));
  });
});

describe("the parts as text", () => {
  it("lists every part with its cost, share and place, as the alternative to the squares", () => {
    const wrapper = breakdown(example());
    const first = wrapper.findAll("button[data-part]")[0];
    expect(first.text()).toContain("tool 0");
    expect(first.text()).toContain("$81.00");
    expect(first.text()).toContain("56%");
    expect(first.text()).toContain("Dedicated cloud compute");
    expect(first.attributes("aria-pressed")).toBe("false");
    // They are for the keyboard and screen readers; the chart is what is seen.
    expect(first.element.closest("ul")!.classList.contains("sr-only")).toBe(true);
  });

  it("says what a share is of while the run is still going or incomplete", () => {
    const running = breakdown(example(), { running: true });
    expect(running.text()).toContain("of cost so far");
    const partial = example();
    partial.cost_breakdown.complete = false;
    expect(breakdown(partial).text()).toContain("of recorded cost");
    expect(breakdown(example()).text()).toContain("of this run's cost");
  });

  it("lists a part with no square of its own, and says it is under one percent", () => {
    const wrapper = breakdown(runDetail([runJob("big", "99.9"), runJob("tiny", "0.1")]));
    const other = wrapper.find('.tiny-list .part-button[data-part="other"]');
    expect(other.exists()).toBe(true);
    expect(other.text()).toContain("Less than 1%");
    expect(wrapper.find(".tiny-note").text()).toContain("Too small to show in the chart");
    expect(cellsOf(wrapper, "other")).toBe(0);
    expect(wrapper.find(".tiny-list").element.closest(".sr-only")).toBeNull();
  });

  it("names the version or place when two parts share a name", () => {
    const detail = runDetail([
      runJob("same", "10", { tool_id: "a/same" }), runJob("same", "10", { tool_id: "b/same", tool_version: "2.0" }),
    ]);
    const text = breakdown(detail).text();
    expect(text).toContain("version 2.0 · Dedicated cloud compute");
  });
});

describe("choosing a part", () => {
  it("selects it from its control and again from the same control to clear it", async () => {
    const wrapper = breakdown(example());
    await wrapper.findAll("button[data-part]")[0].trigger("click");
    expect(wrapper.emitted("select")).toEqual([[keyOf("tool 0"), ""]]);
    await wrapper.setProps({ selected: keyOf("tool 0") });
    expect(wrapper.findAll("button[data-part]")[0].attributes("aria-pressed")).toBe("true");
    await wrapper.findAll("button[data-part]")[0].trigger("click");
    expect(wrapper.emitted("select")![1]).toEqual(["", ""]);
  });

  it("selects the whole part from any of its squares, never one job", async () => {
    const wrapper = breakdown(example());
    await wrapper.findAll(".fp-cell")[10].trigger("click");
    expect(wrapper.emitted("select")).toEqual([[keyOf("tool 0"), ""]]);
  });

  it("opens its details below, leaving the controls where they are", async () => {
    const wrapper = breakdown(example(), { selected: keyOf("tool 1") });
    const detail = wrapper.find("#part-detail");
    expect(detail.exists()).toBe(true);
    expect(detail.find("h4").text()).toBe("tool 1");
    expect(detail.text()).toContain("$50.00");
    expect(detail.text()).toContain("Dedicated cloud compute");
    expect(wrapper.findAll("button[data-part]")).toHaveLength(4);
  });

  it("shows no details until a part is chosen, and says how to choose one", () => {
    const wrapper = breakdown(example());
    expect(wrapper.find("#part-detail").exists()).toBe(false);
    expect(wrapper.find("#part-placeholder").text()).toContain("Choose a square in the chart");
  });

  it("puts the details where the hint was, so the chart above does not move", () => {
    const wrapper = breakdown(example(), { selected: keyOf("tool 1") });
    expect(wrapper.find("#part-placeholder").exists()).toBe(false);
    const html = wrapper.html();
    expect(html.indexOf("fingerprint-cells")).toBeLessThan(html.indexOf('id="part-detail"'));
  });

  it("does not list the parts under the chart for the eye", () => {
    const wrapper = breakdown(example());
    expect(wrapper.findAll(".part-button")).toHaveLength(0);
  });

  it("lists a repeated tool's jobs individually, each one openable", async () => {
    const repeated = [runJob("wig", "0.4"), runJob("wig", "0.4"), runJob("wig", "0.4")];
    const wrapper = breakdown(runDetail([runJob("star", "98.8"), ...repeated]), { selected: keyOf("wig") });
    const rows = wrapper.findAll("#part-detail .job-row");
    expect(rows).toHaveLength(3);
    expect(rows.map(row => row.find(".job-id").text())).toEqual(repeated.map(job => `#${job.source_id}`));
    await rows[1].trigger("click");
    expect(wrapper.emitted("open")).toEqual([[repeated[1].id]]);
    expect(wrapper.find("button[data-part]").text()).toContain("star");
    expect(wrapper.text()).toContain("wig ×3");
  });

  it("shows every part pooled into Other, not a top few", async () => {
    const wrapper = breakdown(runDetail(Array.from({ length: 20 }, (_, i) => runJob(`t${i}`, "5"))), { selected: "other" });
    expect(wrapper.findAll("#part-detail .member-button")).toHaveLength(12);
    expect(wrapper.find("#part-detail").text()).toContain("5%");
    await wrapper.findAll("#part-detail .member-button")[3].trigger("click");
    const key = wrapper.findAll("#part-detail .member-button")[3].attributes("data-member-key");
    expect(wrapper.emitted("select")).toEqual([["other", key]]);
  });

  it("opens a member inside the same area, with a way back to Other", async () => {
    const detail = runDetail(Array.from({ length: 20 }, (_, i) => runJob(`t${i}`, "5")));
    const wrapper = breakdown(detail, { selected: "other" });
    const button = wrapper.findAll("#part-detail .member-button")[0];
    const member = button.attributes("data-member-key")!;
    const name = button.find(".member-name").text();
    await wrapper.setProps({ member });
    const area = wrapper.find("#part-detail");
    expect(wrapper.findAll("#part-detail")).toHaveLength(1);
    expect(area.find("h4").text()).toBe(name);
    expect(area.find(".back-to").text()).toContain("Back to Other");
    expect(area.findAll(".job-row")).toHaveLength(1);
    await area.find(".back-to").trigger("click");
    expect(wrapper.emitted("select")).toEqual([["other", ""]]);
  });

  it("clears the selection from the details without closing anything else", async () => {
    const wrapper = breakdown(example(), { selected: keyOf("tool 0") });
    await wrapper.find("#part-detail .detail-clear").trigger("click");
    expect(wrapper.emitted("select")).toEqual([["", ""]]);
  });

  it("clears with a labeled round icon button, and lists no version", async () => {
    const wrapper = breakdown(example(), { selected: keyOf("tool 0") });
    const clear = wrapper.find("#part-detail .detail-clear");
    expect(clear.attributes("aria-label")).toBe("Clear selection");
    expect(clear.text()).toBe("");
    expect(wrapper.find("#part-detail").text()).not.toContain("Version");
  });

  it("tells the reader when a linked part is no longer there, and clears it", async () => {
    const wrapper = breakdown(example(), { selected: "tool:gone|1|dedicated" });
    await flushPromises();
    expect(wrapper.emitted("select")).toEqual([["", ""]]);
    expect(wrapper.find('[role="status"]').text()).toBe("The part you had selected is no longer available.");
    expect(wrapper.find("#part-detail").exists()).toBe(false);
  });

  it("clears a member the part does not hold", async () => {
    const wrapper = breakdown(example(), { selected: "other", member: "nope" });
    await flushPromises();
    expect(wrapper.emitted("select")).toEqual([["", ""]]);
  });

  it("announces the part that opened, in a polite status", async () => {
    const wrapper = breakdown(example());
    await wrapper.setProps({ selected: keyOf("tool 0") });
    const status = wrapper.find('[role="status"]');
    expect(status.attributes("aria-live")).toBe("polite");
    expect(status.text()).toBe("tool 0, $81.00, 1 job");
  });
});

describe("the tooltip", () => {
  it("appears over a square with the part's name, cost, share and place", async () => {
    const wrapper = breakdown(example());
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    const tip = wrapper.find(".fp-tip");
    expect(tip.attributes("role")).toBe("tooltip");
    expect(tip.text()).toContain("tool 0");
    expect(tip.text()).toContain("$81.00 · 56% of this run's cost");
    expect(tip.text()).toContain("Dedicated cloud compute");
    expect(wrapper.findAll('.fp-cell[data-hot="true"]')).toHaveLength(56);
  });

  it("appears for a control that has keyboard focus, and lights its squares", async () => {
    const keyboard = vi.spyOn(Element.prototype, "matches").mockImplementation(selector => selector === ":focus-visible");
    const wrapper = breakdown(example());
    await wrapper.findAll("button[data-part]")[1].trigger("focus");
    expect(wrapper.find(".fp-tip strong").text()).toBe("tool 1");
    expect(wrapper.findAll('.fp-cell[data-hot="true"]')).toHaveLength(35);
    await wrapper.findAll("button[data-part]")[1].trigger("blur");
    expect(wrapper.find(".fp-tip").exists()).toBe(false);
    keyboard.mockRestore();
  });

  it("says when a figure is not final", async () => {
    const wrapper = breakdown(example(), { running: true });
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    expect(wrapper.find(".fp-tip").text()).toContain("of cost so far");
    expect(wrapper.find(".fp-tip").text()).toContain("Not final");
  });

  it("goes on Escape before the drawer is asked to close", async () => {
    const wrapper = breakdown(example());
    let heard = false;
    const spy = () => { heard = true; };
    document.addEventListener("keydown", spy);
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", cancelable: true }));
    await wrapper.vm.$nextTick();
    expect(wrapper.find(".fp-tip").exists()).toBe(false);
    expect(heard).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(heard).toBe(true);
    document.removeEventListener("keydown", spy);
  });

  it("goes the moment the pointer leaves, and never takes the pointer itself", async () => {
    const wrapper = breakdown(example());
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    expect(wrapper.find(".fp-tip").exists()).toBe(true);
    await wrapper.findAll(".fp-cell")[0].trigger("mouseleave");
    expect(wrapper.find(".fp-tip").exists()).toBe(false);
  });

  it("follows the pointer from square to square, naming the part under it", async () => {
    const wrapper = breakdown(example());
    await wrapper.findAll(".fp-cell")[0].trigger("mouseenter");
    expect(wrapper.find(".fp-tip strong").text()).toBe("tool 0");
    await wrapper.findAll(".fp-cell")[70].trigger("mouseenter");
    expect(wrapper.find(".fp-tip strong").text()).toBe("tool 1");
    await wrapper.findAll(".fp-cell")[99].trigger("mousemove");
    expect(wrapper.find(".fp-tip strong").text()).toBe("Other");
  });
})

describe("when there is nothing to chart", () => {
  it("draws no squares for work that added no cost", () => {
    const free = { environment: "existing", capacities: ["existing"] };
    const wrapper = breakdown(runDetail([runJob("a", "0", free), runJob("b", "0", free)]));
    expect(wrapper.findAll(".fp-cell")).toHaveLength(0);
    expect(wrapper.text()).toContain("added compute cost, so there is nothing to break down");
  });

  it("never turns unknown cost into a share", () => {
    const wrapper = breakdown(runDetail([runJob("a", null), runJob("b", null)]));
    expect(wrapper.findAll(".fp-cell")).toHaveLength(0);
    expect(wrapper.text()).toContain("2 jobs still need cost data");
    expect(wrapper.text()).not.toContain("%");
  });

  it("charts what is known and leaves the unknown work out of it", () => {
    const wrapper = breakdown(runDetail([runJob("a", "4"), runJob("b", null)]), { running: false });
    expect(wrapper.findAll(".fp-cell")).toHaveLength(100);
    expect(wrapper.findAll("button[data-part]")).toHaveLength(1);
  });

  it("says the breakdown is unavailable, and keeps the rest usable", () => {
    const detail = runDetail([runJob("a", "4")], {}, { status: "unavailable", reason: "The parts do not add up to the run total." });
    const wrapper = breakdown(detail);
    expect(wrapper.text()).toContain("Cost breakdown unavailable");
    expect(wrapper.text()).toContain("do not add up");
    expect(wrapper.findAll(".fp-cell")).toHaveLength(0);
  });
});
