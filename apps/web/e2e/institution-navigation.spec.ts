import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

/** The five-section workspace: the sidebar and the section tabs come from one config, follow the person's
 * role, and keep the current section and page marked. */

const SECTIONS = ["Command Centre", "Opportunities", "Products & Appetite", "Team & Routing", "Settings"];

test("an administrator sees all five sections, with the current one marked", async ({ page }) => {
  await signIn(page, "admin@lakeside.demo");
  const sidebar = page.getByRole("complementary", { name: "Workspace" });
  for (const name of SECTIONS) await expect(sidebar.getByRole("link", { name, exact: true })).toBeVisible();

  // A page deep inside a section lights its sidebar item and its own tab — including a page that is not a tab.
  for (const path of ["/institution/appetite", "/institution/appetite/new"]) {
    await page.goto(path);
    await expect(sidebar.getByRole("link", { name: "Products & Appetite", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(sidebar.getByRole("link", { name: "Opportunities", exact: true })).not.toHaveAttribute("aria-current", "page");
    const tabs = page.getByRole("navigation", { name: "Products & Appetite sections" });
    await expect(tabs.getByRole("link", { name: "Appetite", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(tabs.getByRole("link", { name: "Products", exact: true })).not.toHaveAttribute("aria-current", "page");
  }

  // Settings carries the administrator's billing and compliance pages.
  await page.goto("/institution/settings");
  const settings = page.getByRole("navigation", { name: "Settings sections" });
  for (const name of ["Organisation", "Activation", "Notifications", "Compliance", "Billing"]) {
    await expect(settings.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await expect(sidebar.getByRole("link", { name: "Settings", exact: true })).toHaveAttribute("aria-current", "page");
});

test("an officer is only offered the pages their role can open", async ({ page }) => {
  await signIn(page, "officer@lakeside.demo");
  const sidebar = page.getByRole("complementary", { name: "Workspace" });

  await page.goto("/institution/feed");
  const opportunities = page.getByRole("navigation", { name: "Opportunities sections" });
  await expect(opportunities.getByRole("link", { name: "All opportunities", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(opportunities.getByRole("link", { name: "My work", exact: true })).toBeVisible();
  // Pages the officer's role cannot open are not offered as dead ends.
  for (const name of ["Previews", "Outcomes"]) {
    await expect(opportunities.getByRole("link", { name, exact: true })).toHaveCount(0);
  }

  // The sidebar leads each section to a page the officer can open.
  await sidebar.getByRole("link", { name: "Products & Appetite", exact: true }).click();
  await expect(page).toHaveURL(/\/institution\/products$/);
  const supply = page.getByRole("navigation", { name: "Products & Appetite sections" });
  await expect(supply.getByRole("link", { name: "Appetite", exact: true })).toBeVisible();
  for (const name of ["Market fit", "Demand", "Gaps", "Recommendations", "Test changes"]) {
    await expect(supply.getByRole("link", { name, exact: true })).toHaveCount(0);
  }

  await page.goto("/institution/settings");
  const settings = page.getByRole("navigation", { name: "Settings sections" });
  await expect(settings.getByRole("link", { name: "Organisation", exact: true })).toBeVisible();
  for (const name of ["Compliance", "Billing"]) {
    await expect(settings.getByRole("link", { name, exact: true })).toHaveCount(0);
  }
});

test("the Command Centre is a calm front door: greeting, Ask Weza, suggestions and at most three insights", async ({ page }) => {
  await signIn(page, "manager@lakeside.demo");
  await page.goto("/institution");
  await expect(page.getByRole("heading", { level: 1, name: /^Good (morning|afternoon|evening), / })).toBeVisible();
  await expect(page.getByLabel("Ask Weza", { exact: true })).toBeVisible();
  const insights = page.getByRole("region", { name: "Insights from your workspace" });
  await expect(insights).toBeVisible();
  await expect(insights.locator("[aria-busy=true]")).toHaveCount(0, { timeout: 30_000 });
  expect(await insights.getByRole("listitem").count()).toBeLessThanOrEqual(3);
  // The old dashboard content now lives under Opportunities, not on the Command Centre.
  await expect(page.getByRole("heading", { name: "Priority opportunities" })).toHaveCount(0);

  // A suggestion asks Weza and the answer links to where the work is.
  const suggestions = page.getByRole("list", { name: "Suggested questions" });
  await suggestions.getByRole("button", { name: "Show current team workload" }).click();
  await expect(page.locator("main p.whitespace-pre-line").first()).toContainText("open opportunities", { timeout: 30_000 });
  await expect(page.getByRole("link", { name: "Team workload" })).toBeVisible();

  // The priority table and needs-attention queue are one tab away.
  await page.goto("/institution/priority");
  await expect(page.getByRole("heading", { name: "Priority opportunities" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Needs attention" })).toBeVisible();
  const tabs = page.getByRole("navigation", { name: "Opportunities sections" });
  await expect(tabs.getByRole("link", { name: "Priority & attention", exact: true })).toHaveAttribute("aria-current", "page");
});

test("the chevron beside Command Centre collapses and expands the sidebar", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await signIn(page, "admin@lakeside.demo");
  await page.goto("/institution/products");
  const sidebar = page.getByRole("complementary", { name: "Workspace" });
  await sidebar.getByRole("button", { name: "Collapse menu" }).click();
  await expect(sidebar.getByText("Products & Appetite", { exact: true })).toHaveCount(0);
  await expect(sidebar.getByRole("link", { name: "Products & Appetite", exact: true })).toHaveAttribute("aria-current", "page");
  await sidebar.getByRole("button", { name: "Expand menu" }).click();
  await expect(sidebar.getByText("Products & Appetite", { exact: true })).toBeVisible();
});
