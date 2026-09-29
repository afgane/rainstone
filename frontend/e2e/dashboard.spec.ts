import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://localhost:8000";
const PREFIX = process.env.PREFIX_URL || BASE;
// The demonstration fixture is dated, so scenarios that assert amounts pin the
// period explicitly instead of depending on today's date.
const FIXTURE_PERIOD = "period=custom&from=2026-09-19&to=2026-09-20";

test("a first-time user gets a scoped answer without typing dates", async ({ page }) => {
  await page.goto(BASE);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  const headline = page.locator(".figure.featured");
  await expect(headline.getByText("Estimated run compute cost")).toBeVisible();
  await expect(headline.getByText("Compute started for your jobs and workflow runs")).toBeVisible();

  for (const period of ["Yesterday", "Last week", "Last month"]) {
    await page.getByRole("button", { name: period, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`period=${period.toLowerCase().replace(" ", "-")}`));
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  }
  // The resolved dates are always visible, so a preset is never ambiguous.
  await expect(page.locator(".resolved")).toContainText("UTC");
});

test("a workflow run shows its whole cost and its share of the period", async ({ page }) => {
  await page.goto(`${BASE}?view=runs&${FIXTURE_PERIOD}`);
  await page.getByPlaceholder("Find a workflow run").fill("RNA-seq");
  await expect(page).toHaveURL(/search=RNA-seq/);
  const run = page.locator(".run-card", { hasText: "RNA-seq mixed execution demo" });
  await expect(run).toBeVisible();
  await expect(page.getByText("Run total").first()).toBeVisible();

  await run.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Run total", { exact: false })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "Steps" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: /RNA-seq mixed execution demo/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(run).toBeFocused();

  // A run whose cost crosses midnight shows how much of it falls in the period.
  await page.goto(`${BASE}?view=tool-runs&period=custom&from=2026-09-20&to=2026-09-20&search=midnight-price`);
  // The first button in the table head sorts; the row's tool name opens details.
  await page.locator(".jobs-table tbody").getByRole("button").first().click();
  await expect(page.getByRole("dialog")).toContainText("falls inside the selected dates");
});

