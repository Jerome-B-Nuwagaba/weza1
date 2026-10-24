import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEMO_PASSWORD = "WezaDemo!2026";
const API = "/api/v1"; // same-origin: Next rewrites proxy to the core API

const SME_ANSWERS: Record<string, string> = {
  "identity.full_name": "Grace Nakato", "business.name": "Nakato Pharmacy", "business.sector": "health_pharmacy",
  "business.district": "Kampala", "business.age_months": "4 years", "business.monthly_turnover": "12 million",
  "business.registered": "yes", "finance.monthly_repayments": "0", "need.tenor_months": "24 months",
};

let testClientIp = 0;

function nextTestClientIp() {
  const id = testClientIp++;
  // CI runs many simulated clients from one runner; keep the production IP throttle meaningful per client.
  return `198.51.${100 + Math.floor(id / 254)}.${(id % 254) + 1}`;
}

export function idem() {
  return { "Idempotency-Key": crypto.randomUUID() };
}

/** Drives the customer conversation through the journey API exactly as the web chat does, then shares the request
 * with Lakeside Bank. Returns browser-login details and API credentials for later assertions. */
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
  // With CRB_JIT_ENABLED (or the real bureau) WEZA asks for the credit bureau check next: say yes.
  if (data.node === "CRB_CHECK") await send({ action: "crb_consent", value: "yes" });
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
  return { reference, oppId, customer, phone };
}

export async function staffToken(request: APIRequestContext, email: string, password = DEMO_PASSWORD) {
  const r = await request.post(`${API}/auth/login`, {
    data: { email, password }, headers: { "X-Forwarded-For": nextTestClientIp() },
  });
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
  await page.setExtraHTTPHeaders({ "X-Forwarded-For": nextTestClientIp() });
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(institution|admin)/, { timeout: 15_000 });
}

export async function signInCustomer(page: Page, phone: string) {
  await page.goto("/c/login");
  const origin = new URL(page.url()).origin;
  const headers = {
    Origin: origin,
    "X-WEZA-CSRF": "1",
    "X-Forwarded-For": nextTestClientIp(),
  };
  const request = page.context().request;
  const challengeResponse = await request.post(`${origin}${API}/me/auth/otp/request`, {
    data: { phone }, headers,
  });
  expect(challengeResponse.ok(), await challengeResponse.text()).toBeTruthy();
  const challenge = await challengeResponse.json();
  expect(challenge.dev_code, "customer OTP should be available in the E2E demo environment").toBeTruthy();

  const verifyResponse = await request.post(`${origin}${API}/me/auth/otp/verify`, {
    data: { phone, challenge_id: challenge.challenge_id, code: challenge.dev_code }, headers,
  });
  expect(verifyResponse.ok(), await verifyResponse.text()).toBeTruthy();
}
