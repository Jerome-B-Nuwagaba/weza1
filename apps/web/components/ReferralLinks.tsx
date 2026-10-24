"use client";

import { Copy, Download } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Banner, Button, Card, Field, Input } from "./ui";

type Link = { link: string; reference: string; qr_svg: string };

/** Partner and campaign links with printable QR codes (BRD §5). Every customer who arrives through one is traced to its
 * source, campaign, partner and referral code. Making a link changes nothing; the lineage is recorded on arrival. */
export function ReferralLinks() {
  const [f, setF] = useState({ source: "", campaign: "", partner: "", referral: "", text: "Hi" });
  const [out, setOut] = useState<Link | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function make(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setCopied(false);
    try {
      const q = new URLSearchParams(Object.entries(f).filter(([, v]) => v.trim()) as [string, string][]);
      setOut(await api<Link>(`/admin/referral-links?${q}`));
    } catch (error) {
      setOut(null);
      setErr((error as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const svg = out ? `data:image/svg+xml;utf8,${encodeURIComponent(out.qr_svg)}` : "";
  return (
    <Card title="Campaign links & QR codes" subtitle="A link or QR code that opens WhatsApp on WEZA's number and tags every customer who arrives through it.">
      <form onSubmit={make} className="grid gap-3 md:grid-cols-4">
        <Field label="Source" hint="e.g. qr, sms, poster"><Input value={f.source} onChange={set("source")} maxLength={40} /></Field>
        <Field label="Campaign" hint="e.g. sacco-week-2026"><Input value={f.campaign} onChange={set("campaign")} maxLength={40} /></Field>
        <Field label="Partner" hint="e.g. kampala-sacco"><Input value={f.partner} onChange={set("partner")} maxLength={40} /></Field>
        <Field label="Referral code" hint="e.g. a1b2"><Input value={f.referral} onChange={set("referral")} maxLength={40} /></Field>
        <div className="md:col-span-3"><Field label="First message the customer sends" hint="Shown to them before they send it."><Input value={f.text} onChange={set("text")} maxLength={200} /></Field></div>
        <div className="flex items-end"><Button type="submit" pending={busy} className="w-full">Create link and QR code</Button></div>
      </form>
      {err && <div className="mt-3"><Banner tone="danger">{err}</Banner></div>}
      {out && (
        <div className="mt-4 flex flex-col gap-4 sm:flex-row">
          <img src={svg} alt={`QR code for ${out.reference}`} className="h-44 w-44 shrink-0 rounded-lg border border-line bg-white p-1" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="text-[12px] uppercase tracking-wide text-muted">Tracking tag {out.reference}</div>
            <code className="block break-all rounded-lg border border-line bg-canvas p-2 text-[12.5px]">{out.link}</code>
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={async () => { await navigator.clipboard?.writeText(out.link); setCopied(true); }}>
                <Copy className="h-3.5 w-3.5" /> {copied ? "Copied" : "Copy link"}
              </Button>
              <a href={svg} download={`weza-qr-${out.reference.replace(/[^A-Za-z0-9_.-]+/g, "-")}.svg`}
                className="inline-flex h-8 items-center gap-2 rounded-lg border border-line bg-surface px-3 text-[13px] font-medium text-ink hover:bg-blue-50">
                <Download className="h-3.5 w-3.5" /> Download QR (SVG)
              </a>
            </div>
            <p className="text-[12px] text-muted">The SVG scales to any size without blurring, so one file works for a business card and a poster.</p>
          </div>
        </div>
      )}
    </Card>
  );
}