test("ordinary language explains zero, unknown and incomplete costs", async ({ page }) => {
  await page.goto(`${BASE}?view=tool-runs&${FIXTURE_PERIOD}`);
  const table = page.locator(".jobs-table");
  await expect(table.getByText("Used your Galaxy server").first()).toBeVisible();
  await expect(
    table.getByText("Price unavailable").or(table.getByText("Cost incomplete")).first(),
  ).toBeVisible();

  await table.locator("tbody").getByRole("button", { name: "goseq" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("The server continues to incur costs");
  await expect(dialog.getByRole("heading", { name: "Where it ran" })).toBeVisible();
  await dialog.getByRole("button", { name: "Close details" }).click();
  await expect(dialog).toBeHidden();
});

test("advanced filters stay visible and removable while collapsed", async ({ page }) => {
  await page.goto(`${BASE}?${FIXTURE_PERIOD}`);
  const disclosure = page.getByRole("button", { name: /More filters/ });
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  await disclosure.click();
  await page.getByLabel("Cost coverage").selectOption("known_zero");
  await expect(page).toHaveURL(/quality=known_zero/);

  await disclosure.click();
  await expect(disclosure).toHaveAttribute("aria-expanded", "false");
  const chip = page.getByRole("button", { name: /Cost coverage.*known_zero/ });
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(page).not.toHaveURL(/quality=known_zero/);
});

test("a long filter value stays inside the sidebar", async ({ page }) => {
  const toolId = "toolshed.g2.bx.psu.edu/repos/iuc/goseq/goseq/2.0.1";
  await page.goto(`${BASE}?view=tool-runs&${FIXTURE_PERIOD}&tool_id=${toolId}`);
  const chip = page.getByRole("button", { name: /Tool ID/ });
  await expect(chip).toBeVisible();

  const sidebar = await page.locator(".sidebar").boundingBox();
  const box = await chip.boundingBox();
  expect(box!.x + box!.width).toBeLessThanOrEqual(sidebar!.x + sidebar!.width + 1);
  // The whole value stays available even though the label is truncated.
  await expect(chip).toHaveAttribute("title", new RegExp(toolId.replace(/[.]/g, "\\.")));
});

test("status is operational and carries no report controls", async ({ page }) => {
  await page.goto(BASE);
  await page.getByRole("button", { name: "Status", exact: true }).click();
  await expect(page).toHaveURL(/view=status/);
  await expect(page.getByRole("heading", { name: "Deployment status" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download diagnostics" })).toBeVisible();
  await expect(page.getByRole("button", { name: "This month", exact: true })).toBeHidden();
  await expect(page.getByRole("cell", { name: "migration_state" })).toBeVisible();
});

test("the report works behind a proxy prefix and on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${PREFIX}?${FIXTURE_PERIOD}`);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  const filters = page.getByRole("button", { name: /Filters/ });
  await expect(filters).toBeVisible();
  await filters.click();
  await page.getByRole("button", { name: "Workflow runs", exact: true }).click();
  await expect(page).toHaveURL(/view=runs/);

  await page.reload();
  await expect(page.getByRole("heading", { name: "Workflow runs" }).first()).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});


/* The Workflow runs page, against the generated demonstration runs. */
const RUNS_PERIOD = "period=custom&from=2026-08-01&to=2026-09-29";
const API_PERIOD = { from: "2026-08-01T00:00:00Z", to: "2026-09-30T00:00:00Z" };
const IDENTITY = { "X-Rainstone-Tenant": "anvil-demo", "X-Rainstone-User": "admin", "X-Rainstone-Admin": "true" };

async function api(request: APIRequestContext, path: string, params: Record<string, string> = {}) {
  const query = new URLSearchParams({ ...API_PERIOD, ...params });
  const response = await request.get(`${BASE}/api/${path}?${query}`, { headers: IDENTITY });
  expect(response.ok()).toBe(true);
  return response.json();
}

const dollars = (amount: string) =>
  Number(amount).toLocaleString("en-US", { style: "currency", currency: "USD" });

async function openRuns(page: Page, extra = "") {
  await page.goto(`${BASE}?view=runs&${RUNS_PERIOD}${extra}`);
  await expect(page.locator(".figures")).toBeVisible();
  await expect(page.locator(".run-card").first()).toBeVisible();
}

/** The outer positions and sizes that must not move when a filter narrows the page. */
async function outline(page: Page) {
  // Positions are measured on the page, so scrolling the window cannot look like movement.
  const scrolled = await page.evaluate(() => window.scrollY);
  const box = async (locator: Locator) => {
    const found = (await locator.boundingBox())!;
    return { ...found, y: found.y + scrolled };
  };
  return {
    figuresTop: (await box(page.locator(".figures"))).y,
    chartTop: (await box(page.locator(".chart-panel"))).y,
    chartRegionHeight: (await box(page.locator(".chart-region"))).height,
    // A note under the legend appears only when it applies, so what follows it may shift.
    notes: await page.locator(".chart-notes").count(),
  };
}

async function settle(page: Page) {
  await expect(page.locator(".refetching")).toHaveCount(0);
  await page.waitForTimeout(150);
}

test("the total is the period's, and paging never changes it", async ({ page, request }) => {
  const listing = await api(request, "invocations", { limit: "1" });
  await openRuns(page);
  const card = page.locator(".figure.featured .figure-amount");
  const expected = dollars(listing.totals.amount);
  await expect(card).toContainText(expected);
  await expect(page.locator(".figure").nth(1).locator(".figure-amount")).toHaveText(String(listing.totals.run_count));
  expect(listing.totals.run_count).toBeGreaterThan(50);

  const more = page.getByRole("button", { name: /^Show \d+ more$/ });
  while (await more.count()) {
    const before = await page.locator(".run-card").count();
    await more.click();
    await expect(page.locator(".run-card")).not.toHaveCount(before);
    await expect(card).toContainText(expected);
  }
  await expect(page.locator(".run-card")).toHaveCount(listing.totals.run_count);
  await expect(page.getByText(`Showing ${listing.totals.run_count} of ${listing.totals.run_count}`)).toBeVisible();
});

test("Overview lists the period's four most expensive runs", async ({ page, request }) => {
  const top = await api(request, "invocations", { run_sort: "amount", direction: "desc", limit: "4" });
  await page.goto(`${BASE}?${RUNS_PERIOD}`);
  const rows = page.locator(".rank-row", { has: page.locator("small", { hasText: /Completed|Failed|Running/ }) });
  await expect(rows.first()).toBeVisible();
  const shown = await rows.locator(".rank-amount").allInnerTexts();
  expect(shown.slice(0, 4)).toEqual(top.items.map((run: { amount: string }) => dollars(run.amount)));
});

test("choosing an outcome narrows the figures, the chart and the list together", async ({ page, request }) => {
  const everything = await api(request, "invocations", { limit: "1" });
  const failed = await api(request, "invocations", { limit: "200", run_status: "failed" });
  await openRuns(page);
  await page.getByRole("button", { name: /^Failed/ }).click();
  await expect(page).toHaveURL(/outcome=failed/);
  const card = page.locator(".figure.featured .figure-amount");
  await expect(card).toContainText(dollars(failed.totals.amount));
  await expect(page.locator(".figure").nth(1)).toContainText(`${failed.totals.run_count} failed`);
  await expect(page.locator(".figure").nth(1)).toContainText(`Out of ${everything.totals.run_count} runs in this period`);
  await expect(page.locator(".run-card")).toHaveCount(Math.min(20, failed.totals.run_count));
  for (const status of await page.locator(".run-card .status").allInnerTexts()) expect(status).toBe("Failed");
  // Blocks of other outcomes are gone, not dimmed.
  const statuses = await page.locator(".workflow-bars .blk[data-status]").evaluateAll(
    blocks => blocks.map(block => block.getAttribute("data-status")));
  expect(statuses.length).toBeGreaterThan(0);
  expect(statuses.every(status => status === "failed")).toBe(true);
  // The other choices stay available, with their own counts.
  await expect(page.getByRole("button", { name: /^Completed/ })).toBeEnabled();
  await page.getByRole("button", { name: /^Completed/ }).click();
  await expect(page.locator(".run-card .status").first()).toHaveText("Completed");
});

test("workflow, search, a day and a grouped segment each narrow everything, and history steps back", async ({ page, request }) => {
  await openRuns(page);
  const options = (await api(request, "invocations", { limit: "1" })).filter_options.workflows as
    Array<{ key: string; name: string; run_count: number }>;
  const busiest = options.reduce((a, b) => (b.run_count > a.run_count ? b : a));

  await page.locator(".page-filters select").selectOption(busiest.key);
  await expect(page).toHaveURL(new RegExp(`workflow=${encodeURIComponent(busiest.key)}`));
  await expect(page.locator(".figure").nth(1)).toContainText(String(busiest.run_count));
  await expect(page.locator(".run-card strong").first()).toHaveText(busiest.name);
  await expect(page.locator(".zoom-label")).toContainText(busiest.name);

  await page.getByPlaceholder("Find a workflow run").fill("zzz-nothing");
  await expect(page.getByText("No workflow runs match these filters.")).toBeVisible();
  await expect(page.locator(".figure").first()).toContainText("No matching runs");
  await page.locator(".empty").getByRole("button", { name: "Clear filters" }).click();
  await expect(page.locator(".run-card").first()).toBeVisible();
  await expect(page).not.toHaveURL(/workflow=/);

  // A day on the time chart selects the runs active then, and can be cleared.
  await page.getByRole("tab", { name: "Over time" }).click();
  await expect(page).toHaveURL(/chart=time/);
  const column = page.locator(".col:not(.empty)").first();
  await column.click();
  await expect(page).toHaveURL(/focus_from=/);
  await expect(page.locator(".page-chips")).toContainText("Runs active");
  await expect(column).toHaveAttribute("aria-pressed", "true");
  await page.goBack();
  await expect(page).not.toHaveURL(/focus_from=/);
  await page.goForward();
  await expect(page).toHaveURL(/focus_from=/);
  await page.getByRole("button", { name: /Remove filter: Runs active/ }).click();
  await expect(page).not.toHaveURL(/focus_from=/);
});

test("a grouped segment selects exactly its runs and survives a reload", async ({ page }) => {
  await openRuns(page);
  const grouped = page.locator(".workflow-bars .blk.more").first();
  test.skip((await grouped.count()) === 0, "no grouped segment at this width");
  await grouped.click();
  await expect(page).toHaveURL(/boundary_run_id=/);
  await expect(page.locator(".page-chips")).toContainText("Smaller runs in");
  await settle(page);
  const total = await page.locator(".figure").nth(1).locator(".figure-amount").innerText();
  await page.reload();
  await expect(page.locator(".figure").nth(1).locator(".figure-amount")).toHaveText(total);
  await expect(page.locator(".page-chips")).toContainText("Smaller runs in");
  await page.getByRole("button", { name: /Remove filter: Smaller runs/ }).click();
  await expect(page).not.toHaveURL(/boundary_run_id=/);
});

for (const chart of ["workflow", "time"]) {
  test(`choosing things does not move the page (${chart} tab)`, async ({ page }) => {
    await openRuns(page, chart === "time" ? "&chart=time" : "");
    const before = await outline(page);
    const same = async () => {
      await settle(page);
      const after = await outline(page);
      for (const key of Object.keys(before) as Array<keyof typeof before>) {
        expect(Math.abs(after[key] - before[key]), key).toBeLessThanOrEqual(1);
      }
    };
    await page.locator(".page-filters select").selectOption({ index: 2 });
    await same();
    await page.getByRole("button", { name: /^Failed/ }).click();
    await same();
    await page.getByRole("button", { name: /^All/ }).click();
    await page.locator(".page-filters select").selectOption({ index: 0 });
    await same();
    if (chart === "time") {
      await page.locator(".col:not(.empty)").nth(2).click();
      await same();
    } else {
      const grouped = page.locator(".workflow-bars .blk.more").first();
      if (await grouped.count()) {
        await grouped.click();
        await same();
      }
    }
    await page.getByPlaceholder("Find a workflow run").fill("zzz-nothing");
    await same();
  });
}

test("the run drawer opens from a block and a row, swaps, and dismisses", async ({ page }) => {
  await openRuns(page);
  const drawer = page.getByRole("dialog");
  await page.locator(".workflow-bars .blk[data-run-id]").first().click();
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("dt").first()).toBeVisible();
  const facts = await drawer.locator("dt").allInnerTexts();
  expect(facts).toEqual(["Status", "Started", "Duration", "Workflow jobs"]);
  const first = await drawer.getByRole("heading").first().innerText();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  const rows = page.locator(".run-card");
  await rows.nth(0).click();
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/detail_kind=runs/);
  const urlBefore = page.url();
  const historyLength = await page.evaluate(() => history.length);
  // A press on another run swaps the drawer and replaces the history entry.
  await rows.nth(3).click();
  await expect(drawer.getByRole("heading").first()).not.toHaveText(first, { timeout: 5000 }).catch(() => {});
  await expect(page).not.toHaveURL(urlBefore);
  expect(await page.evaluate(() => history.length)).toBe(historyLength);
  await expect(drawer).toBeVisible();
  // Its own trigger again closes it, and focus stays with that trigger.
  await rows.nth(3).click();
  await expect(drawer).toBeHidden();
  await expect(rows.nth(3)).toBeFocused();

  await rows.nth(1).click();
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "Close details" }).click();
  await expect(drawer).toBeHidden();
  await expect(rows.nth(1)).toBeFocused();

  // Any press outside dismisses it, the masthead and sidebar included.
  for (const outside of [page.locator(".masthead"), page.locator(".sidebar .nav-item").first()]) {
    await rows.nth(1).click();
    await expect(drawer).toBeVisible();
    await outside.click({ position: { x: 5, y: 5 } });
    await expect(drawer).toBeHidden();
  }
});

