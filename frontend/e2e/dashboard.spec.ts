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
  await expect(headline.getByText("Run compute", { exact: true })).toBeVisible();
  await expect(page.getByText("Run compute is additional to the Galaxy server compute.")).toBeVisible();

  for (const period of ["Yesterday", "Last week", "Last month"]) {
    await page.getByRole("button", { name: period, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`period=${period.toLowerCase().replace(" ", "-")}`));
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  }
  // The resolved dates are always visible, so a preset is never ambiguous.
  await expect(page.locator(".resolved")).toContainText("UTC");
});

test("the welcome guide leaves the report in place and dismissal survives a reload", async ({ page }) => {
  await page.goto(`${BASE}?${FIXTURE_PERIOD}`);
  const welcome = page.getByRole("region", { name: "Welcome to Rainstone" });
  const help = page.getByRole("button", { name: "How to read this page", exact: true });
  await expect(welcome).toBeVisible();
  const chart = page.locator(".chart-panel");
  const before = await chart.boundingBox();
  await welcome.getByRole("button", { name: "Quick guide", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "How to read this page" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "How to read this page" })).toBeFocused();
  await expect(drawer).toContainText("including idle time");
  const after = await chart.boundingBox();
  expect(after).toEqual(before);
  const bounds = await drawer.boundingBox();
  expect(bounds!.y).toBe(0);
  expect(bounds!.height).toBe(page.viewportSize()!.height);
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(welcome.getByRole("button", { name: "Quick guide", exact: true })).toBeFocused();
  await expect(welcome).toBeVisible();

  await welcome.getByRole("button", { name: "Dismiss welcome" }).click();
  await expect(welcome).toBeHidden();
  await expect(help).toBeFocused();
  await page.reload();
  await expect(chart).toBeVisible();
  await expect(welcome).toBeHidden();
  await help.click();
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/detail_kind=guide/);
  await page.reload();
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).toBeFocused();
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
  await expect(drawer.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: /RNA-seq mixed execution demo/ })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(run).toBeFocused();

  // A run whose cost crosses midnight shows how much of it falls in the period.
  await page.goto(`${BASE}?view=tool-runs&period=custom&from=2026-09-20&to=2026-09-20&search=midnight-price`);
  await page.locator(".job-card").first().click();
  await expect(page.getByRole("dialog")).toContainText("falls inside the selected dates");
});

