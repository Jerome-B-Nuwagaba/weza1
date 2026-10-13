"use client";

import { ArrowUp, FileUp, MessageCircle, RotateCcw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { whatsappHref } from "@/lib/whatsapp";
import { api, ApiError, tokens } from "@/lib/api";
import { money } from "@/lib/format";
import { Badge, Banner, Button, cx, inputCls, ScoreRing, Select } from "@/components/ui";

type QR = { label: string; action: string; value?: string | null };
type Msg = { direction: "IN" | "OUT"; type: string; text?: string; hint?: string; card?: string; data?: any; quick_replies?: QR[]; label?: string; action?: string };
type View = { journey_id: string; node: string; status: string; messages: Msg[]; quick_replies: QR[]; need: any; verified: boolean; outputs?: Msg[] };

const STEPS = [
  ["Your need", ["GREET", "UNDERSTAND_INTENT", "ASK_INTENT", "CONFIRM_INTENT", "REVISE_INTENT", "CONFIRM_INTENT_WAIT"]],
  ["Verify", ["VERIFY_PHONE"]],
  ["Profile", ["BUILD_PROFILE", "ASK_PROFILE", "RESOLVE_CONFLICT", "READINESS_CHECK", "REQUEST_MISSING_ITEM"]],
  ["Options", ["PRESENT_OPTIONS", "RERANK", "OFFER_WAITING_ROOM", "WAITING_ROOM", "CONSENT"]],
  ["Submitted", ["CREATE_OPPORTUNITY", "CONFIRM", "TRACKING", "RESCUE_ASK"]],
] as const;

export function Conversation({ attribution, seed }: { attribution: Record<string, string>; seed?: string | null }) {
  const [view, setView] = useState<View | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cfg, setCfg] = useState<any>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const initialised = useRef(false);

  useEffect(() => {
    if (initialised.current) return; // React strict mode runs effects twice in dev
    initialised.current = true;
    api("/public/config").then(setCfg).catch(() => undefined);
    const last = tokens.lastJourney();
    const t = last ? tokens.journey(last) : null;
    if (seed) {
      startJourney(seed);
      return;
    }
    if (last && t) {
      api<View>(`/journeys/${last}`, { headers: { "X-Journey-Token": t } })
        .then((v) => {
          if (["COMPLETED", "EXPIRED", "FAILED"].includes(v.status)) return;
          setView(v);
          setToken(t);
        })
        .catch((e: ApiError) => {
          // Forget the conversation only if the server rejected it; keep it across transient outages.
          if (e.status === 403 || e.status === 404) tokens.setLastJourney(null);
          else setError("We couldn't load your conversation. Please refresh in a moment.");
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [view?.messages.length, busy]);

  const absorb = (v: View) => {
    for (const o of v.outputs || []) if (o.type === "card" && o.card === "session") tokens.setCustomer(o.data.token);
    setView(v);
  };

  async function startJourney(first?: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api<View & { token: string }>("/journeys", {
        body: { channel: "web", text: first || null, ...attribution, landing: typeof window !== "undefined" ? window.location.pathname : null, device_id: deviceId() },
        auth: tokens.customer() ? "customer" : "none",
      });
      tokens.setJourney(r.journey_id, r.token);
      tokens.setLastJourney(r.journey_id);
      setToken(r.token);
      absorb(r);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function send(payload: Record<string, unknown>) {
    if (!view || !token) return startJourney(String(payload.text || ""));
    setBusy(true);
    setError(null);
    try {
      const r = await api<View>(`/journeys/${view.journey_id}/messages`, { body: { ...payload, message_id: crypto.randomUUID() }, headers: { "X-Journey-Token": token } });
      absorb(r);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  function submitText(e?: React.FormEvent) {
    e?.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    send({ text: t });
  }

  function restart() {
    tokens.setLastJourney(null);
    setView(null);
    setToken(null);
  }

  // Latest card of each kind is the interactive one
  const lastIdx = useMemo(() => {
    const m: Record<string, number> = {};
    view?.messages.forEach((msg, i) => msg.type === "card" && msg.card && (m[msg.card] = i));
    return m;
  }, [view]);
  const devCode = view?.outputs?.find((o) => o.card === "otp_input")?.data?.dev_code;
  const step = view ? STEPS.findIndex(([, nodes]) => (nodes as readonly string[]).includes(view.node)) : 0;
  const waitingText = view && ["ASK_INTENT", "GREET", "CONFIRM_INTENT_WAIT", "REVISE_INTENT", "VERIFY_PHONE", "ASK_PROFILE", "TRACKING", "WAITING_ROOM", "SAVE_EXIT", "CONFIRM_INTENT"].includes(view.node);

  if (!view)
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-4 py-10">
        <h1 className="font-serif text-3xl leading-tight text-ink sm:text-4xl">Welcome to WEZA.</h1>
        <p className="mt-2 text-[16px] text-muted">Tell me what you would like financing for — in your own words.</p>
        <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) startJourney(text.trim()); }} className="mt-6">
          <textarea
            autoFocus
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (text.trim()) startJourney(text.trim()); } }}
            rows={3}
            placeholder="e.g. I need UGX 30 million to expand my pharmacy"
            className={cx(inputCls, "text-[16px]")}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button type="submit" size="lg" pending={busy} disabled={!text.trim()}>Start</Button>
            {["I need UGX 30 million to expand my pharmacy", "I need money for school fees", "I need 3 million for seeds and fertiliser"].map((s) => (
              <button type="button" key={s} onClick={() => startJourney(s)} className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] text-muted hover:border-blue-400 hover:text-ink">{s}</button>
            ))}
          </div>
          {error && <p className="mt-3 text-[13px] text-danger">{error}</p>}
        </form>
        <p className="mt-8 flex items-center gap-2 text-[13px] text-muted"><ShieldCheck className="h-4 w-4 text-blue-600" /> WEZA is a marketplace, not a lender. Nothing is shared with any institution without your consent.</p>
      </div>
    );

  const firstNeed = ((view.messages as any[]).find((m) => m.direction === "IN" && m.type === "text")?.text as string | undefined) || seed || "";
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">
      <div className="sticky top-0 z-10 border-b border-line bg-canvas/95 px-4 py-2 backdrop-blur">
        <ol className="flex items-center gap-1 text-[12px]">
          {STEPS.map(([name], i) => (
            <li key={name} className="flex flex-1 items-center gap-1">
              <span className={cx("h-1.5 flex-1 rounded-full", i <= step ? "bg-blue-600" : "bg-line")} />
              <span className={cx("hidden whitespace-nowrap sm:inline", i === step ? "font-semibold text-ink" : "text-muted")}>{name}</span>
            </li>
          ))}
          {cfg?.whatsapp_number && (
            <li><a href={whatsappHref(cfg.whatsapp_number, firstNeed, attribution)} className="ml-2 inline-flex items-center gap-1 text-muted hover:text-ink" title="Continue this request on WhatsApp"><MessageCircle className="h-3.5 w-3.5" /><span className="hidden sm:inline">WhatsApp</span></a></li>
          )}
          <li><button onClick={restart} className="ml-2 inline-flex items-center gap-1 text-muted hover:text-ink" title="Start a new request"><RotateCcw className="h-3.5 w-3.5" /><span className="hidden sm:inline">New</span></button></li>
        </ol>
      </div>
      {cfg?.ai_mode && cfg.ai_mode !== "AVAILABLE" && (
        <div className="px-4 pt-3"><Banner tone="info">Simple mode — WEZA is using structured questions right now.</Banner></div>
      )}
      <div className="flex-1 space-y-3 px-4 py-4" aria-live="polite">
        {view.messages.map((m, i) => (
          <Message key={i} m={m} active={m.type === "card" && lastIdx[m.card!] === i && i >= view.messages.length - 3} send={send} busy={busy} cfg={cfg} devCode={devCode} />
        ))}
        {busy && <div className="flex gap-1 px-2 py-3"><span className="skeleton h-2 w-2 rounded-full" /><span className="skeleton h-2 w-2 rounded-full" /><span className="skeleton h-2 w-2 rounded-full" /></div>}
        {error && <Banner tone="danger">{error}</Banner>}
        <div ref={bottom} />
      </div>
      <div className="sticky bottom-0 border-t border-line bg-surface px-4 py-3">
        {view.quick_replies?.length > 0 && !busy && (
          <div className="scroll-thin mb-2 flex gap-2 overflow-x-auto pb-1">
            {view.quick_replies.map((q, i) => (
              <button key={i} onClick={() => send({ action: q.action, value: q.value ?? undefined, label: q.label, text: q.action === "answer" ? q.value : undefined })} className="whitespace-nowrap rounded-full border border-blue-400 bg-blue-50 px-3 py-1.5 text-[13px] font-medium text-blue-800 hover:bg-blue-100">
                {q.label}
              </button>
            ))}
          </div>
        )}
        {view.status === "COMPLETED" || view.status === "EXPIRED" ? (
          <div className="flex items-center justify-between gap-3 text-[14px] text-muted">This conversation has ended. <Button size="sm" onClick={restart}>Start a new request</Button></div>
        ) : (
          <form onSubmit={submitText} className="flex items-end gap-2">
            <textarea value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submitText(e); }} rows={1} placeholder={waitingText ? "Type your reply…" : "Choose an option above or type a reply…"} className={cx(inputCls, "max-h-32 min-h-10 resize-none text-[15px]")} aria-label="Your message" />
            <Button type="submit" aria-label="Send" disabled={!text.trim() || busy} className="h-10 w-10 shrink-0 !px-0"><ArrowUp className="h-4 w-4" /></Button>
          </form>
        )}
      </div>
    </div>
  );
}