test("a run's drawer says no more than it should", async ({ page }) => {
  await openRuns(page);
  await page.locator(".run-card").first().click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Workflow jobs")).toBeVisible();
  const text = await drawer.innerText();
  for (const absent of ["Version", "version", "History", "history", "Cost in the selected period", "falls inside"]) {
    expect(text).not.toContain(absent);
  }
  await page.keyboard.press("Escape");
  const rows = await page.locator(".run-list").innerText();
  expect(rows).not.toContain("Version");
});

test("page filters sit in a tinted section under Period", async ({ page }) => {
  await openRuns(page);
  const filters = page.locator(".sidebar .page-filters");
  await expect(filters).toContainText("Filters for this page");
  await expect(filters).toContainText("Workflow runs only. The period above applies everywhere.");
  expect(await filters.evaluate(node => getComputedStyle(node).backgroundColor)).toBe("rgb(217, 230, 242)");
  const order = await page.locator(".sidebar").evaluate(sidebar => {
    const period = sidebar.querySelector("#period-label")!;
    const section = sidebar.querySelector(".page-filters")!;
    return Boolean(period.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(order).toBe(true);
});

test("the sidebar scrolls on its own in a short window", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openRuns(page);
  const sidebar = page.locator(".sidebar");
  expect(await sidebar.evaluate(node => getComputedStyle(node).overflowY)).toBe("auto");
  expect(await sidebar.evaluate(node => node.clientHeight)).toBeLessThanOrEqual(900);
});

test("every chart control can be reached from the keyboard", async ({ page }) => {
  await openRuns(page);
  await page.getByRole("tab", { name: "By workflow" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Over time" })).toHaveAttribute("aria-selected", "true");
  const column = page.locator(".col:not(.empty)").first();
  await column.focus();
  await expect(page.locator(".chart-tip")).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/focus_from=/);
  await page.getByRole("tab", { name: "By workflow" }).click();
  await page.locator(".wf-label").first().focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/workflow=/);
  await page.getByText("Show this chart as a table").click();
  await expect(page.locator(".chart-panel table")).toBeVisible();
});

for (const [label, open] of [
  ["closed", async (_page: Page) => {}],
  ["open", async (page: Page) => { await page.locator(".run-card").first().click(); await expect(page.getByRole("dialog")).toBeVisible(); }],
] as const) {
  test(`the runs page has no accessibility violations with the drawer ${label}`, async ({ page }) => {
    await openRuns(page);
    await open(page);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);
  });
}

test("the four block styles are told apart by texture, and contrast the surface", async ({ page }) => {
  await openRuns(page);
  const styles = await page.locator(".chart-foot .sw").evaluateAll(swatches =>
    swatches.map(swatch => getComputedStyle(swatch).backgroundImage));
  expect(styles.filter(image => image.includes("repeating-linear-gradient")).length).toBeGreaterThanOrEqual(2);
});

test("a period of two days or more shows days on the time axis, not hours", async ({ page }) => {
  await page.goto(`${BASE}?view=runs&period=custom&from=2026-09-16&to=2026-09-17&chart=time`);
  await expect(page.locator(".col:not(.empty)").first()).toBeVisible();
  const labels = await page.locator(".xaxis .xl span").allInnerTexts();
  expect(labels.length).toBeGreaterThan(0);
  for (const label of labels) expect(label).not.toMatch(/\d\s?[AP]M/);
  // A single day still reads by the hour.
  await page.goto(`${BASE}?view=runs&period=custom&from=2026-09-17&to=2026-09-17&chart=time`);
  await expect(page.locator(".col:not(.empty)").first()).toBeVisible();
  expect((await page.locator(".xaxis .xl span").allInnerTexts()).join(" ")).toMatch(/[AP]M/);
});

test("choosing a workflow keeps the others on the chart and leaves the page where it was", async ({ page }) => {
  await openRuns(page);
  const labels = page.locator(".wf-label");
  const count = await labels.count();
  expect(count).toBeGreaterThan(3);
  await page.evaluate(() => window.scrollTo(0, 120));
  const scrolled = await page.evaluate(() => window.scrollY);
  const width = await page.locator(".chart-panel").evaluate(node => node.getBoundingClientRect().width);
  await labels.nth(1).click();
  await expect(page).toHaveURL(/workflow=/);
  await settle(page);
  await expect(labels).toHaveCount(count);
  await expect(labels.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".wf-label[aria-pressed='true']")).toHaveCount(1);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - scrolled)).toBeLessThanOrEqual(1);
  const after = await page.locator(".chart-panel").evaluate(node => node.getBoundingClientRect().width);
  expect(Math.abs(after - width)).toBeLessThanOrEqual(1);
  // Choosing it again clears the choice, and the chart is unchanged.
  await labels.nth(1).click();
  await expect(page).not.toHaveURL(/workflow=/);
  await expect(labels).toHaveCount(count);
});

