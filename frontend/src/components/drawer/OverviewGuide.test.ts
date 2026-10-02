import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import OverviewGuide from "./OverviewGuide.vue";

describe("OverviewGuide", () => {
  it("says what the amounts leave out, whether or not the server is shown", () => {
    for (const canViewServer of [true, false]) {
      const text = mount(OverviewGuide, { props: { canViewServer } }).find(".dialog-meta").text();
      expect(text).toContain("do not include data storage or data transfer out of the cloud (egress)");
    }
  });

  it("explains run compute as the machines started for the jobs", () => {
    const text = mount(OverviewGuide, { props: { canViewServer: true } }).text();
    expect(text).toContain("machines started to run your matching jobs");
    expect(text).toContain("Jobs that ran on the Galaxy server itself add nothing here.");
  });
});
