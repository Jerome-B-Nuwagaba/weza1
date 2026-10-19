"use client";

/** API client. The web app calls same-origin /api/v1 (Next rewrites proxy to the core API), so the refresh-token
 * cookie stays first-party. Errors follow the WEZA error contract (TSD §59). */

export class ApiError extends Error {
  code: string;
  status: number;
  correlationId?: string;
  details: { field?: string; issue?: string }[];
  constructor(status: number, body: any) {
    const e = body?.error ?? {};
    super(e.message || `Request failed (${status})`);
    this.status = status;
    this.code = e.code || "HTTP_ERROR";
    this.correlationId = e.correlation_id;
    this.details = e.details || [];
  }
}

const STAFF_TOKEN = "weza.staff.access";
const CUSTOMER_TOKEN = "weza.customer.session";

function store(kind: "session" | "local") {
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export const tokens = {
  staff: () => store("session")?.getItem(STAFF_TOKEN) ?? null,
  setStaff: (t: string | null) => (t ? store("session")?.setItem(STAFF_TOKEN, t) : store("session")?.removeItem(STAFF_TOKEN)),
  customer: () => store("local")?.getItem(CUSTOMER_TOKEN) ?? null,
  setCustomer: (t: string | null) =>
    t ? store("local")?.setItem(CUSTOMER_TOKEN, t) : store("local")?.removeItem(CUSTOMER_TOKEN),
  journey: (id: string) => store("local")?.getItem(`weza.journey.${id}`) ?? null,
  setJourney: (id: string, t: string) => store("local")?.setItem(`weza.journey.${id}`, t),
  lastJourney: () => store("local")?.getItem("weza.journey.last") ?? null,
  setLastJourney: (id: string | null) =>
    id ? store("local")?.setItem("weza.journey.last", id) : store("local")?.removeItem("weza.journey.last"),
};

type Auth = "staff" | "customer" | "none";

interface Opts {
  method?: string;
  body?: unknown;
  auth?: Auth;
  headers?: Record<string, string>;
  form?: FormData;
  idempotencyKey?: string | true;
  raw?: boolean;
}

let refreshing: Promise<boolean> | null = null;

async function refreshStaff(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: "{}" })
      .then(async (r) => {
        if (!r.ok) return false;
        const j = await r.json();
        tokens.setStaff(j.access_token);
        return true;
      })
      .catch(() => false)
      .finally(() => setTimeout(() => (refreshing = null), 0));
  }
  return refreshing;
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const auth = opts.auth ?? (path.startsWith("/inst") || path.startsWith("/admin") || path.startsWith("/auth/me") ? "staff" : path.startsWith("/me") ? "customer" : "none");
  const run = async (): Promise<Response> => {
    const headers: Record<string, string> = { ...(opts.headers || {}) };
    if (!opts.form) headers["Content-Type"] = "application/json";
    // Customer credentials live only in an HTTP-only cookie. The custom header and server-side
    // origin check protect cookie-authenticated mutations, including multipart document uploads.
    headers["X-WEZA-CSRF"] = "1";
    const token = auth === "staff" ? tokens.staff() : null;
    if (token) headers.Authorization = `Bearer ${token}`;
    if (opts.idempotencyKey) headers["Idempotency-Key"] = opts.idempotencyKey === true ? crypto.randomUUID() : opts.idempotencyKey;
    return fetch(`/api/v1${path}`, {
      method: opts.method || (opts.body || opts.form ? "POST" : "GET"),
      headers,
      credentials: "include",
      body: opts.form ? opts.form : opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  };
  let res = await run();
  if (res.status === 401 && auth === "staff" && (await refreshStaff())) res = await run();
  if (opts.raw) return res as unknown as T;
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    if (res.status === 401 && auth === "staff" && typeof window !== "undefined") {
      tokens.setStaff(null);
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      if (!window.location.pathname.startsWith("/login")) window.location.href = `/login?next=${next}`;
    }
    throw new ApiError(res.status, data);
  }
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return { error: { message: t.slice(0, 200) } };
  }
}

export const staffLogout = async () => {
  await fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" }).catch(() => undefined);
  tokens.setStaff(null);
  window.location.href = "/login";
};
