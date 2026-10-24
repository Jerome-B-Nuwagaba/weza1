import { expect, test } from "@playwright/test";
import { signIn, staffToken } from "./helpers";

const API = "/api/v1";

/** WEZA Staff: the institution onboarding flow (Goal 2).
 *
 *  A WEZA administrator creates an institution in Draft, records its primary contact, gives it an
 *  administrator, reviews readiness, and activates it once the institution itself has built its supply.
 *  The same page pauses it again. */

async function apiPost(request: any, path: string, headers: any, body: any) {
  const r = await request.post(`${API}${path}`, { data: body, headers });
  expect(r.ok(), await r.text()).toBeTruthy();
  return r.json();
}

/** What the market looks like right now: how many institutions, products and mandates are live. */
async function marketSupply(request: any, token: any) {
  const m = await (await request.get(`${API}/admin/market`, { headers: token })).json();
  const s = m.state.supply;
  const appetites = Object.values(s.appetites_by_capacity as Record<string, number>)
    .reduce((a: number, b: any) => a + Number(b), 0);
  return { institutions: s.active_institutions as number, products: s.active_products as number, appetites };
}

test("unauthorised users cannot reach the Weza Staff area", async ({ page, request }) => {
  // Anonymous: the shell sends them to sign in.
  await page.goto("/staff/institutions");
  await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });

  // An institution administrator is a tenant, not WEZA staff: refused by the API.
  const instAdmin = await staffToken(request, "admin@lakeside.demo");
  const r = await request.get(`${API}/staff/institutions`, { headers: instAdmin });
  expect(r.status()).toBe(403);

  // A WEZA user without the administrator role: refused too.
  const ops = await staffToken(request, "ops@weza.demo");
  expect((await request.get(`${API}/staff/institutions`, { headers: ops })).status()).toBe(403);
  expect((await request.post(`${API}/staff/institutions`, { headers: ops, data: { legal_name: "Nope Ltd" } })).status()).toBe(403);
});

