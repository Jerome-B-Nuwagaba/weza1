"use client";

import { useEffect, useState } from "react";
import { api, ApiError, tokens } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { PublicShell } from "@/components/PublicShell";
import { Badge, Banner, Button, Card, EmptyState, ErrorState, Input, Loading, PageHeader, Select } from "@/components/ui";

const SOURCE: Record<string, string> = { CUSTOMER: "You told us", AI_EXTRACTED: "Understood by WEZA", DOCUMENT: "From a document", OPS: "WEZA support" };
const PREFS: Record<string, string> = { LOWER_MONTHLY_PAYMENT: "Lower monthly payment", LOW_COLLATERAL: "Little or no collateral", FAST_RESPONSE: "Fast response", DIGITAL: "Digital process", NEAR_ME: "Near me", SHORTER_TENOR: "Shorter repayment" };

export default function ProfilePage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => setAuthed(!!tokens.customer()), []);
  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        {authed === false ? <EmptyState title="Verify your phone first" action={<Button href="/start">Start</Button>} /> : authed && <Inner />}
      </div>
    </PublicShell>
  );
}

function Inner() {
  const p = useApi<any>("/me/profile");
  const [edit, setEdit] = useState<string | null>(null);
  const [val, setVal] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<any>(null);
  useEffect(() => { if (p.data) setPrefs(p.data.preferences); }, [p.data]);

  async function save(key: string) {
    try {
      const r = await api("/me/profile", { method: "PATCH", body: { key, value: val } });
      p.setData(r);
      setEdit(null);
      setMsg("Saved. If this changes your options, WEZA refreshes them automatically.");
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }
  async function savePrefs() {
    await api("/me/preferences", { method: "PUT", body: prefs });
    setMsg("Preferences saved.");
  }

  if (p.loading) return <Loading />;
  if (p.error) return <ErrorState error={p.error} onRetry={p.reload} />;
  const c = p.data.customer;
  return (
    <>
      <PageHeader title="My profile" subtitle="This is what WEZA holds about you. Correct anything before sharing — every value shows where it came from." actions={<Button href="/c/documents" variant="secondary">Documents</Button>} />
      {msg && <Banner tone="info" className="mb-4">{msg}</Banner>}
      <Card title={c.name || "Your details"} subtitle={`Phone ${c.phone} · ${c.verification_level === "IDENTITY" ? "Phone and ID provided" : "Phone verified"} · Marketplace verification only — institutions do their own checks.`}>
        <ul className="divide-y divide-line">
          {p.data.facts.map((f: any) => (
            <li key={f.key} className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-[13px] text-muted">{f.label}</div>
                {edit === f.key ? (
                  <div className="mt-1 flex gap-2"><Input value={val} onChange={(e) => setVal(e.target.value)} className="!w-56" autoFocus /><Button size="sm" onClick={() => save(f.key)}>Save</Button><Button size="sm" variant="ghost" onClick={() => setEdit(null)}>Cancel</Button></div>
                ) : (
                  <div className="font-medium text-ink">{display(f)}</div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone="muted">{SOURCE[f.source] || f.source} · {f.channel} · {date(f.captured_at)}</Badge>
                {f.stale && <Badge tone="warning">Please reconfirm</Badge>}
                {f.editable && edit !== f.key && <Button size="sm" variant="ghost" onClick={() => { setEdit(f.key); setVal(String(f.value ?? "")); }}>Edit</Button>}
              </div>
            </li>
          ))}
        </ul>
      </Card>
      {prefs && (
        <Card title="Preferences" className="mt-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-[13px]">Preferred contact<Select value={prefs.contact_channel} onChange={(e) => setPrefs({ ...prefs, contact_channel: e.target.value })} options={[["phone", "Phone call"], ["sms", "SMS"], ["whatsapp", "WhatsApp"]]} /></label>
            <label className="text-[13px]">Best time to contact<Select value={prefs.contact_window} onChange={(e) => setPrefs({ ...prefs, contact_window: e.target.value })} options={[["ANY", "Any time"], ["MORNING", "Morning (8–12)"], ["AFTERNOON", "Afternoon (12–5)"], ["EVENING", "Evening (5–8)"]]} /></label>
          </div>
          <div className="mt-4 text-[13px] text-muted">What matters most when ranking options</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(PREFS).map(([k, l]) => (
              <button key={k} onClick={() => setPrefs({ ...prefs, ranking: prefs.ranking.includes(k) ? prefs.ranking.filter((x: string) => x !== k) : [...prefs.ranking, k] })} className={`rounded-full border px-3 py-1 text-[13px] ${prefs.ranking.includes(k) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{l}</button>
            ))}
          </div>
          <Button className="mt-4" onClick={savePrefs}>Save preferences</Button>
        </Card>
      )}
    </>
  );
}

function display(f: any) {
  const v = f.value;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (f.key.includes("turnover") || f.key.includes("income") || f.key.includes("repayments")) return `UGX ${Number(v).toLocaleString()}`;
  if (f.key.endsWith("months")) return Number(v) >= 12 ? `${Math.floor(v / 12)} yr ${v % 12 ? `${v % 12} mo` : ""}` : `${v} months`;
  return String(v).replace(/_/g, " ");
}
