import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEMO_PASSWORD = "WezaDemo!2026";
const API = "/api/v1"; // same-origin: Next rewrites proxy to the core API

const SME_ANSWERS: Record<string, string> = {
  "identity.full_name": "Grace Nakato", "business.name": "Nakato Pharmacy", "business.sector": "health_pharmacy",
  "business.district": "Kampala", "business.age_months": "4 years", "business.monthly_turnover": "12 million",
  "business.registered": "yes", "finance.monthly_repayments": "0", "need.tenor_months": "24 months",
};

export function idem() {
  return { "Idempotency-Key": crypto.randomUUID() };
}

/** Drives the customer conversation through the journey API exactly as the web chat does, then shares the request
 * with Lakeside Bank. Returns the opportunity and a customer session for later answers. */
export async function customerSharesWithLakeside(request: APIRequestContext, text = "I need UGX 20 million to buy stock for my pharmacy") {
  return customerSharesWith(request, "Lakeside Bank", text);
}

export async function customerSharesWith(request: APIRequestContext, institution: string, text: string) {
  const phone = "0772" + String(Math.floor(Math.random() * 1e6)).padStart(6, "0");
  let r = await request.post(`${API}/journeys`, { data: { channel: "web", text } });
  expect(r.ok(), await r.text()).toBeTruthy();
  let data = await r.json();
  const headers = { "X-Journey-Token": data.token };
  let session = "";
  const cards = (kind: string) => (data.outputs || []).filter((o: any) => o.type === "card" && o.card === kind).map((o: any) => o.data);
  const send = async (body: Record<string, unknown>) => {
    r = await request.post(`${API}/journeys/${data.journey_id}/messages`, { data: body, headers });
    expect(r.ok(), await r.text()).toBeTruthy();
    data = await r.json();
    for (const s of cards("session")) session = s.token;
  };

  await send({ action: "confirm" });
  expect(data.node).toBe("VERIFY_PHONE");
  await send({ text: phone });
  await send({ text: cards("otp_input")[0].dev_code });
  const answers = { ...SME_ANSWERS, "identity.nin": `CM${phone}AB` };
  for (let i = 0; i < 30 && data.node === "ASK_PROFILE"; i++) {
    const q = cards("question")[0];
    expect(Object.keys(answers), `unexpected question ${q.key}`).toContain(q.key);
    await send({ text: answers[q.key] });
  }
  expect(cards("options").length, `no options at node ${data.node}: ${JSON.stringify(data.outputs).slice(0, 1500)}`).toBeGreaterThan(0);
  const offered = cards("options")[0].options;
  const option = offered.find((o: any) => o.institution === institution);
  expect(option, `${institution} should be offered (got ${offered.map((o: any) => o.institution).join(", ")})`).toBeTruthy();
  await send({ action: "select", value: option.match_id });
  await send({ action: "agree", value: cards("consent")[0].template_id });
  const reference: string = cards("submitted")[0].reference;
  const customer = { Authorization: `Bearer ${session}` };

  // Routing runs on the outbox worker; wait until the opportunity is visible to the customer as shared.
  let oppId = "";
  await expect.poll(async () => {
    const needs = await (await request.get(`${API}/me/needs`, { headers: customer })).json();
    const o = needs.needs.flatMap((n: any) => n.opportunities).find((x: any) => x.reference === reference);
    oppId = o?.id || "";
    return o?.state;
  }, { timeout: 30_000 }).not.toMatch(/^(QUALIFIED)?$/);
  return { reference, oppId, session, customer };
}

export async function staffToken(request: APIRequestContext, email: string, password = DEMO_PASSWORD) {
  const r = await request.post(`${API}/auth/login`, { data: { email, password } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return { Authorization: `Bearer ${(await r.json()).access_token}` };
}

/** Make sure a known officer owns the opportunity, whatever the routing rules picked. */
export async function assignTo(request: APIRequestContext, oppId: string, officerEmail: string) {
  const mgr = await staffToken(request, "manager@lakeside.demo");
  const opp = await (await request.get(`${API}/inst/opportunities/${oppId}`, { headers: mgr })).json();
  const officer = opp.members.find((m: any) => m.email === officerEmail);
  expect(officer, `${officerEmail} should be assignable`).toBeTruthy();
  if (opp.owner_id !== officer.id) {
    const r = await request.post(`${API}/inst/opportunities/${oppId}/assign`, { data: { user_id: officer.id, reason: "E2E" }, headers: mgr });
    expect(r.ok(), await r.text()).toBeTruthy();
  }
}

export async function signIn(page: Page, email: string, password = DEMO_PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/(institution|admin)/);
}
