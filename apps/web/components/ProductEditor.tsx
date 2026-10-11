"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { RuleBuilder, Rule } from "./RuleBuilder";
import { Banner, Button, Card, Field, Input, Select, Textarea } from "./ui";

export type ProductDraft = { name: string; family: string; terms: any; rules: Rule[]; requirements: { doc_type: string; label: string; required: boolean }[]; provenance?: any };

export const EMPTY: ProductDraft = {
  name: "", family: "SME_WORKING_CAPITAL",
  terms: { min_amount: 1000000, max_amount: 50000000, min_tenor_months: 3, max_tenor_months: 24, pricing_display: "", collateral_required: false, digital_journey: true, typical_response_hours: 24, description: "" },
  rules: [], requirements: [],
};

export function ProductEditor({ initial, onSave, saving, error }: { initial: ProductDraft; onSave: (d: ProductDraft) => void; saving: boolean; error?: ApiError | null }) {
  const [d, setD] = useState<ProductDraft>(initial);
  const [meta, setMeta] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api("/inst/products").then(setMeta).catch(() => undefined);
    api("/public/config").then(setCfg).catch(() => undefined);
  }, []);
  useEffect(() => setD(initial), [initial]);
  const t = d.terms;
  const setT = (patch: any) => setD({ ...d, terms: { ...t, ...patch } });
  return (
    <div className="space-y-4">
      {d.provenance && (
        <Banner tone="gold" title="AI-proposed draft">Values below were proposed from your document ({d.provenance.source}). Review every field — nothing is active until approved by an authorised user.</Banner>
      )}
      <Card title="Identity">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Product name" required><Input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></Field>
          <Field label="Product family" required>{meta && <Select value={d.family} onChange={(e) => setD({ ...d, family: e.target.value })} options={Object.entries(meta.families) as [string, string][]} />}</Field>
          <div className="md:col-span-2"><Field label="Customer-facing description"><Textarea rows={2} value={t.description || ""} onChange={(e) => setT({ description: e.target.value })} /></Field></div>
        </div>
      </Card>
      <Card title="Terms" subtitle="Indicative only — your institution confirms final terms with the customer.">
        <div className="grid gap-4 md:grid-cols-4">
          <Field label="Min amount (UGX)"><Input inputMode="numeric" value={t.min_amount} onChange={(e) => setT({ min_amount: Number(e.target.value || 0) })} /></Field>
          <Field label="Max amount (UGX)"><Input inputMode="numeric" value={t.max_amount} onChange={(e) => setT({ max_amount: Number(e.target.value || 0) })} /></Field>
          <Field label="Min tenor (months)"><Input inputMode="numeric" value={t.min_tenor_months} onChange={(e) => setT({ min_tenor_months: Number(e.target.value || 0) })} /></Field>
          <Field label="Max tenor (months)"><Input inputMode="numeric" value={t.max_tenor_months} onChange={(e) => setT({ max_tenor_months: Number(e.target.value || 0) })} /></Field>
          <div className="md:col-span-2"><Field label="Pricing shown to customers" hint="Approved wording only, e.g. 'From 18% p.a. (indicative)'"><Input value={t.pricing_display || ""} onChange={(e) => setT({ pricing_display: e.target.value })} /></Field></div>
          <Field label="Typical response (hours)"><Input inputMode="numeric" value={t.typical_response_hours ?? ""} onChange={(e) => setT({ typical_response_hours: Number(e.target.value || 0) })} /></Field>
          <div className="flex flex-col justify-end gap-2 text-[14px]">
            <label className="flex items-center gap-2"><input type="checkbox" checked={!!t.collateral_required} onChange={(e) => setT({ collateral_required: e.target.checked })} /> Collateral required</label>
            <label className="flex items-center gap-2"><input type="checkbox" checked={!!t.digital_journey} onChange={(e) => setT({ digital_journey: e.target.checked })} /> Digital process</label>
          </div>
        </div>
      </Card>
      <Card title="Eligibility rules" subtitle="Deterministic, versioned rules. A failed rule excludes; missing information makes the customer 'almost ready'.">
        <RuleBuilder rules={d.rules} onChange={(rules) => setD({ ...d, rules })} cfg={cfg} />
      </Card>
      <Card title="Requirements for qualification">
        <div className="space-y-2">
          {d.requirements.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_auto_auto] items-center gap-2">
              {meta && <Select value={r.doc_type} onChange={(e) => setD({ ...d, requirements: d.requirements.map((x, j) => (j === i ? { ...x, doc_type: e.target.value, label: meta.doc_types[e.target.value] } : x)) })} options={Object.entries(meta.doc_types).filter(([k]) => k !== "product_document") as [string, string][]} />}
              <Input value={r.label} onChange={(e) => setD({ ...d, requirements: d.requirements.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) })} />
              <label className="flex items-center gap-1 text-[13px]"><input type="checkbox" checked={r.required} onChange={(e) => setD({ ...d, requirements: d.requirements.map((x, j) => (j === i ? { ...x, required: e.target.checked } : x)) })} /> required</label>
              <button onClick={() => setD({ ...d, requirements: d.requirements.filter((_, j) => j !== i) })} className="p-2 text-muted hover:text-danger" aria-label="Remove"><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
          <Button size="sm" variant="secondary" onClick={() => setD({ ...d, requirements: [...d.requirements, { doc_type: "bank_statement", label: "Bank statement (3–6 months)", required: false }] })}><Plus className="h-4 w-4" /> Add requirement</Button>
        </div>
      </Card>
      {error && <Banner tone="danger">{error.message}</Banner>}
      <div className="flex justify-end"><Button pending={saving} onClick={() => onSave(d)} disabled={!d.name.trim()}>Save draft</Button></div>
    </div>
  );
}
