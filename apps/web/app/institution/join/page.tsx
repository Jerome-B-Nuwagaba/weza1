"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Button, Card, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";

export default function Join() {
  const [cfg, setCfg] = useState<any>(null);
  const [f, setF] = useState<any>({ legal_name: "", display_name: "", institution_type: "", licence_no: "", regulator: "", description: "", website: "", representative: { name: "", email: "", phone: "", title: "" }, compliance: { name: "", email: "", phone: "" }, admin_name: "", admin_email: "", admin_password: "", accept_terms: false });
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api("/public/config").then(setCfg).catch(() => undefined);
  }, []);
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const setC = (who: string, k: string, v: string) => setF({ ...f, [who]: { ...f[who], [k]: v } });
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/institutions/applications", { body: { ...f, display_name: f.display_name || null } });
      setDone(r.message);
    } catch (e2) {
      setErr(e2 as ApiError);
    } finally {
      setBusy(false);
    }
  }
  const fe = (name: string) => err?.details?.find((d) => d.field === name)?.issue;
  if (done)
    return (
      <PublicShell>
        <div className="mx-auto w-full max-w-xl px-4 py-16">
          <Banner tone="success" title="Application received">{done}</Banner>
          <Button className="mt-4" href="/login">Sign in to continue setup</Button>
        </div>
      </PublicShell>
    );
  return (
    <PublicShell>
      <form onSubmit={submit} className="mx-auto w-full max-w-3xl space-y-4 px-4 py-8">
        <PageHeader eyebrow="WEZA Institutional" title="Join the WEZA network" subtitle="Apply → WEZA verifies → configure products and appetite → activate. No core-system integration required." />
        <Card title="Institution">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Legal name" required error={fe("legal_name")}><Input value={f.legal_name} onChange={(e) => set("legal_name", e.target.value)} required /></Field>
            <Field label="Display name"><Input value={f.display_name} onChange={(e) => set("display_name", e.target.value)} /></Field>
            <Field label="Institution type" required>{cfg && <Select value={f.institution_type} onChange={(e) => set("institution_type", e.target.value)} options={[["", "Choose…"], ...cfg.institution_types]} required />}</Field>
            <Field label="Regulator">{cfg && <Select value={f.regulator} onChange={(e) => set("regulator", e.target.value)} options={[["", "Choose…"], ...cfg.regulators]} />}</Field>
            <Field label="Licence / registration number"><Input value={f.licence_no} onChange={(e) => set("licence_no", e.target.value)} /></Field>
            <Field label="Website"><Input value={f.website} onChange={(e) => set("website", e.target.value)} /></Field>
            <div className="md:col-span-2"><Field label="Short description"><Textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field></div>
          </div>
        </Card>
        <Card title="Authorised representative & compliance contact">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Representative name" required><Input value={f.representative.name} onChange={(e) => setC("representative", "name", e.target.value)} required /></Field>
            <Field label="Representative email" required error={fe("representative.email")}><Input type="email" value={f.representative.email} onChange={(e) => setC("representative", "email", e.target.value)} required /></Field>
            <Field label="Compliance contact name" required><Input value={f.compliance.name} onChange={(e) => setC("compliance", "name", e.target.value)} required /></Field>
            <Field label="Compliance email" required error={fe("compliance.email")}><Input type="email" value={f.compliance.email} onChange={(e) => setC("compliance", "email", e.target.value)} required /></Field>
          </div>
        </Card>
        <Card title="Your administrator account">
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Full name" required><Input value={f.admin_name} onChange={(e) => set("admin_name", e.target.value)} required /></Field>
            <Field label="Email" required error={fe("admin_email")}><Input type="email" value={f.admin_email} onChange={(e) => set("admin_email", e.target.value)} required /></Field>
            <Field label="Password" required hint="12+ characters" error={fe("admin_password")}><Input type="password" value={f.admin_password} onChange={(e) => set("admin_password", e.target.value)} required minLength={12} /></Field>
          </div>
        </Card>
        <label className="flex items-start gap-2 text-[14px]"><input type="checkbox" checked={f.accept_terms} onChange={(e) => set("accept_terms", e.target.checked)} className="mt-1" /> I accept the WEZA marketplace and data-sharing terms (v2026.1) on behalf of the institution, including that customer data is received only under customer consent.</label>
        {err && <Banner tone="danger">{err.message}</Banner>}
        <Button type="submit" size="lg" pending={busy} disabled={!f.accept_terms}>Submit application</Button>
      </form>
    </PublicShell>
  );
}