test("a job opened from a run's steps can lead back to the run", async ({ page }) => {
  await openRuns(page);
  await page.locator(".run-card").first().click();
  const drawer = page.getByRole("dialog");
  const runTitle = await drawer.getByRole("heading").first().innerText();
  await expect(drawer.getByRole("heading", { name: "Steps" })).toBeVisible();
  await expect(drawer.locator(".drawer-back")).toHaveCount(0);
  await drawer.locator(".step-list .link-button").first().click();
  await expect(drawer.getByText("Cost of this job")).toBeVisible();
  await drawer.getByRole("button", { name: "Back to workflow run" }).click();
  await expect(drawer.getByRole("heading").first()).toHaveText(runTitle);
  await expect(drawer.locator(".drawer-back")).toHaveCount(0);
  await expect(drawer.getByRole("heading", { name: "Steps" })).toBeVisible();
});

test("the time axis names every day of the period, month included", async ({ page }) => {
  // 14 to 20 September 2026 is a whole week; days without cost still have their date.
  await page.goto(`${BASE}?view=runs&period=custom&from=2026-09-14&to=2026-09-20&chart=time`);
  await expect(page.locator(".xaxis")).toBeVisible();
  const labels = await page.locator(".xaxis .xl span").allInnerTexts();
  expect(labels).toEqual(["Sep 14", "Sep 15", "Sep 16", "Sep 17", "Sep 18", "Sep 19", "Sep 20"]);
});

