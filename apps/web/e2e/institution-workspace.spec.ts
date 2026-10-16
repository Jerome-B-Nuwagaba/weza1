import { expect, test } from "@playwright/test";
import { signIn, staffToken } from "./helpers";

/** Users & roles and Settings: an administrator edits roles, renames a team and resets a colleague's password;
 * the colleague signs in with it and changes their own password. */
test("administrator manages roles, teams and passwords; a user changes their own password", async ({ page, request }) => {
  test.setTimeout(150_000);
  const s = Math.random().toString(36).slice(2, 8);
  const pw = "E2e-Str0ng-Passw0rd!";
  const email = (who: string) => `${who}@ws-${s}.co.ug`;
  const r = await request.post("/api/v1/institutions/applications", { data: {
    legal_name: `Workspace ${s} Ltd`, institution_type: "Fintech Lender", licence_no: `WS-${s}`, regulator: "Other",
    representative: { name: "Rep", email: email("rep") }, compliance: { name: "Comp", email: email("comp") },
    admin_name: "Admin WS", admin_email: email("admin"), admin_password: pw, accept_terms: true } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const ops = await staffToken(request, "ops@weza.demo");
  await request.post(`/api/v1/admin/institutions/${(await r.json()).institution_id}/verify`, { headers: ops, data: { approve: true, reason: "ok" } });
  const admin = await staffToken(request, email("admin"), pw);
  const team = await (await request.post("/api/v1/inst/teams", { headers: admin, data: { name: "Desk" } })).json();
  await request.post("/api/v1/inst/users", { headers: admin, data: { full_name: "Olivia Officer", email: email("off"), roles: ["OFFICER"], team_id: team.id, password: pw } });

  await signIn(page, email("admin"), pw);
  await page.goto("/institution/users");
  const row = page.getByRole("row", { name: /Olivia Officer/ });

  // Edit roles
  await row.getByRole("button", { name: "Roles" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Compliance" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(row.getByText("Compliance")).toBeVisible();

  // Rename the team
  await page.getByRole("button", { name: "Rename" }).click();
  await page.getByRole("dialog").getByLabel("Team name").fill("SME Desk");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "SME Desk" })).toBeVisible();

  // Reset the colleague's password
  await row.getByRole("button", { name: "Reset password" }).click();
  await page.getByRole("dialog").getByLabel("New temporary password").fill("Temp-Reset-Passw0rd!");
  await page.getByRole("dialog").getByRole("button", { name: "Reset" }).click();
  await expect(page.getByText(/Password reset for Olivia Officer/)).toBeVisible();

  // The colleague signs in with it and changes their own password
  await page.evaluate(() => window.sessionStorage.clear());
  await page.context().clearCookies();
  await signIn(page, email("off"), "Temp-Reset-Passw0rd!");
  await page.goto("/institution/settings");
  await page.getByLabel("Current password").fill("Temp-Reset-Passw0rd!");
  await page.getByLabel("New password", { exact: false }).first().fill("Mine-Own-Passw0rd!");
  await page.getByLabel("Confirm new password").fill("Mine-Own-Passw0rd!");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText(/Password changed/)).toBeVisible();
  expect((await request.post("/api/v1/auth/login", { data: { email: email("off"), password: "Mine-Own-Passw0rd!" } })).ok()).toBeTruthy();
});
