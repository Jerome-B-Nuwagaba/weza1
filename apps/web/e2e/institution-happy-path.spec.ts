import { expect, test, type APIRequestContext } from "@playwright/test";
import { customerSharesWith, signIn, staffToken } from "./helpers";

/**
 * E2E-01 (blueprint 12; resiliency spec §7): one brand-new institution, end to end —
 * Apply → Verify → Activate → Receive opportunity → Request info → Customer fulfils → Report outcome.
 * Configuration steps that have their own specs and backend tests (users, product maker-checker, appetite
 * simulation, routing) are done through the API; every decision point a person takes is driven in the browser.
 */
const API = "/api/v1";

async function ok(r: Awaited<ReturnType<APIRequestContext["post"]>>): Promise<any> {
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

test("a new institution goes from application to a reported outcome", async ({ page, request }) => {
  test.setTimeout(240_000);
  const s = Math.random().toString(36).slice(2, 8);
  const name = `Happy Path ${s} Finance`;
  const pw = "E2e-Str0ng-Passw0rd!";
  const email = (who: string) => `${who}@hp-${s}.co.ug`;

  // 1. Apply (browser)
  await page.goto("/institution/join");
  await page.getByLabel("Legal name").fill(`${name} Ltd`);
  await page.getByLabel("Display name").fill(name);
  await page.getByLabel("Institution type").selectOption({ index: 1 });
  await page.getByLabel("Licence / registration number").fill(`HP-${s}`);
  await page.getByLabel("Representative name").fill("Rep HP");
  await page.getByLabel("Representative email").fill(email("rep"));
  await page.getByLabel("Compliance contact name").fill("Compliance HP");
  await page.getByLabel("Compliance email").fill(email("comp"));
  await page.getByLabel("Full name").fill("Admin HP");
  await page.getByLabel("Email", { exact: false }).last().fill(email("admin"));
  await page.getByLabel("Password").fill(pw);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByText("Application received", { exact: true })).toBeVisible();

  // 2. WEZA Operations verifies (browser)
  const ops = await staffToken(request, "ops@weza.demo");
  const inst = (await (await request.get(`${API}/admin/institutions`, { headers: ops })).json())
    .institutions.find((i: any) => i.display_name === name);
  await signIn(page, "ops@weza.demo");
  await page.goto(`/admin/institutions/${inst.id}`);
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("dialog").getByLabel("Reason / evidence checked").fill("Licence checked (E2E happy path)");
  await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Configuring").first()).toBeVisible();

  // 3. Configure (API): team & users, product (maker-checker), appetite (simulate → approve), routing, notifications
  const admin = await staffToken(request, email("admin"), pw);
  const team = await ok(await request.post(`${API}/inst/teams`, { headers: admin, data: { name: "SME desk" } }));
  for (const [who, roles] of [["biz", ["BUSINESS", "CREDIT_RISK"]], ["officer", ["OFFICER"]], ["manager", ["MANAGER"]]] as const) {
    await ok(await request.post(`${API}/inst/users`, { headers: admin, data: { full_name: `${who} HP`, email: email(who), roles, team_id: team.id, password: pw } }));
  }
  const biz = await staffToken(request, email("biz"), pw);
  const prod = await ok(await request.post(`${API}/inst/products`, { headers: biz, data: {
    name: `HP Stock Loan ${s}`, family: "SME_WORKING_CAPITAL",
    terms: { min_amount: 1_000_000, max_amount: 60_000_000, min_tenor_months: 3, max_tenor_months: 36 },
    rules: [{ field: "customer_type", op: "in", value: ["SME"] }] } }));
  await ok(await request.post(`${API}/inst/products/${prod.product_id}/submit`, { headers: biz }));
  await ok(await request.post(`${API}/inst/products/${prod.product_id}/review`, { headers: admin, data: { approve: true, note: "ok" } }));
  const ap = await ok(await request.post(`${API}/inst/appetites`, { headers: biz, data: {
    name: "Central SMEs", product_ids: [prod.product_id], criteria: [{ field: "region", op: "in", value: ["Central"] }], min_match_score: 50 } }));
  await ok(await request.post(`${API}/inst/appetites/${ap.appetite_id}/simulate`, { headers: biz }));
  await ok(await request.post(`${API}/inst/appetites/${ap.appetite_id}/review`, { headers: admin, data: { approve: true, note: "ok" } }));
  await request.put(`${API}/inst/routing`, { headers: admin, data: { rules: [{ name: "All", conditions: {}, target_team_id: team.id }] } });
  const prefs = (await (await request.get(`${API}/inst/notification-prefs`, { headers: admin })).json()).prefs;
  await request.put(`${API}/inst/notification-prefs`, { headers: admin, data: { prefs } });

  // 4. Activate (browser)
  await page.evaluate(() => window.sessionStorage.clear());
  await page.context().clearCookies();
  await signIn(page, email("admin"), pw);
  await page.goto("/institution/onboarding");
  await page.getByRole("button", { name: "ACTIVATE ON WEZA" }).click();
  await expect(page.getByText("You're live on WEZA")).toBeVisible();

  // 5. A customer chooses the new institution; routing assigns the officer
  const { reference, oppId, customer } = await customerSharesWith(request, name, "I need UGX 25 million to buy stock for my pharmacy");

  // 6. Officer receives it and asks a question tied to a profile field (browser)
  await page.evaluate(() => window.sessionStorage.clear());
  await page.context().clearCookies();
  await signIn(page, email("officer"), pw);
  await page.goto(`/institution/opportunities/${oppId}`);
  await expect(page.getByRole("heading", { name: reference })).toBeVisible();
  await page.getByRole("button", { name: "Mark contacted" }).click();
  await page.getByRole("button", { name: "Ask the customer…" }).click();
  const ask = page.getByRole("dialog");
  await ask.getByLabel("What do you need?").selectOption("QUESTION");
  await ask.getByLabel("Your question").fill("What is your current monthly turnover?");
  await ask.getByLabel("Save the answer to profile field (optional)").selectOption("business.monthly_turnover");
  await ask.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Waiting for customer", { exact: true }).first()).toBeVisible();

  // 7. Customer fulfils (spec route)
  await expect.poll(async () => (await (await request.get(`${API}/me/info-requests`, { headers: customer })).json()).open).toBe(1);
  const req = (await (await request.get(`${API}/me/info-requests`, { headers: customer })).json()).requests[0];
  await ok(await request.post(`${API}/me/info-requests/${req.id}/fulfil`, { headers: customer, data: { response_text: "14 million" } }));

  // 8. Officer sees the answer and reports the outcome (browser)
  await page.reload();
  await expect(page.getByText("14 million")).toBeVisible();
  await page.getByRole("button", { name: "Reported approved…" }).click();
  await page.getByRole("dialog").getByLabel("Approved amount (UGX)").fill("22000000");
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Outcome recorded")).toBeVisible();

  // The customer sees the institution-reported outcome
  const needs = await (await request.get(`${API}/me/needs`, { headers: customer })).json();
  const opp = needs.needs.flatMap((n: any) => n.opportunities).find((o: any) => o.id === oppId);
  expect(opp.state).toBe("REPORTED_APPROVED");
  expect(opp.outcomes.at(-1).reported_by).toBe(name);
});