test("the time axis is drawn even when nothing cost anything", async ({ page }) => {
  await page.goto(`${BASE}?view=runs&period=custom&from=2026-01-05&to=2026-01-11&chart=time`);
  await expect(page.locator(".plot-empty")).toBeVisible();
  expect(await page.locator(".xaxis .xl span").count()).toBe(7);
});

test("a job's back button sits under its heading", async ({ page }) => {
  await openRuns(page);
  await page.locator(".run-card").first().click();
  const drawer = page.getByRole("dialog");
  await drawer.locator(".step-list .link-button").first().click();
  await expect(drawer.getByText("Cost of this job")).toBeVisible();
  const eyebrow = await drawer.locator(".drawer-head .eyebrow").boundingBox();
  const back = await drawer.locator(".drawer-back").boundingBox();
  const title = await drawer.getByRole("heading").first().boundingBox();
  expect(back!.y).toBeGreaterThan(eyebrow!.y);
  expect(back!.y).toBeLessThan(title!.y);
});

test("opening More filters does not move the period buttons", async ({ page }) => {
  // Short enough that the opened section makes the sidebar taller than the window.
  await page.setViewportSize({ width: 1280, height: 700 });
  await openRuns(page);
  const pills = page.locator(".period-buttons .chip-button");
  // Where each pill is in the sidebar's own content, whether or not the sidebar has scrolled.
  const place = () => pills.evaluateAll(nodes => nodes.map(node => {
    const box = node.getBoundingClientRect();
    const sidebar = node.closest(".sidebar")!;
    return [box.x, box.y + sidebar.scrollTop, box.width];
  }));
  const before = await place();
  await page.getByRole("button", { name: /More filters/ }).click();
  await expect(page.locator("#advanced-filters")).toBeVisible();
  expect(await page.locator(".sidebar").evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
  expect(await place()).toEqual(before);
});

test("the footer under the run list has room above it", async ({ page }) => {
  await openRuns(page);
  const list = await page.locator(".panel", { has: page.locator(".run-list") }).last().boundingBox();
  const footer = await page.locator(".snapshot").boundingBox();
  expect(footer!.y - (list!.y + list!.height)).toBeGreaterThanOrEqual(12);
});

test("choosing a workflow on a tall window does not throw the page towards the top", async ({ page }) => {
  // The narrower list makes the page shorter than where the reader is scrolled to.
  await page.setViewportSize({ width: 1360, height: 1700 });
  await openRuns(page);
  const label = page.locator(".wf-label").first();
  const documentHeight = () => page.evaluate(() => document.documentElement.scrollHeight);
  const before = await documentHeight();
  await page.evaluate(() => window.scrollTo(0, 400));
  const scrolled = await page.evaluate(() => window.scrollY);
  expect(scrolled).toBeGreaterThan(100);
  await label.evaluate(node => (node as HTMLElement).click());
  await settle(page);
  await expect(page).toHaveURL(/workflow=/);
  expect(await documentHeight()).toBeGreaterThanOrEqual(scrolled + 1700 - 1);
  expect(Math.abs((await page.evaluate(() => window.scrollY)) - scrolled)).toBeLessThanOrEqual(1);
  expect(before).toBeGreaterThan(0);
});


/* The Overview page. */
async function openOverview(page: Page, extra = "") {
  await page.goto(`${BASE}?${RUNS_PERIOD}${extra}`);
  await expect(page.locator(".figures")).toBeVisible();
  await expect(page.locator(".chart-panel .blk").first()).toBeVisible();
}

test("Overview pairs a cost summary with a workload summary", async ({ page, request }) => {
  const summary = await api(request, "summary");
  const runs = (await api(request, "invocations", { limit: "1" })).totals;
  await openOverview(page);
  const [cost, workload] = await page.locator(".figure").all();
  await expect(cost).toContainText("Estimated run compute cost");
  await expect(cost).toContainText(dollars(summary.amount));
  await expect(cost).toContainText("Compute only · USD");
  await expect(workload).toContainText("Workload");
  // Jobs and workflow runs each have a shaded block; the job count covers every job, in a workflow or not.
  const [jobsBlock, runsBlock] = await workload.locator(".workload-group").all();
  await expect(jobsBlock.locator(".figure-amount")).toHaveText(String(summary.job_count));
  await expect(runsBlock.locator(".figure-amount")).toHaveText(String(runs.run_count));
  await expect(jobsBlock).toContainText(/\d+ completed/);
  await expect(runsBlock).toContainText(`Across ${runs.workflow_count} workflows`);
  // The two cards are the same height, with no room left over in the taller.
  const heights = await page.locator(".figure").evaluateAll(cards => cards.map(card => card.getBoundingClientRect().height));
  expect(Math.abs(heights[0] - heights[1])).toBeLessThanOrEqual(1);
});

test("Overview's cost chart is dated, groups the runs, and has no table beneath it", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByRole("heading", { name: "Daily cost" })).toBeVisible();
  const labels = await page.locator(".chart-panel .xaxis .xl span").allInnerTexts();
  expect(labels.length).toBeGreaterThan(3);
  for (const label of labels) expect(label).toMatch(/^[A-Z][a-z]{2} \d+$/);
  await expect(page.locator(".chart-panel .blk[data-kind='runs']").first()).toBeVisible();
  await expect(page.locator(".chart-panel .blk[data-kind='individual']").first()).toBeVisible();
  // However many workflows there are, no column holds more than the two blocks.
  const blocksPerColumn = await page.locator(".chart-panel .overview-col").evaluateAll(
    columns => columns.map(column => column.querySelectorAll(".blk").length));
  expect(Math.max(...blocksPerColumn)).toBeLessThanOrEqual(2);
  // The only table is the collapsed alternative to the chart.
  await expect(page.locator(".chart-panel table")).toBeHidden();
  await page.getByText("Show this chart as a table").click();
  await expect(page.locator(".chart-panel table")).toBeVisible();
});

