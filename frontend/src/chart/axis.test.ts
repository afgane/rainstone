import { describe, expect, it } from "vitest";

import { axisSlots } from "./axis";

describe("axisSlots", () => {
  it("fills every hour, empty ones too", () => {
    const slots = axisSlots("hour", {
      from: "2026-09-28T00:00:00+00:00", to: "2026-09-28T06:00:00+00:00",
    }, "UTC");
    expect(slots).toHaveLength(6);
    expect(slots[0]).toEqual({ from: Date.parse("2026-09-28T00:00:00Z"), to: Date.parse("2026-09-28T01:00:00Z") });
  });

  it("has 23 hourly slots on the day clocks spring forward and 25 when they fall back", () => {
    const spring = axisSlots("hour", {
      from: "2026-03-08T00:00:00-05:00", to: "2026-03-09T00:00:00-04:00",
    }, "America/New_York");
    const fall = axisSlots("hour", {
      from: "2026-11-01T00:00:00-04:00", to: "2026-11-02T00:00:00-05:00",
    }, "America/New_York");
    expect(spring).toHaveLength(23);
    expect(fall).toHaveLength(25);
  });

  it("fills local days between midnights", () => {
    const slots = axisSlots("day", {
      from: "2026-09-01T00:00:00+00:00", to: "2026-09-04T00:00:00+00:00",
    }, "UTC");
    expect(slots.map(slot => new Date(slot.from).toISOString().slice(0, 10))).toEqual([
      "2026-09-01", "2026-09-02", "2026-09-03",
    ]);
    expect(slots[2].to).toBe(Date.parse("2026-09-04T00:00:00Z"));
  });

  it("makes days at local midnight, however long the day is", () => {
    const slots = axisSlots("day", {
      from: "2026-03-08T00:00:00-05:00", to: "2026-03-10T00:00:00-04:00",
    }, "America/New_York");
    expect(slots).toHaveLength(2);
    expect((slots[0].to - slots[0].from) / 3600e3).toBe(23);
    expect((slots[1].to - slots[1].from) / 3600e3).toBe(24);
  });

  it("steps weeks from a Monday", () => {
    const slots = axisSlots("week", {
      from: "2026-08-31T00:00:00+00:00", to: "2026-09-21T00:00:00+00:00",
    }, "UTC");
    expect(slots).toHaveLength(3);
    expect(slots[1].from).toBe(Date.parse("2026-09-07T00:00:00Z"));
  });

  it("is empty when the axis is", () => {
    expect(axisSlots("day", {
      from: "2026-09-01T00:00:00+00:00", to: "2026-09-01T00:00:00+00:00",
    }, "UTC")).toEqual([]);
  });
});
