import { expect, test } from "@playwright/test";
import { assignTo, customerSharesWithLakeside, signIn } from "./helpers";

/**
 * E2E-01 (blueprint 12), institution side: a customer shares a pharmacy request with Lakeside Bank; the assigned
 * officer works it in the browser — contact, ask for information, read the answer, report approval with indicative
 * terms, report disbursement — and the customer sees institution-reported terms on My requests.
 */
test("officer works an opportunity from first contact to disbursement", async ({ page, request }) => {
  const officer = "officer@lakeside.demo";
  const { reference, oppId, session, customer } = await customerSharesWithLakeside(request);
  await assignTo(request, oppId, officer);

  await signIn(page, officer);
  await page.goto(`/institution/opportunities/${oppId}`);
  await expect(page.getByRole("heading", { name: reference })).toBeVisible();
  await expect(page.getByText("Shared under the customer's consent")).toBeVisible();

  // First contact
  await page.getByRole("button", { name: "Mark contacted" }).click();
  await expect(page.getByText("Marked contacted")).toBeVisible();

  // Ask the customer a question through WEZA
  await page.getByRole("button", { name: "Ask the customer…" }).click();
  const ask = page.getByRole("dialog");
  await ask.getByLabel("What do you need?").selectOption("QUESTION");
  await ask.getByLabel("Your question").fill("How many staff does the pharmacy employ?");
  await ask.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Waiting for customer")).toBeVisible();

  // The customer answers (API — the customer UI is covered below)
  await expect.poll(async () => (await (await request.get("/api/v1/me/info-requests", { headers: customer })).json()).open).toBe(1);
  const reqs = (await (await request.get("/api/v1/me/info-requests", { headers: customer })).json()).requests;
  const answered = await request.post(`/api/v1/me/info-requests/${reqs[0].id}/respond`, { headers: customer, data: { response_text: "Four full-time staff" } });
  expect(answered.ok(), await answered.text()).toBeTruthy();

  await page.reload();
  await expect(page.getByText("Four full-time staff")).toBeVisible();
  await expect(page.getByText("Answered", { exact: true })).toBeVisible();

  // Report approval with indicative terms
  await page.getByRole("button", { name: "Reported approved…" }).click();
  const approve = page.getByRole("dialog");
  await approve.getByLabel("Approved amount (UGX)").fill("18000000");
  await approve.getByText("Indicative terms (optional)").click();
  await approve.getByLabel("Tenor (months)").fill("24");
  await approve.getByLabel("Interest rate (%)").fill("1.8");
  await approve.getByLabel("Monthly repayment (UGX)").fill("925000");
  await approve.getByLabel("Conditions").fill("Subject to site visit");
  await approve.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Outcome recorded")).toBeVisible();
  await expect(page.getByText(/Indicative terms: 24 months · 1\.8% per month/)).toBeVisible();

  // Report disbursement
  await page.getByRole("button", { name: "Reported disbursed…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Outcome recorded")).toBeVisible();
  await expect(page.getByRole("button", { name: "Reported disbursed…" })).toHaveCount(0);

  // The customer sees the institution-reported terms on My requests
  await page.addInitScript((t) => window.localStorage.setItem("weza.customer.session", t), session);
  await page.goto("/c/status");
  await expect(page.getByText(reference)).toBeVisible();
  await expect(page.getByText(/Indicative terms: 24 months/)).toBeVisible();
  await expect(page.getByText(/reported by the institution/).first()).toBeVisible();
});

test("customer answers an information request on My requests", async ({ page, request }) => {
  const officer = "officer@lakeside.demo";
  const { oppId, session } = await customerSharesWithLakeside(request, "I need UGX 15 million to restock my pharmacy");
  await assignTo(request, oppId, officer);

  await signIn(page, officer);
  await page.goto(`/institution/opportunities/${oppId}`);
  await page.getByRole("button", { name: "Ask the customer…" }).click();
  const ask = page.getByRole("dialog");
  await ask.getByLabel("What do you need?").selectOption("QUESTION");
  await ask.getByLabel("Your question").fill("Do you own or rent the premises?");
  await ask.getByRole("button", { name: "Send request" }).click();
  await expect(page.getByText("Waiting for customer")).toBeVisible();

  // Switch to the customer in a fresh context so staff and customer sessions don't mix
  const customerPage = await page.context().browser()!.newPage();
  await customerPage.addInitScript((t) => window.localStorage.setItem("weza.customer.session", t), session);
  await customerPage.goto("/c/status");
  await expect(customerPage.getByText("Do you own or rent the premises?")).toBeVisible();
  await customerPage.getByPlaceholder("Your answer").fill("We rent on a 3-year lease");
  await customerPage.getByRole("button", { name: "Send", exact: true }).click();
  await expect(customerPage.getByText("Sent to Lakeside Bank.")).toBeVisible();
  await customerPage.close();

  await page.reload();
  await expect(page.getByText("We rent on a 3-year lease")).toBeVisible();
});

test("access rules hold in the browser", async ({ page, request }) => {
  const { oppId } = await customerSharesWithLakeside(request, "I need UGX 12 million for pharmacy stock");
  await assignTo(request, oppId, "officer@lakeside.demo");

  // Executives see opportunity intelligence but never the customer, and can't ask them anything
  await signIn(page, "exec@lakeside.demo");
  await page.goto(`/institution/opportunities/${oppId}`);
  await expect(page.getByText("Your role sees opportunity intelligence, not customer identity.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Ask the customer…" })).toHaveCount(0);

  // Another institution can't tell the opportunity exists
  await page.context().clearCookies();
  await page.evaluate(() => window.sessionStorage.clear());
  await signIn(page, "manager@pearl.demo");
  await page.goto(`/institution/opportunities/${oppId}`);
  await expect(page.getByText(/not found/i).first()).toBeVisible();
});