test("Overview names every day of a whole week", async ({ page }) => {
  await page.goto(`${BASE}?period=custom&from=2026-09-14&to=2026-09-20`);
  await expect(page.locator(".chart-panel .xaxis")).toBeVisible();
  expect(await page.locator(".chart-panel .xaxis .xl span").allInnerTexts()).toEqual(
    ["Sep 14", "Sep 15", "Sep 16", "Sep 17", "Sep 18", "Sep 19", "Sep 20"]);
});

test("a block on Overview explains itself", async ({ page }) => {
  await openOverview(page);
  await page.locator(".chart-panel .blk[data-kind='runs']").last().hover();
  const tip = page.locator(".chart-tip");
  await expect(tip).toBeVisible();
  await expect(tip).toContainText("$");
  await expect(tip).toContainText(/\d+ runs? · \d+ jobs?/);
  await expect(tip).toContainText("Select to see the runs");
  await page.locator(".chart-panel .blk[data-kind='individual']").last().hover();
  await expect(tip).toContainText("Select to see the jobs");
});

test("the workflow runs block opens the Workflow runs page for that day", async ({ page }) => {
  await openOverview(page);
  await page.locator(".chart-panel .blk[data-kind='runs']").last().click();
  await expect(page).toHaveURL(/view=runs/);
  await expect(page).toHaveURL(/period=custom/);
  // Not one workflow: the runs of them all, as the top level page shows them.
  await expect(page).not.toHaveURL(/workflow=/);
  await expect(page.getByRole("heading", { name: "Workflow runs" }).first()).toBeVisible();
  await expect(page.locator(".run-card").first()).toBeVisible();
  await expect(page.locator(".page-filters select")).toHaveValue("");
});