test("ordinary language explains zero, unknown and incomplete costs", async ({ page }) => {
  await page.goto(`${BASE}?view=tool-runs&${FIXTURE_PERIOD}`);
  const list = page.locator(".job-cards");
  await expect(list.getByText("Used your Galaxy server").first()).toBeVisible();
  await expect(list.getByText("$0 extra").first()).toBeVisible();
  await expect(
    list.getByText("Price unavailable").or(list.getByText("Cost incomplete")).first(),
  ).toBeVisible();

  await list.locator(".job-card", { hasText: "goseq" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("The server continues to incur costs");
  await expect(dialog.getByRole("heading", { name: "Compute", exact: true })).toBeVisible();
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

for (const width of [1280, 390]) {
  test(`the Galaxy server explains its recorded session without report controls at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto(`${BASE}?view=server&${FIXTURE_PERIOD}&search=RNA-seq&quality=known_zero`);
    const session = page.getByRole("region", { name: "Galaxy server session" });
    await expect(session).toBeVisible();
    await expect(session.locator(".server-configuration")).toContainText("4 vCPUs · 16 GiB memory");
    await expect(session.locator(".server-duration strong")).toHaveText("3 h");
    await expect(session.locator(".session-timeline")).toContainText("Recorded through");
    await expect(page.locator(".snapshot")).toHaveCount(0);
    if (width < 1000) await page.getByRole("button", { name: "Navigation", exact: true }).click();
    await expect(page.getByRole("button", { name: "This week", exact: true })).toHaveCount(0);
    await expect(page.getByPlaceholder("Search your work")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /More filters/ })).toHaveCount(0);
    if (width < 1000) await page.getByRole("button", { name: "Navigation", exact: true }).click();
    await expect(session.getByText("t2d-standard-4", { exact: true })).toBeHidden();
    const technical = session.getByText("Technical details", { exact: true });
    await technical.focus();
    await page.keyboard.press("Enter");
    await expect(session.getByText("t2d-standard-4", { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);

    if (width < 1000) await page.getByRole("button", { name: "Navigation", exact: true }).click();
    await page.getByRole("button", { name: "Overview", exact: true }).click();
    await expect(page).toHaveURL(/view=overview/);
    await expect(page).toHaveURL(/search=RNA-seq/);
    await expect(page).toHaveURL(/quality=known_zero/);
    if (width < 1000) await page.getByRole("button", { name: /Filters/ }).click();
    await expect(page.getByPlaceholder("Search your work")).toHaveValue("RNA-seq");
    await expect(page.getByRole("button", { name: "Custom dates", exact: true })).toHaveAttribute("aria-pressed", "true");
  });
}

for (const width of [1280, 390]) {
  test(`server duration marks and their table work at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.route("**/api/infrastructure**", async route => {
      const response = await route.fetch();
      const body = await response.json();
      const start = Date.parse(body.current_launch.launch_at), end = Date.parse(body.current_launch.as_of);
      const instant = (offset: number) => new Date(start + offset).toISOString();
      const from = new Date(start).toISOString(), to = new Date(end).toISOString();
      await route.fulfill({ response, json: { ...body, activity: {
        from, to, kind: "dots", job_count: 2,
        intervals: [
          { job_id: "one", source_id: "1", from: instant(600000), to: instant(626000), running: false },
          { job_id: "two", source_id: "2", from: instant(600000), to: instant(720000), running: false },
        ],
        steps: [
          { from, to: instant(600000), count: 0 },
          { from: instant(600000), to: instant(626000), count: 2 },
          { from: instant(626000), to: instant(720000), count: 1 },
          { from: instant(720000), to, count: 0 },
        ],
      } } });
    });
    await page.goto(`${BASE}?view=server&${FIXTURE_PERIOD}`);
    const plot = page.locator(".server-activity");
    await expect(plot).toHaveAttribute("data-kind", "dots");
    await expect(plot.locator(".activity-dot")).toHaveCount(2);
    await expect(plot.locator(".activity-caption")).toContainText("2 recorded jobs");
    const layout = await plot.evaluate(element => {
      const svg = element.querySelector("svg")!.getBoundingClientRect();
      const duration = element.querySelector(".server-duration")!.getBoundingClientRect();
      const endpoints = element.querySelectorAll(".session-timeline li");
      return { height: svg.height, under: duration.top >= svg.bottom,
        between: duration.left >= endpoints[0].getBoundingClientRect().right
          && duration.right <= endpoints[2].getBoundingClientRect().left };
    });
    expect(layout.height).toBeLessThanOrEqual(140);
    expect(layout.under).toBe(true);
    expect(layout.between).toBe(true);
    const sizes = await plot.locator(".activity-dot").evaluateAll(nodes => nodes.map(node => Number(node.getAttribute("width"))));
    expect(sizes[1]).toBeGreaterThan(sizes[0]);
    await plot.getByText("Show job activity as a table", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await expect(plot.getByRole("cell", { name: "26 sec", exact: true })).toBeVisible();
    await expect(plot.getByRole("cell", { name: "Job 2", exact: true })).toBeVisible();
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

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

test("exploring the period ranks its top workflow runs and tools on the server", async ({ page, request }) => {
  const runs = await api(request, "overview/details", { scope: "period", kind: "runs" });
  const tools = await api(request, "overview/details", { scope: "period", kind: "tools" });
  await page.goto(`${BASE}?${RUNS_PERIOD}`);
  await page.getByRole("button", { name: "Explore this period" }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("tab", { name: "Workflow runs" })).toHaveAttribute("aria-selected", "true");
  const amounts = drawer.locator(".rank-row .rank-amount");
  await expect(amounts).toHaveCount(runs.items.length);
  expect(await amounts.allInnerTexts()).toEqual(runs.items.map((run: { amount: string }) => dollars(run.amount)));
  await drawer.getByRole("tab", { name: "Tools" }).click();
  await expect(drawer.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
  await expect(amounts).toHaveCount(tools.items.length);
  expect(await amounts.allInnerTexts()).toEqual(tools.items.map((tool: { amount: string }) => dollars(tool.amount)));
  // Opening a tool and coming back keeps the tab.
  await drawer.locator("[data-tool-key]").first().click();
  await drawer.getByRole("button", { name: "Back to this period" }).click();
  await expect(drawer.getByRole("tab", { name: "Tools" })).toHaveAttribute("aria-selected", "true");
  await drawer.getByRole("button", { name: "See all tools" }).click();
  await expect(page).toHaveURL(/view=tool-runs/);
  await expect(page.getByRole("tab", { name: "By tool" })).toHaveAttribute("aria-selected", "true");
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
  await expect(drawer.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  await expect(drawer.locator(".drawer-back")).toHaveCount(0);
  await drawer.locator(".job-groups .job-row").first().click();
  await expect(drawer.getByRole("heading", { name: "Timeline", exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "Back to workflow run" }).click();
  await expect(drawer.getByRole("heading").first()).toHaveText(runTitle);
  await expect(drawer.locator(".drawer-back")).toHaveCount(0);
  await expect(drawer.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
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
  await drawer.locator(".job-groups .job-row").first().click();
  await expect(drawer.getByRole("heading", { name: "Timeline", exact: true })).toBeVisible();
  const eyebrow = await drawer.locator(".drawer-head .eyebrow").boundingBox();
  const back = await drawer.locator(".drawer-back").boundingBox();
  const title = await drawer.getByRole("heading").first().boundingBox();
  expect(back!.y).toBeGreaterThan(eyebrow!.y);
  expect(back!.y).toBeLessThan(title!.y);
});

test("a job's details read in order, keep their disclosures closed and fit a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await openRuns(page);
  await page.locator(".run-card").first().click();
  const drawer = page.getByRole("dialog");
  await drawer.locator(".job-groups .job-row").first().click();
  const sections = ["Timeline", "Compute", "Resource use"];
  for (const name of sections) await expect(drawer.getByRole("heading", { name, exact: true })).toBeVisible();
  const positions = await Promise.all(
    sections.map(async name => (await drawer.getByRole("heading", { name, exact: true }).boundingBox())!.y),
  );
  expect([...positions].sort((a, b) => a - b)).toEqual(positions);

  const estimate = drawer.locator("details", { hasText: "How this cost was estimated" });
  const technical = drawer.locator("details", { hasText: "Technical details" });
  await expect(estimate).not.toHaveAttribute("open", "");
  await expect(technical).not.toHaveAttribute("open", "");
  await estimate.locator("summary").click();
  await expect(estimate).toContainText("compute only, in USD");

  // Nothing overflows sideways, and nothing inside the drawer scrolls on its own.
  const overflow = await drawer.evaluate(element => ({
    sideways: element.scrollWidth > element.clientWidth,
    nested: [...element.querySelectorAll<HTMLElement>("*")].some(child => {
      const style = getComputedStyle(child);
      return /auto|scroll/.test(style.overflowY + style.overflowX) && child.scrollHeight > child.clientHeight + 1;
    }),
  }));
  expect(overflow).toEqual({ sideways: false, nested: false });

  const results = await new AxeBuilder({ page }).include("[role=dialog]").analyze();
  expect(results.violations).toEqual([]);
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
  await expect(page.locator(".cost-cards")).toBeVisible();
  await expect(page.locator(".chart-panel .blk").first()).toBeVisible();
}

test("Overview puts run compute and the Galaxy server side by side, never summed", async ({ page, request }) => {
  const summary = await api(request, "summary");
  await openOverview(page);
  const [run, server] = await page.locator(".cost-card").all();
  await expect(run.locator(".eyebrow")).toHaveText("Run compute");
  await expect(run.locator(".figure-amount")).toHaveText(dollars(summary.amount));
  await expect(server.locator(".eyebrow")).toHaveText("Galaxy server");
  await expect(page.locator(".cost-relation")).toHaveText("Run compute is additional to the Galaxy server compute.");
  await expect(server.locator(".figure-qualifier")).toHaveText(/\/hour while running$/);
  await expect(server).toContainText("since launch");
  // Peers: the same width and height.
  const boxes = await page.locator(".cost-card").evaluateAll(cards => cards.map(card => {
    const box = card.getBoundingClientRect();
    return [box.width, box.height];
  }));
  expect(Math.abs(boxes[0][0] - boxes[1][0])).toBeLessThanOrEqual(1);
  expect(Math.abs(boxes[0][1] - boxes[1][1])).toBeLessThanOrEqual(1);
  // No workload card, and the server is not repeated further down.
  await expect(page.getByText("Workload")).toHaveCount(0);
  await expect(page.getByText("Galaxy server compute cost")).toHaveCount(0);
  await server.getByRole("button", { name: "Server details" }).click();
  await expect(page).toHaveURL(/view=server/);
});

test("Overview's cost chart is dated, groups the runs, and has no table beneath it", async ({ page }) => {
  await openOverview(page);
  await expect(page.getByRole("heading", { name: "Run compute over time" })).toBeVisible();
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

test("a workflow runs block opens that interval's runs over the page, without moving it", async ({ page }) => {
  await openOverview(page);
  const block = page.locator(".chart-panel .blk[data-kind='runs']").last();
  // Bring the target into view before measuring: click's scrolling is not drawer reflow.
  await block.scrollIntoViewIfNeeded();
  const chart = await page.locator(".chart-panel").boundingBox();
  const amount = (await block.getAttribute("aria-label"))!.match(/\$[\d,]*\.\d{2}|less than \$0\.01/)![0];
  await block.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: /^Workflow runs · / })).toBeFocused();
  await expect(drawer.locator(".dialog-amount strong")).toHaveText(amount);
  await expect(drawer.getByText("Counted here")).toBeVisible();
  await expect(page).toHaveURL(/view=overview/);
  await expect(page).toHaveURL(/detail_kind=overview/);
  expect(await page.locator(".chart-panel").boundingBox()).toEqual(chart);
  // The drawer covers the window's full height, at its right edge (beside any page scrollbar).
  const viewport = page.viewportSize()!;
  await expect.poll(async () => {
    const box = (await drawer.boundingBox())!;
    return box.x + box.width;
  }).toBeGreaterThanOrEqual(viewport.width - 16);
  const box = (await drawer.boundingBox())!;
  expect(box.x + box.width).toBeLessThanOrEqual(viewport.width);
  expect(box.y).toBe(0);
  expect(Math.round(box.height)).toBe(viewport.height);

  await drawer.locator(".rank-row").first().click();
  await expect(drawer).toContainText(/Inside .+ of this run's cost/);
  await page.reload();
  await drawer.getByRole("button", { name: /Back to selected (day|hour|week)/ }).click();
  await expect(drawer.getByText("Counted here")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("an individual jobs block opens only jobs outside workflows", async ({ page }) => {
  await openOverview(page);
  const block = page.locator(".chart-panel .blk[data-kind='individual']").last();
  await block.focus();
  await page.keyboard.press("Enter");
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: /^Jobs outside workflows · / })).toBeVisible();
  await expect(drawer.locator(".job-row").first()).toBeVisible();
  await expect(block).toHaveAttribute("aria-current", "true");
  // A press outside dismisses it.
  await page.locator(".page-title").click();
  await expect(drawer).toBeHidden();
});

test("Overview's drawer has no accessibility violations", async ({ page }) => {
  await openOverview(page);
  await page.getByRole("button", { name: "Explore this period" }).click();
  await expect(page.getByRole("dialog").getByRole("tab", { name: "Tools" })).toBeVisible();
  const results = await new AxeBuilder({ page }).include(".drawer").analyze();
  expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);
});

test("pressing a column, not a block, on Overview does nothing", async ({ page }) => {
  await openOverview(page);
  await page.locator(".chart-panel .overview-col:not(.empty)").first().click({ position: { x: 1, y: 1 } });
  await expect(page).not.toHaveURL(/view=runs|view=tool-runs|detail_kind/);
});

test("the Overview chart's table opens what its blocks open", async ({ page }) => {
  await openOverview(page);
  await page.getByText("Show this chart as a table").click();
  await page.locator(".chart-panel table").getByRole("button", { name: "See runs" }).first().click();
  await expect(page.getByRole("dialog").getByRole("heading", { name: /^Workflow runs · / })).toBeVisible();
  await expect(page).toHaveURL(/view=overview/);
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
      badgeRight: box(".demo-badge").right, contentRight: box(".cost-cards").right,
    };
  });
  expect(Math.abs(edges.brandLeft - edges.sidebarLeft)).toBeLessThanOrEqual(1);
  expect(Math.abs(edges.badgeRight - edges.contentRight)).toBeLessThanOrEqual(1);
});

/* The run drawer's cost breakdown and job list, on a run with real cost. */
async function openCostlyRun(page: Page) {
  await page.goto(`${BASE}?view=runs&${FIXTURE_PERIOD}&search=RNA-seq`);
  await page.locator(".run-card", { hasText: "RNA-seq mixed execution demo" }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Cost breakdown by tool" })).toBeVisible();
  return drawer;
}

test("a run's cost breakdown is a hundred squares in a wide grid, and a text alternative", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  await expect(drawer.locator(".fp-cell")).toHaveCount(100);
  // Every square is the same size and has four rounded corners.
  const shapes = await drawer.locator(".fp-cell").evaluateAll(nodes => nodes.map(node => {
    const box = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return [Math.round(box.width), Math.round(box.height), style.borderRadius, style.boxShadow];
  }));
  expect(new Set(shapes.map(shape => shape.join("|"))).size).toBe(1);
  // They sit on one grid: the same columns in every row.
  const lefts = await drawer.locator(".fp-cell").evaluateAll(nodes => nodes.map(node => Math.round(node.getBoundingClientRect().left)));
  expect(new Set(lefts).size).toBeLessThanOrEqual(20);
  const grid = await drawer.locator(".fingerprint-cells").boundingBox();
  const frame = await drawer.boundingBox();
  expect(grid!.width).toBeGreaterThan(frame!.width - 64);
  // The drawer keeps its width; the squares fit inside it.
  expect(frame!.width).toBeLessThanOrEqual(441);
  // The parts are for the keyboard and screen readers, not listed under the chart.
  expect(await drawer.locator("button[data-part]").count()).toBeGreaterThan(0);
  await expect(drawer.locator("button[data-part]").first()).not.toBeInViewport({ ratio: 0.5 });
  await expect(drawer.locator("#part-placeholder")).toBeVisible();
  // Squares are not tab stops: the parts are.
  expect(await drawer.locator(".fp-cell[tabindex]").count()).toBe(0);
  await expect(drawer.locator(".job-groups .job-row").first()).toBeVisible();
});

test("a part opens from the keyboard, keeps focus, and the jobs stay whole below", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  const jobs = await drawer.locator(".job-groups .job-row").count();
  const first = drawer.locator("button[data-part]").first();
  await first.focus();
  await page.keyboard.press("Enter");
  await expect(first).toHaveAttribute("aria-pressed", "true");
  await expect(first).toBeFocused();
  await expect(drawer.locator("#part-detail")).toBeVisible();
  await expect(page).toHaveURL(/detail_part=/);
  expect(await drawer.locator(".job-groups .job-row").count()).toBe(jobs);
  await page.keyboard.press("Enter");
  await expect(drawer.locator("#part-detail")).toHaveCount(0);
  await expect(page).not.toHaveURL(/detail_part=/);
});

test("returning from a job restores the open part and the row that was pressed", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  await drawer.locator(".fp-cell").first().click();
  const row = drawer.locator("#part-detail .job-row").first();
  const jobId = await row.getAttribute("data-job-id");
  await row.click();
  await expect(drawer.getByRole("heading", { name: "Timeline", exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/detail_part=/);
  await drawer.getByRole("button", { name: "Back to workflow run" }).click();
  await expect(drawer.locator("#part-detail")).toBeVisible();
  await expect(page).toHaveURL(/detail_part=/);
  await expect(drawer.locator(`#part-detail [data-job-id="${jobId}"]`)).toBeFocused();
  // A reload of that address reproduces the same view.
  await page.reload();
  await expect(drawer.locator("#part-detail")).toBeVisible();
});

test("the first Escape clears a tooltip and the second closes the drawer", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  await drawer.locator(".fp-cell").first().hover();
  await expect(drawer.locator(".fp-tip")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer.locator(".fp-tip")).toHaveCount(0);
  await expect(drawer).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

for (const [width, height] of [[1280, 900], [390, 844], [320, 640]] as const) {
  test(`the run drawer has no sideways overflow and one-line job rows at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    const drawer = await openCostlyRun(page);
    await drawer.locator(".fp-cell").first().click();
    expect(await drawer.evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
    const rows = drawer.locator(".job-groups .job-row");
    const count = Math.min(await rows.count(), 12);
    for (let index = 0; index < count; index += 1) {
      const box = await rows.nth(index).boundingBox();
      expect(box!.height).toBeLessThanOrEqual(56);
      expect(await rows.nth(index).evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    }
    expect(await drawer.locator(".fp-cell").count()).toBe(100);
  });
}

test("the run drawer has no accessibility violations with a part open", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  await drawer.locator(".fp-cell").first().click();
  await expect(drawer.locator("#part-detail")).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.map(violation => `${violation.id}: ${violation.help}`)).toEqual([]);
});

test("the server's jobs are stated once and carry no cost column", async ({ page }) => {
  const drawer = await openCostlyRun(page);
  const server = drawer.locator(".job-group[data-environment='existing']");
  if (await server.count() === 0) test.skip(true, "This run has no jobs on the server.");
  await expect(server.locator(".group-summary")).toContainText("no compute charge");
  await expect(server.locator(".job-cost")).toHaveCount(0);
  expect(await server.innerText()).not.toContain("$0.00");
});

// One height where the drawer has more than fits, and one where it fits and has nothing to scroll.
for (const height of [500, 1000]) {
  test(`scrolling over the drawer never scrolls the page, at ${height}px high`, async ({ page }) => {
    await page.setViewportSize({ width: 1280, height });
    await page.goto(`${BASE}?view=runs&${FIXTURE_PERIOD}&search=RNA-seq`);
    await page.locator(".run-card", { hasText: "RNA-seq mixed execution demo" }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer.getByRole("heading", { name: "Cost breakdown by tool" })).toBeVisible();
    const before = await page.evaluate(() => window.scrollY);
    const box = await drawer.boundingBox();
    await page.mouse.move(box!.x + 100, box!.y + 200);
    for (const delta of [800, 800, -800, -800]) await page.mouse.wheel(0, delta);
    await page.waitForTimeout(200);
    expect(await page.evaluate(() => window.scrollY)).toBe(before);
    // Its own scrollbar takes no room, and the page's is not drawn while it is open.
    expect(await drawer.evaluate(node => getComputedStyle(node).scrollbarWidth)).toBe("none");
    expect(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarColor))
      .toContain("rgba(0, 0, 0, 0)");
  });
}

/* The Jobs page. */

async function openJobs(page: Page, extra = "") {
  await page.goto(`${BASE}?view=tool-runs&${RUNS_PERIOD}${extra}`);
  await expect(page.locator(".figures")).toBeVisible();
  await expect(page.locator(".job-card").first()).toBeVisible();
}

test("the Jobs page answers what the jobs cost, by tool, with every period choice", async ({ page, request }) => {
  const summary = await api(request, "summary");
  await openJobs(page);
  await expect(page.locator(".figure.featured .figure-amount")).toContainText(dollars(summary.amount));
  for (const period of ["Today", "Yesterday", "This week", "Last week", "This month", "Last month", "Custom dates"]) {
    await expect(page.getByRole("button", { name: period, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("tab", { name: "By tool" })).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".tool-row")).toHaveCount(12);
  await expect(page.getByPlaceholder("Find a job")).toBeVisible();
  await expect(page.getByText("Search by tool")).toBeVisible();
  // There is no Tools page any more.
  await expect(page.getByRole("button", { name: "Tools", exact: true })).toHaveCount(0);
  // No job numbers or invented context on the list.
  await expect(page.locator(".job-cards")).not.toContainText(/#\d|Job \d/);
  await expect(page.locator(".origin").first()).toHaveText(/Part of .+|Individual tool job|Workflow link not recorded/);
});

test("more tools keep one scale, and finding one leaves the report as it was", async ({ page }) => {
  await openJobs(page);
  const first = page.locator(".tool-row").first();
  const width = async () => (await first.locator(".bar").boundingBox())!.width;
  const before = await width();
  const headline = await page.locator(".figure.featured .figure-amount").textContent();
  await page.getByRole("button", { name: /Show \d+ more tools/ }).click();
  await expect(page.locator(".tool-row")).not.toHaveCount(12);
  expect(Math.abs((await width()) - before)).toBeLessThan(1);
  const last = (await page.locator(".tool-row .tool-name").last().textContent())!;
  await page.goto(`${BASE}?view=tool-runs&${RUNS_PERIOD}`);
  await page.getByLabel("Find a tool").fill(last);
  await expect(page.locator(".tool-row .tool-name", { hasText: last }).first()).toBeVisible();
  await expect(page.locator(".figure.featured .figure-amount")).toHaveText(headline!);
  await expect(page).not.toHaveURL(/search=/);
});

test("a tool's drawer ranks its costliest jobs and can list them all", async ({ page }) => {
  await openJobs(page);
  const row = page.locator(".tool-row").first();
  const name = (await row.locator(".tool-name").textContent())!;
  await row.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name, exact: true })).toBeFocused();
  await expect(drawer.getByRole("heading", { name: /jobs? contributing most to the cost/ })).toBeVisible();
  const rows = drawer.locator(".job-row");
  expect(await rows.count()).toBeLessThanOrEqual(5);
  const costs = await rows.locator(".job-cost").allTextContents();
  const values = costs.map(text => Number(text.replace(/[^0-9.]/g, "")));
  expect([...values].sort((a, b) => b - a)).toEqual(values);
  // The action sits under the ranked jobs.
  const show = drawer.getByRole("button", { name: /^Show \d+ jobs?$/ });
  expect((await show.boundingBox())!.y).toBeGreaterThan((await rows.last().boundingBox())!.y);
  // Opening the drawer changed no filter.
  await expect(page).not.toHaveURL(/tool_key=/);
  await show.click();
  await expect(drawer).toBeHidden();
  await expect(page).toHaveURL(/tool_key=/);
  await expect(page.getByRole("button", { name: /Tool:/ })).toBeVisible();
  await settle(page);
  await expect(page.locator(".job-open").first()).toHaveText(name);
  for (const title of await page.locator(".job-open").allTextContents()) expect(title).toBe(name);
});

test("tool, then job, then back to the tool puts the reader back", async ({ page }) => {
  await openJobs(page);
  await page.locator(".tool-row").first().click();
  const drawer = page.getByRole("dialog");
  const job = drawer.locator(".job-row").nth(1);
  const id = await job.getAttribute("data-job-id");
  await job.click();
  await expect(drawer.getByRole("heading", { name: "Compute", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/detail_parent_kind=tool/);
  // A reload keeps the way back.
  await page.reload();
  await drawer.getByRole("button", { name: "Back to tool" }).click();
  await expect(drawer.locator(`.job-row[data-job-id="${id}"]`)).toBeFocused();
});

test("a column opens its interval's jobs without filtering the page", async ({ page }) => {
  await openJobs(page, "&chart=time");
  await expect(page.getByRole("combobox", { name: /interval/i })).toHaveCount(0);
  const headline = await page.locator(".figure.featured .figure-amount").textContent();
  const url = page.url();
  const column = page.locator("button.job-col:not(.empty)").first();
  await column.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Jobs, highest cost first")).toBeVisible();
  await expect(column).toHaveAttribute("aria-current", "true");
  await expect(page.locator(".figure.featured .figure-amount")).toHaveText(headline!);
  await expect(page.getByRole("button", { name: /Runs active|Tool:/ })).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("from")).toBe(new URL(url).searchParams.get("from"));
  await drawer.locator(".job-row").first().click();
  await expect(drawer).toContainText(/falls inside|Estimated compute cost/);
  await drawer.getByRole("button", { name: /Back to selected (day|hour|week)/ }).click();
  await expect(drawer.getByText("Jobs, highest cost first")).toBeVisible();
});

test("the Tools page's links open the Jobs page by tool", async ({ page }) => {
  await page.goto(`${BASE}?view=tools&${RUNS_PERIOD}`);
  await expect(page.getByRole("heading", { name: "Jobs", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/view=tool-runs/);
  await expect(page.getByRole("tab", { name: "By tool" })).toHaveAttribute("aria-selected", "true");
});

test("the Jobs page has no accessibility violations, drawers included", async ({ page }) => {
  await openJobs(page);
  const scan = async () => {
    const results = await new AxeBuilder({ page }).exclude(".chart-tip").analyze();
    expect(results.violations).toEqual([]);
  };
  await scan();
  await page.locator(".tool-row").first().click();
  await expect(page.getByRole("dialog").locator(".job-row").first()).toBeVisible();
  await scan();
  await page.keyboard.press("Escape");
  await page.getByRole("tab", { name: "Over time" }).click();
  await page.locator("button.job-col:not(.empty)").first().click();
  await expect(page.getByRole("dialog").getByText("Jobs, highest cost first")).toBeVisible();
  await scan();
});

test("a workflow job names its run, which opens from the list", async ({ page }) => {
  await openJobs(page);
  const link = page.locator(".origin-run").first();
  const name = (await link.textContent())!.trim();
  await link.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByText("Workflow run", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("heading", { name, exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(link).toBeFocused();
  // Pressing the rest of the card still opens the job itself.
  const card = page.locator(".job-card").first();
  const box = (await card.boundingBox())!;
  await card.click({ position: { x: box.width - 30, y: box.height / 2 } });
  await expect(drawer.getByRole("heading", { name: "Compute", exact: true })).toBeVisible();
});
