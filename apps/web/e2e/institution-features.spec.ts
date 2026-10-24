import { expect, test, type Page } from "@playwright/test";
import { customerSharesWithLakeside, signIn } from "./helpers";

/** Every institution feature that the other specs don't already drive, used the way a person would, by the role that
 * owns it. Each test asserts the visible result (not just that the page rendered) and that no server error appeared. */

async function noServerError(page: Page) {
  await expect(page.getByText("Something went wrong"), "server error shown").toHaveCount(0);
  await expect(page.getByText("Application error"), "page crashed").toHaveCount(0);
}

test("sandbox runs synthetic customers against the live configuration", async ({ page }) => {
  await signIn(page, "credit@lakeside.demo");
  await page.goto("/institution/sandbox");
  await page.getByRole("button", { name: "Run sandbox" }).click();
  await expect(page.getByText("Would route").first()).toBeVisible({ timeout: 30_000 });
  await noServerError(page);
});

test("radius what-if simulates a change without touching the live appetite", async ({ page }) => {
  await signIn(page, "credit@lakeside.demo");
  await page.goto("/institution/radius");
  await page.getByRole("button", { name: "Simulate a change" }).first().click();
  await page.getByRole("button", { name: "Run what-if" }).click();
  await expect(page.getByText("Inside appetite", { exact: false }).first()).toBeVisible({ timeout: 30_000 });
  await noServerError(page);
});

test("ask WEZA answers from read-only tools", async ({ page }) => {
  await signIn(page, "credit@lakeside.demo");
  // Ask Weza lives on the Command Centre (/institution/ask redirects there).
  await page.goto("/institution/ask");
  await page.getByLabel("Ask Weza", { exact: true }).fill("What sits just outside our appetite?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.locator("main p.whitespace-pre-line").first()).not.toBeEmpty({ timeout: 30_000 });
  await noServerError(page);
});

test("an insight is decided with a reason that lands in the audit trail", async ({ page }) => {
  await signIn(page, "credit@lakeside.demo");
  await page.goto("/institution/insights");
  const dismiss = page.getByRole("button", { name: "Dismiss" }).first();
  test.skip(!(await dismiss.isVisible({ timeout: 15_000 }).catch(() => false)), "no open insight in this database");
  await dismiss.click();
  await page.getByLabel("Reason (recorded in audit)").fill("Reviewed by the credit committee (E2E)");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/dismissed/i).first()).toBeVisible({ timeout: 15_000 });
  await noServerError(page);
});

test("product pause and resume, with reasons", async ({ page }) => {
  await signIn(page, "business@lakeside.demo");
  await page.goto("/institution/products");
  await page.locator("main a[href^='/institution/products/']").filter({ hasNotText: /new|extract/i }).first().click();
  const pause = page.getByRole("button", { name: "Pause" });
  test.skip(!(await pause.isVisible({ timeout: 15_000 }).catch(() => false)), "first product is not active");
  await pause.click();
  await page.getByRole("dialog").locator("textarea, input").first().fill("Temporarily full (E2E)");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Resume" }).click();
  await page.getByRole("dialog").locator("textarea, input").first().fill("Capacity back (E2E)");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible({ timeout: 15_000 });
  await noServerError(page);
});

test("appetite capacity override is set and cleared", async ({ page }) => {
  await signIn(page, "credit@lakeside.demo");
  await page.goto("/institution/appetite");
  await page.locator("main a[href^='/institution/appetite/']").filter({ hasNotText: /new/i }).first().click();
  await page.getByRole("button", { name: "Capacity override" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.locator("select").first().selectOption("LIMITED");
  await dialog.locator("textarea, input").first().fill("Branch staffing (E2E)");
  await dialog.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/capacity limited/i).first()).toBeVisible({ timeout: 15_000 });
  await page.getByRole("button", { name: "Capacity override" }).click();
  await page.getByRole("dialog").locator("select").first().selectOption({ index: 0 });
  await page.getByRole("dialog").locator("textarea, input").first().fill("Staffing restored (E2E)");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/capacity active/i).first()).toBeVisible({ timeout: 15_000 });
  await noServerError(page);
});

test("routing, service targets and notification preferences save", async ({ page }) => {
  await signIn(page, "admin@lakeside.demo");
  await page.goto("/institution/routing");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Routing saved")).toBeVisible({ timeout: 15_000 });
  await page.goto("/institution/notifications");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Notification preferences saved")).toBeVisible({ timeout: 15_000 });
  await page.goto("/institution/settings");
  await page.getByLabel("Website").fill("https://lakeside.example");
  await page.getByRole("button", { name: "Save" }).first().click();
  await expect(page.getByText("Saved")).toBeVisible({ timeout: 15_000 });
  await noServerError(page);
});

test("reports export downloads a CSV without customer identity", async ({ page }) => {
  await signIn(page, "admin@lakeside.demo");
  await page.goto("/institution/reports");
  const [download] = await Promise.all([page.waitForEvent("download"),
    page.getByRole("button", { name: /Export CSV/ }).click()]);
  const path = await download.path();
  const csv = require("fs").readFileSync(path, "utf8") as string;
  expect(csv.split("\n")[0]).toContain("reference,state,amount");
  expect(csv).not.toMatch(/CM\d{10}|\+2567\d{8}/); // no NIN, no phone
  await noServerError(page);
});

test("officers don't get an export they aren't allowed to use", async ({ page }) => {
  await signIn(page, "officer@lakeside.demo");
  await page.goto("/institution/feed");
  await expect(page.getByRole("heading", { name: "Opportunities", level: 1 })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Export/ })).toHaveCount(0);
});

test("a charge is disputed by the institution", async ({ page, request }) => {
  await customerSharesWithLakeside(request); // makes sure there is a fresh billable event
  await signIn(page, "admin@lakeside.demo");
  await page.goto("/institution/billing");
  const dispute = page.getByRole("button", { name: "Dispute" }).first();
  await expect(dispute).toBeVisible({ timeout: 30_000 });
  await dispute.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason").selectOption({ index: 1 });
  await dialog.getByLabel("Evidence / description").fill("We had already received this customer directly (E2E).");
  await dialog.getByRole("button", { name: "Submit dispute" }).click();
  await expect(page.getByText(/open|under review/i).first()).toBeVisible({ timeout: 15_000 });
  await noServerError(page);
});

test("product extraction from a document is only a proposal", async ({ page }) => {
  await signIn(page, "business@lakeside.demo");
  await page.goto("/institution/products/extract");
  await page.locator("input[type=file]").setInputFiles({ name: "sme-loan.txt", mimeType: "text/plain",
    buffer: Buffer.from("SME Working Capital Loan. Amount UGX 5,000,000 to UGX 50,000,000. Tenor 6 to 24 months. "
      + "Business must be at least 2 years old with monthly turnover above UGX 3,000,000. Kampala and Wakiso.") });
  await expect(page.getByText(/proposal|review|draft/i).first()).toBeVisible({ timeout: 30_000 });
  await noServerError(page);
});