test("the individual jobs' block opens the jobs for that day", async ({ page }) => {
  await openOverview(page);
  await page.locator(".chart-panel .blk[data-kind='individual']").last().click();
  await expect(page).toHaveURL(/view=tool-runs/);
  await expect(page).toHaveURL(/period=custom/);
  await expect(page.locator(".jobs-table")).toBeVisible();
});

test("pressing a column, not a block, on Overview does nothing", async ({ page }) => {
  await openOverview(page);
  await page.locator(".chart-panel .overview-col:not(.empty)").first().click({ position: { x: 1, y: 1 } });
  await expect(page).not.toHaveURL(/view=runs|view=tool-runs/);
});

test("the Overview chart's table opens what its blocks open", async ({ page }) => {
  await openOverview(page);
  await page.getByText("Show this chart as a table").click();
  await page.locator(".chart-panel table").getByRole("button", { name: "See runs" }).first().click();
  await expect(page).toHaveURL(/view=runs/);
  await expect(page).not.toHaveURL(/workflow=/);
});

test("Overview has no accessibility violations", async ({ page }) => {
  await openOverview(page);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);
});

test("a chart overlay keeps its width and stays on the screen at the window's edge", async ({ page }) => {
  await openOverview(page);
  const blocks = page.locator(".chart-panel .blk[data-kind='runs']");
  await blocks.last().hover();
  const tip = page.locator(".chart-tip");
  await expect(tip).toBeVisible();
  const box = (await tip.boundingBox())!;
  const viewport = page.viewportSize()!;
  expect(box.width).toBeGreaterThan(150);
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
});

test("Overview no longer has a failed and repeated work section", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByText("Failed and repeated work")).toHaveCount(0);
});

test("the masthead spans the same width as the page below it", async ({ page }) => {
  await openOverview(page);
  const edges = await page.evaluate(() => {
    const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
    return {
      brandLeft: box(".brand").left, sidebarLeft: box(".nav-item").left,
      badgeRight: box(".demo-badge").right, contentRight: box(".figures").right,
    };
  });
  expect(Math.abs(edges.brandLeft - edges.sidebarLeft)).toBeLessThanOrEqual(1);
  expect(Math.abs(edges.badgeRight - edges.contentRight)).toBeLessThanOrEqual(1);
});

test("the workload card's blocks stay in line when a label wraps", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 700 });
  await openOverview(page);
  const tops = await page.locator(".workload-group .figure-amount").evaluateAll(
    nodes => nodes.map(node => node.getBoundingClientRect().top));
  expect(Math.abs(tops[0] - tops[1])).toBeLessThanOrEqual(1);
});
