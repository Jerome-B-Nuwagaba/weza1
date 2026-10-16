import { expect, test } from "@playwright/test";
import { signIn, staffToken } from "./helpers";

/** Join → WEZA verifies → the institution's administrator lands on its activation checklist (AT-22…AT-24). */
test("an institution applies, WEZA verifies it, and its admin starts setup", async ({ page, request }) => {
  const suffix = Math.random().toString(36).slice(2, 8);
  const legal = `E2E Lender ${suffix} Ltd`;
  const adminEmail = `admin@e2e-${suffix}.co.ug`;
  const password = "E2e-Str0ng-Passw0rd!";

  await page.goto("/institution/join");
  await page.getByLabel("Legal name").fill(legal);
  await page.getByLabel("Institution type").selectOption({ index: 1 });
  await page.getByLabel("Licence / registration number").fill(`E2E-${suffix}`);
  await page.getByLabel("Representative name").fill("Rep E2E");
  await page.getByLabel("Representative email").fill(`rep@e2e-${suffix}.co.ug`);
  await page.getByLabel("Compliance contact name").fill("Compliance E2E");
  await page.getByLabel("Compliance email").fill(`comp@e2e-${suffix}.co.ug`);
  await page.getByLabel("Full name").fill("Admin E2E");
  await page.getByLabel("Email", { exact: false }).last().fill(adminEmail);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByText("Application received", { exact: true })).toBeVisible();

  // The new admin can sign in but is waiting on WEZA
  await signIn(page, adminEmail, password);
  await page.goto("/institution/onboarding");
  await expect(page.getByText("Awaiting WEZA verification")).toBeVisible();

  // WEZA Operations approves it from the admin console
  const ops = await staffToken(request, "ops@weza.demo");
  const list = await (await request.get("/api/v1/admin/institutions", { headers: ops })).json();
  const inst = list.institutions.find((i: any) => i.legal_name === legal);
  expect(inst).toBeTruthy();
  await page.evaluate(() => window.sessionStorage.clear());
  await page.context().clearCookies();
  await signIn(page, "ops@weza.demo");
  await page.goto(`/admin/institutions/${inst.id}`);
  await page.getByRole("button", { name: "Approve" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason / evidence checked").fill("Licence checked with regulator (E2E)");
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Configuring").first()).toBeVisible();

  // Back as the institution admin: verification is done, setup steps remain, activation is not yet possible
  await page.evaluate(() => window.sessionStorage.clear());
  await page.context().clearCookies();
  await signIn(page, adminEmail, password);
  await page.goto("/institution/onboarding");
  await expect(page.getByText("Awaiting WEZA verification")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Set up" }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "ACTIVATE ON WEZA" })).toBeDisabled();
});
