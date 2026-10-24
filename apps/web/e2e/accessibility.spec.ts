import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

/** Accessibility (BRD §38): the main screens are scanned with axe against WCAG 2.1 A and AA. Critical violations fail
 * the build (a control a keyboard or screen-reader user cannot operate). Serious ones are listed in the test output so
 * they can be worked down without blocking every release; tighten `BLOCKING` to include "serious" once the list is empty. */
const BLOCKING = ["critical"];
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function scan(page: Page, label: string) {
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const summary = (v: (typeof violations)[number]) => `${v.impact} ${v.id} (${v.nodes.length}): ${v.help}`;
  const serious = violations.filter((v) => v.impact === "serious");
  if (serious.length) console.log(`[a11y] ${label} serious:\n  ${serious.map(summary).join("\n  ")}`);
  const blocking = violations.filter((v) => BLOCKING.includes(v.impact || ""));
  expect.soft(blocking.map(summary), `${label} has blocking accessibility violations`).toEqual([]);
}

test("the sign-in page is accessible", async ({ page }) => {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await scan(page, "/login");
});

test("the customer chat is accessible", async ({ page }) => {
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await scan(page, "/");
});

test("the main institution screens are accessible", async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, "admin@lakeside.demo");
  for (const path of ["/institution", "/institution/feed", "/institution/appetite", "/institution/users",
    "/institution/notifications"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await scan(page, path);
  }
});