function deviceId() {
  try {
    let d = localStorage.getItem("weza.device");
    if (!d) { d = crypto.randomUUID(); localStorage.setItem("weza.device", d); }
    return d;
  } catch { return null; }
}

function Bubble({ out, children }: { out: boolean; children: React.ReactNode }) {
  return (
    <div className={cx("flex", out ? "justify-start" : "justify-end")}>
      <div className={cx("max-w-[88%] whitespace-pre-line rounded-2xl px-4 py-2.5 text-[15px]", out ? "rounded-tl-sm border border-line bg-surface text-ink" : "rounded-tr-sm bg-blue-600 text-white dark:text-[#07111a]")}>{children}</div>
    </div>
  );
}

function Message({ m, active, send, busy, cfg, devCode }: { m: Msg; active: boolean; send: (p: any) => void; busy: boolean; cfg: any; devCode?: string }) {
  if (m.direction === "IN") return <Bubble out={false}>{m.text || m.label || m.action}</Bubble>;
  if (m.type === "text") return <Bubble out>{m.text}{m.hint && <span className="mt-1 block text-[13px] text-muted">{m.hint}</span>}</Bubble>;
  const d = m.data || {};
  switch (m.card) {
    case "understanding":
      return (
        <div className="ml-0 max-w-md rounded-xl border border-blue-100 bg-blue-50 p-4">
          <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-blue-800">What I understood</div>
          {[["Amount", d.amount, "amount"], ["Purpose", d.purpose, "purpose"], ["You are", d.customer_type, "customer_type"], ["Sector", d.sector], ["District", d.district]].filter((r) => r[1]).map(([k, v, key]) => (
            <div key={k as string} className="flex justify-between gap-4 border-b border-blue-100 py-1.5 text-[14px] last:border-0">
              <span className="text-muted">{k}</span>
              <span className="text-right font-medium text-ink">{v} {d.needs_confirmation?.includes(key) && <Badge tone="warning" className="ml-1">please check</Badge>}</span>
            </div>
          ))}
        </div>
      );
    case "phone_input":
      return active ? <PhoneInput send={send} busy={busy} prefix={d.prefix} /> : null;
    case "otp_input":
      return active ? <OtpInput send={send} busy={busy} masked={d.masked} devCode={devCode} demo={cfg?.demo_mode} /> : null;
    case "question":
      return active ? <QuestionInput q={d} send={send} busy={busy} cfg={cfg} /> : null;
    case "options":
      return <Options d={d} active={active} send={send} busy={busy} />;
    case "consent":
      return <ConsentCard d={d} active={active} send={send} busy={busy} />;
    case "submitted":
      return (
        <div className="max-w-md rounded-xl border border-success/30 bg-success-bg p-4">
          <div className="text-[12px] font-semibold uppercase tracking-wide text-success">Request shared</div>
          <div className="mt-1 text-xl font-semibold text-ink">{d.reference}</div>
          <p className="mt-1 text-[14px] text-ink">With {d.institution}. Expected first contact within {d.expected_contact_hours} hours.</p>
          <Button href="/c/status" size="sm" variant="secondary" className="mt-3">Track my requests</Button>
        </div>
      );
    case "documents_needed":
      return <DocUpload d={d} send={send} />;
    default:
      return null;
  }
}

