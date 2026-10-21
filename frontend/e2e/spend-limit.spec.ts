import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PREFIX = process.env.PREFIX_URL || process.env.BASE_URL || "http://localhost:8000/";
const root = PREFIX.endsWith("/") ? PREFIX : `${PREFIX}/`;
const headers = { "X-Rainstone-Tenant": "anvil-demo", "X-Rainstone-User": "admin", "X-Rainstone-Admin": "true" };
const endpoint = new URL("api/spend-guard", root).href;

test("set, trigger, raise and turn off a Batch limit with the keyboard", async ({ page }, info) => {
  test.setTimeout(60_000);
  const initial = await (await page.request.get(endpoint, { headers })).json();
  if (initial.limit !== null) await page.request.put(endpoint, { headers, data: { revision: initial.revision, limit: null, stop_jobs: false } });
  try {
    await page.goto(`${root}?view=overview&period=last-month&timezone=UTC`);
    const original = await page.locator(".figure.featured .figure-amount").innerText();
    const entry = page.getByRole("link", { name: "Set a Batch spend limit", exact: true });
    await entry.focus(); await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/view=limit/);
    await expect(page).toHaveURL(/period=last-month/);
    await expect(page.getByRole("heading", { name: "Batch spend limit", exact: true })).toBeVisible();
    const state = await (await page.request.get(endpoint, { headers })).json();
    const nearLimit = (Math.ceil(Number(state.snapshot.amount) * 100) / 100 + .10).toFixed(2);
    const input = page.getByLabel("Batch spend limit (USD)");
    await input.focus(); await page.keyboard.type(nearLimit);
    const finish = page.getByRole("radio", { name: /Let jobs already on Batch finish/ });
    await finish.focus(); await page.keyboard.press("Space");
    await input.focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Save this Batch limit?" })).toBeFocused();
    await expect(page.getByText(/already within the current margin/)).toBeVisible();
    await page.keyboard.press("Tab"); await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: "New Batch jobs paused", exact: true })).toBeVisible();
    await expect(page.locator(".limit-result")).toContainText("New Batch jobs are paused");

    await input.focus(); await input.fill("5.00"); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Save this Batch limit?" })).toBeFocused();
    await page.keyboard.press("Tab"); await page.keyboard.press("Enter");
    await expect(page.getByRole("link", { name: /Batch limit \$5.00/ })).toBeVisible();
    await page.getByRole("button", { name: "Overview", exact: true }).focus(); await page.keyboard.press("Enter");
    await expect(page.locator(".figure.featured .figure-amount")).toHaveText(original);
    await expect(page.locator(".limit-progress")).toContainText("$5.00 Batch limit recorded so far");
    await page.getByRole("link", { name: "Manage Batch limit" }).focus(); await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/view=limit/);
    await page.reload();
    await expect(input).toHaveValue("5.00");
    const accessibility = await new AxeBuilder({ page }).analyze();
    expect(accessibility.violations).toEqual([]);
    await page.screenshot({ path: info.outputPath("spend-limit-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByRole("link", { name: /Batch limit \$5.00/ })).toBeVisible();
    await page.screenshot({ path: info.outputPath("spend-limit-mobile.png"), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole("button", { name: "Turn off limit", exact: true }).focus(); await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Turn off your Batch limit?" })).toBeFocused();
    await page.keyboard.press("Tab"); await page.keyboard.press("Enter");
    await expect(page.locator(".limit-result")).toContainText("turned off");
    await expect(page.getByRole("link", { name: "Set a Batch spend limit", exact: true })).toBeVisible();
  } finally {
    const state = await (await page.request.get(endpoint, { headers })).json();
    if (state.limit !== null) await page.request.put(endpoint, { headers, data: { revision: state.revision, limit: null, stop_jobs: false } });
  }
});