test("WEZA staff onboard an institution and take it live, then pause it", async ({ page, request }) => {
  const suffix = Math.random().toString(36).slice(2, 8);
  const legal = `E2E Staff Bank ${suffix} Ltd`;
  const trading = `E2E Staff Bank ${suffix}`;
  const adminEmail = `admin@e2e-staff-${suffix}.co.ug`;
  const adminPassword = "E2e-Staff-Passw0rd!";

  // ---- WEZA staff sign in and create the institution in Draft.
  await signIn(page, "admin@weza.demo");
  const weza = await staffToken(request, "admin@weza.demo");
  await page.goto("/staff/institutions");
  await page.waitForLoadState("networkidle");
  // Start from a settled page: the staff area fetches its list, and the test then fills a form on it.
  await page.reload();
  await expect(page.getByRole("heading", { name: "Institutions" })).toBeVisible();

  await page.getByRole("button", { name: "New institution" }).click();
  const create = page.getByRole("dialog");
  await create.getByLabel("Legal name").fill(legal);
  await create.getByLabel("Trading name").fill(trading);
  await create.getByLabel("Institution type").selectOption({ label: "Commercial Bank" });
  await create.getByLabel("Regulator").selectOption({ label: "Bank of Uganda" });
  await create.getByLabel("Licence number").fill(`E2E-STAFF-${suffix}`);
  await create.getByRole("button", { name: "Create in draft" }).click();

  await expect(page).toHaveURL(/\/staff\/institutions\/[0-9a-f-]+$/, { timeout: 15_000 });
  const instId = page.url().split("/").pop()!;
  await expect(page.getByText("Draft", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Not ready yet")).toBeVisible();

  // ---- The primary contact.
  await page.getByRole("button", { name: "Set contact" }).click();
  const contact = page.getByRole("dialog");
  await contact.getByLabel("Name").fill("Priya Head");
  await contact.getByLabel("Email").fill(`priya@e2e-staff-${suffix}.co.ug`);
  await contact.getByLabel("Phone").fill("+256700000001");
  await contact.getByRole("button", { name: "Save contact" }).click();
  await expect(page.getByText("priya@e2e-staff-" + suffix + ".co.ug")).toBeVisible();

  // ---- The institution's administrator.
  await page.getByRole("button", { name: "Create", exact: true }).click();
  const createAdmin = page.getByRole("dialog");
  await createAdmin.getByLabel("Full name").fill("Chief Admin");
  await createAdmin.getByLabel("Email").fill(adminEmail);
  await createAdmin.getByLabel("Initial password").fill(adminPassword);
  await createAdmin.getByRole("button", { name: "Create administrator" }).click();
  await expect(page.getByText("Chief Admin")).toBeVisible();

  // The new administrator is a normal institution account: it signs in and reaches its own workspace.
  const adminToken = await staffToken(request, adminEmail, adminPassword);
  const ws = await (await request.get(`${API}/inst/workspace`, { headers: adminToken })).json();
  expect(ws.institution.id).toBe(instId);
  expect(ws.permissions).toContain("users.manage");

  // ---- Activation is refused while the institution has no supply. The checklist names what is missing.
  await expect(page.getByText("Next: At least one active product")).toBeVisible();
  await expect(page.getByRole("button", { name: "Activate" })).toBeDisabled();

  // ---- The institution's own team builds its supply: a product, a mandate and routing. WEZA separates
  // duties, so a second person has to approve what the first authored.
  const businessEmail = `business@e2e-staff-${suffix}.co.ug`;
  const businessPassword = "E2e-Biz-Passw0rd!";
  await apiPost(request, "/inst/users", adminToken, {
    full_name: "Business Lead", email: businessEmail, password: businessPassword, roles: ["BUSINESS"],
  });
  const businessToken = await staffToken(request, businessEmail, businessPassword);

  const product = await apiPost(request, "/inst/products", businessToken, {
    name: "Working Capital", family: "SME_WORKING_CAPITAL",
    terms: { min_amount: 1_000_000, max_amount: 40_000_000, min_tenor_months: 3, max_tenor_months: 18 },
  });
  const productId = product.product_id;
  expect((await request.post(`${API}/inst/products/${productId}/submit`, { headers: businessToken })).ok()).toBeTruthy();
  expect((await request.post(`${API}/inst/products/${productId}/review`, {
    headers: adminToken, data: { approve: true, note: "Terms checked." },
  })).ok()).toBeTruthy();

  const appetite = await apiPost(request, "/inst/appetites", businessToken, {
    name: "SME Mandate", product_ids: [productId],
  });
  const appetiteId = appetite.appetite_id;
  expect((await request.post(`${API}/inst/appetites/${appetiteId}/simulate`, { headers: businessToken })).ok()).toBeTruthy();
  expect((await request.post(`${API}/inst/appetites/${appetiteId}/review`, {
    headers: adminToken, data: { approve: true, note: "Mandate agreed." },
  })).ok()).toBeTruthy();

  const routing = await request.put(`${API}/inst/routing`, {
    headers: adminToken, data: { rules: [{ name: "Default", conditions: {}, active: true }] },
  });
  expect(routing.ok(), await routing.text()).toBeTruthy();

  // ---- WEZA staff review readiness and activate.
  await page.reload();
  await expect(page.getByText("Ready to activate")).toBeVisible({ timeout: 15_000 });
  const before = await marketSupply(request, weza);
  const activate = page.getByRole("button", { name: "Activate" });
  await expect(activate).toBeEnabled();
  await activate.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Reason (audited)").fill("Licence checked with the regulator (E2E).");
  await dialog.getByRole("button", { name: "Activate" }).click();

  await expect(page.getByText("Trading on WEZA")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Active", { exact: true }).first()).toBeVisible();

  // An active institution is in the market: it and its mandate are live. (The product went live when the
  // institution's own team approved it, so it does not move at activation.)
  const after = await marketSupply(request, weza);
  expect(after.institutions).toBe(before.institutions + 1);
  expect(after.appetites).toBe(before.appetites + 1);

  const detail = await (await request.get(`${API}/staff/institutions/${instId}`, { headers: weza })).json();
  expect(detail.status).toBe("ACTIVE");
  expect(detail.appetites.map((a: any) => a.status)).toContain("ACTIVE");
  expect(detail.products.map((p: any) => p.status)).toContain("ACTIVE");

  // ---- And WEZA staff can pause it again.
  await page.getByRole("button", { name: "Pause" }).click();
  const pause = page.getByRole("dialog");
  await pause.getByLabel("Reason (audited)").fill("Licence renewal under review (E2E).");
  await pause.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByText("Paused", { exact: true }).first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Trading on WEZA")).toHaveCount(0);

  // A paused institution is out of the market: the matcher filters on the institution being active.
  const stopped = await marketSupply(request, weza);
  expect(stopped.institutions).toBe(before.institutions);
});