function PhoneInput({ send, busy, prefix }: { send: (p: any) => void; busy: boolean; prefix: string }) {
  const [v, setV] = useState("");
  return (
    <form onSubmit={(e) => { e.preventDefault(); send({ text: v }); }} className="flex max-w-sm gap-2">
      <span className="flex h-10 items-center rounded-lg border border-line bg-canvas px-3 text-[14px] text-muted">{prefix}</span>
      <input inputMode="tel" autoComplete="tel" value={v} onChange={(e) => setV(e.target.value)} placeholder="772 123 456" className={cx(inputCls, "h-10")} aria-label="Mobile number" />
      <Button type="submit" pending={busy} disabled={v.replace(/\D/g, "").length < 9}>Send code</Button>
    </form>
  );
}

function OtpInput({ send, busy, masked, devCode, demo }: { send: (p: any) => void; busy: boolean; masked?: string; devCode?: string; demo?: boolean }) {
  const [v, setV] = useState("");
  return (
    <div className="max-w-sm space-y-2">
      {devCode && demo && <Banner tone="gold" title="Test mode">SMS isn't connected yet, so your code is shown here: <b className="num tracking-widest">{devCode}</b></Banner>}
      <form onSubmit={(e) => { e.preventDefault(); send({ text: v }); setV(""); }} className="flex gap-2">
        <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={v} onChange={(e) => setV(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" className={cx(inputCls, "h-10 text-center text-lg tracking-[0.4em]")} aria-label={`Code sent to ${masked}`} />
        <Button type="submit" pending={busy} disabled={v.length !== 6}>Verify</Button>
      </form>
    </div>
  );
}

function QuestionInput({ q, send, busy, cfg }: { q: any; send: (p: any) => void; busy: boolean; cfg: any }) {
  const [v, setV] = useState("");
  if (q.type === "district" && cfg) {
    const opts = Object.entries(cfg.regions as Record<string, string[]>).flatMap(([r, ds]) => ds.map((d) => [d, `${d} (${r})`] as [string, string]));
    return (
      <div className="flex max-w-sm gap-2">
        <Select value={v} onChange={(e) => setV(e.target.value)} options={[["", "Choose district…"], ...opts.sort()]} aria-label="District" />
        <Button onClick={() => send({ text: v })} disabled={!v} pending={busy}>Next</Button>
      </div>
    );
  }
  if (q.type === "money")
    return (
      <form onSubmit={(e) => { e.preventDefault(); send({ text: v }); }} className="flex max-w-sm gap-2">
        <span className="flex h-10 items-center rounded-lg border border-line bg-canvas px-3 text-[14px] text-muted">UGX</span>
        <input inputMode="numeric" value={v} onChange={(e) => setV(e.target.value)} placeholder="e.g. 12,000,000 or 12m" className={cx(inputCls, "h-10")} aria-label="Amount" />
        <Button type="submit" disabled={!v} pending={busy}>Next</Button>
      </form>
    );
  return (
    <div className="text-[12px] text-muted">
      {q.progress && <>Question {q.progress.asked} · about {q.progress.remaining} left</>}
    </div>
  );
}

function Options({ d, active, send, busy }: { d: any; active: boolean; send: (p: any) => void; busy: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<string[]>(d.preferences || []);
  return (
    <div className="space-y-3">
      {d.options.map((o: any) => (
        <div key={o.match_id} className={cx("rounded-xl border bg-surface p-4", o.score >= 90 ? "border-gold-500/50" : "border-line")}>
          <div className="flex items-start gap-3">
            <ScoreRing score={o.score} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[16px] font-semibold text-ink">{o.institution}</span>
                <span className="text-[13px] text-muted">{o.institution_type}</span>
                {o.readiness !== "READY" && <Badge tone="warning">Needs more info</Badge>}
                {o.sponsored && <Badge tone="muted">Sponsored</Badge>}
              </div>
              <div className="text-[14px] text-ink">{o.product}</div>
              <div className="num mt-1 text-[13px] text-muted">{o.amount_range} · {o.tenor} · {o.pricing}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">{o.why.slice(0, 4).map((w: string) => <Badge key={w} tone="success">✓ {w}</Badge>)}</div>
              {open === o.match_id && (
                <div className="mt-3 space-y-1 border-t border-line pt-3 text-[13px] text-muted">
                  <div>Collateral: {o.collateral_required ? "required" : "not required"} · {o.digital_journey ? "Digital process" : "Branch visit may be needed"}</div>
                  {o.typical_response_hours && <div>Typical response: within {o.typical_response_hours} hours</div>}
                  {o.requirements.length > 0 && <div>Requirements: {o.requirements.join(", ")}</div>}
                  {o.outstanding.length > 0 && <div className="text-warning">To unlock: {o.outstanding.join("; ")}</div>}
                </div>
              )}
            </div>
          </div>
          {active && (
            <div className="mt-3 flex flex-wrap gap-2">
              {o.readiness === "READY" && <Button size="sm" pending={busy} onClick={() => send({ action: "select", value: o.match_id, label: `Choose ${o.institution}` })}>Choose this option</Button>}
              <Button size="sm" variant="ghost" onClick={() => setOpen(open === o.match_id ? null : o.match_id)}>{open === o.match_id ? "Less" : "Details"}</Button>
            </div>
          )}
        </div>
      ))}
      {active && (
        <div className="rounded-xl border border-line bg-surface p-4">
          <div className="mb-2 text-[13px] font-medium text-ink">What matters most to you? (re-orders options; never changes who is eligible)</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(d.preference_choices || {}).map(([k, l]) => (
              <button key={k} onClick={() => setPrefs(prefs.includes(k) ? prefs.filter((p) => p !== k) : [...prefs, k])} className={cx("rounded-full border px-3 py-1 text-[13px]", prefs.includes(k) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted")}>{l as string}</button>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => send({ action: "prefs", values: prefs, label: "Update preferences" })}>Apply preferences</Button>
            <Button size="sm" variant="ghost" onClick={() => send({ action: "why_not", label: "Why not other options?" })}>Why not other options?</Button>
          </div>
        </div>
      )}
      <p className="text-[12px] text-muted">A match shows how well your request fits each institution's current criteria. It is not a loan approval — the institution makes its own decision.</p>
    </div>
  );
}

function ConsentCard({ d, active, send, busy }: { d: any; active: boolean; send: (p: any) => void; busy: boolean }) {
  const [cats, setCats] = useState<string[]>(d.categories.map((c: any) => c.code));
  const [channel, setChannel] = useState("phone");
  return (
    <div className="rounded-xl border border-blue-400 bg-surface p-5">
      <div className="text-[12px] font-semibold uppercase tracking-wide text-blue-800">Consent · version {d.version}</div>
      <h3 className="mt-1 text-[17px] font-semibold text-ink">{d.title}</h3>
      <p className="mt-2 whitespace-pre-line text-[14px] text-ink">{d.text}</p>
      <div className="mt-4 text-[13px] font-medium text-ink">Information that will be shared</div>
      <ul className="mt-1 space-y-1.5">
        {d.categories.map((c: any) => (
          <li key={c.code} className="flex items-center gap-2 text-[14px]">
            <input type="checkbox" id={c.code} checked={cats.includes(c.code)} disabled={!active || c.code === "CONTACT"} onChange={() => setCats(cats.includes(c.code) ? cats.filter((x) => x !== c.code) : [...cats, c.code])} className="h-4 w-4 accent-[var(--blue-600)]" />
            <label htmlFor={c.code}>{c.label}{c.code === "CONTACT" && <span className="text-muted"> (required)</span>}</label>
          </li>
        ))}
      </ul>
      {active && (
        <>
          <div className="mt-4 flex items-center gap-2 text-[14px]">
            <span className="text-muted">Preferred contact:</span>
            <Select value={channel} onChange={(e) => setChannel(e.target.value)} options={[["phone", "Phone call"], ["sms", "SMS"], ["whatsapp", "WhatsApp"]]} className="!w-44" />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button pending={busy} onClick={() => send({ action: "agree", value: d.template_id, categories: cats, contact_channel: channel, label: `I agree — share with ${d.institution}` })}>I agree — share with {d.institution}</Button>
            <Button variant="secondary" onClick={() => send({ action: "decline", label: "Not now" })}>Not now</Button>
          </div>
        </>
      )}
    </div>
  );
}

function DocUpload({ d, send }: { d: any; send: (p: any) => void }) {
  const [msg, setMsg] = useState<string | null>(null);
  async function upload(docType: string, f: File) {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("doc_type", docType);
    try {
      const r = await api("/me/documents", { form: fd, auth: "customer" });
      setMsg(r.state === "STORED" ? `${r.label} uploaded securely.` : r.reason || "Upload rejected.");
      if (r.state === "STORED") send({ action: "uploaded", label: "I've uploaded it" });
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }
  return (
    <div className="max-w-md space-y-2 rounded-xl border border-line bg-surface p-4">
      {d.documents.map((doc: any) => (
        <label key={doc.doc_type} className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-dashed border-line px-3 py-2.5 hover:border-blue-400">
          <span className="text-[14px] text-ink">{doc.label}</span>
          <span className="inline-flex items-center gap-1 text-[13px] text-blue-800"><FileUp className="h-4 w-4" /> Upload</span>
          <input type="file" accept="application/pdf,image/jpeg,image/png" className="hidden" onChange={(e) => e.target.files?.[0] && upload(doc.doc_type, e.target.files[0])} />
        </label>
      ))}
      {d.other?.length > 0 && <p className="text-[13px] text-muted">Also needed: {d.other.join("; ")}</p>}
      <p className="text-[12px] text-muted">PDF, JPG or PNG up to 10 MB. Files are security-checked and encrypted. <Link href="/c/documents" className="underline">Manage documents</Link></p>
      {msg && <p className="text-[13px] text-ink">{msg}</p>}
    </div>
  );
}

export { money };
