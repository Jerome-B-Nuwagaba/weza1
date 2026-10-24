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
