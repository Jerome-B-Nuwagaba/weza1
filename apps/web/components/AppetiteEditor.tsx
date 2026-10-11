"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { RuleBuilder, Rule } from "./RuleBuilder";
import { Banner, Button, Card, Field, Input } from "./ui";

export type AppetiteDraft = { name: string; product_ids: string[]; criteria: Rule[]; min_match_score: number; target_count?: number | null; target_value?: number | null; capacity_limits: Record<string, number>; campaign_from?: string | null; campaign_to?: string | null };

export const EMPTY_APPETITE: AppetiteDraft = { name: "", product_ids: [], criteria: [], min_match_score: 60, capacity_limits: { daily_count: 20 }, target_count: null, target_value: null, campaign_from: null, campaign_to: null };

export function AppetiteEditor({ initial, onSave, saving, error }: { initial: AppetiteDraft; onSave: (d: AppetiteDraft) => void; saving: boolean; error?: ApiError | null }) {
  const [d, setD] = useState(initial);
  const [products, setProducts] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api("/inst/products").then((r) => setProducts(r.products)).catch(() => undefined);
    api("/public/config").then(setCfg).catch(() => undefined);
  }, []);
  const lim = d.capacity_limits || {};
  const setLim = (k: string, v: string) => setD({ ...d, capacity_limits: { ...lim, [k]: Number(v || 0) } });
  return (
    <div className="space-y-4">
      <Card title="Mandate">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Name" required><Input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} placeholder="e.g. Q4 SME Growth Mandate" /></Field>
          <Field label="Minimum match score" hint="Opportunities below this score are not offered to customers."><Input type="number" min={0} max={100} value={d.min_match_score} onChange={(e) => setD({ ...d, min_match_score: Number(e.target.value) })} /></Field>
          <div className="md:col-span-2">
            <Field label="Products covered" required>
              <div className="flex flex-wrap gap-2">
                {products.map((p) => (
                  <button key={p.id} type="button" onClick={() => setD({ ...d, product_ids: d.product_ids.includes(p.id) ? d.product_ids.filter((x) => x !== p.id) : [...d.product_ids, p.id] })} className={`rounded-full border px-3 py-1 text-[13px] ${d.product_ids.includes(p.id) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{p.name} <span className="opacity-70">({p.status.toLowerCase()})</span></button>
                ))}
              </div>
            </Field>
          </div>
        </div>
      </Card>
      <Card title="Who do you want WEZA to find?" subtitle="'Must' criteria exclude. Others shape appetite fit (weighted).">
        <RuleBuilder rules={d.criteria} onChange={(criteria) => setD({ ...d, criteria })} cfg={cfg} appetite />
      </Card>
      <Card title="Targets & capacity" subtitle="Capacity protects your teams: WEZA marks the mandate LIMITED at 80% and FULL at 100%.">
        <div className="grid gap-4 md:grid-cols-4">
          <Field label="Target opportunities"><Input inputMode="numeric" value={d.target_count ?? ""} onChange={(e) => setD({ ...d, target_count: e.target.value ? Number(e.target.value) : null })} /></Field>
          <Field label="Target value (UGX)"><Input inputMode="numeric" value={d.target_value ?? ""} onChange={(e) => setD({ ...d, target_value: e.target.value ? Number(e.target.value) : null })} /></Field>
          <Field label="Campaign from"><Input type="date" value={d.campaign_from || ""} onChange={(e) => setD({ ...d, campaign_from: e.target.value || null })} /></Field>
          <Field label="Campaign to"><Input type="date" value={d.campaign_to || ""} onChange={(e) => setD({ ...d, campaign_to: e.target.value || null })} /></Field>
          <Field label="Max per day"><Input inputMode="numeric" value={lim.daily_count ?? ""} onChange={(e) => setLim("daily_count", e.target.value)} /></Field>
          <Field label="Max per week"><Input inputMode="numeric" value={lim.weekly_count ?? ""} onChange={(e) => setLim("weekly_count", e.target.value)} /></Field>
          <Field label="Max per month"><Input inputMode="numeric" value={lim.monthly_count ?? ""} onChange={(e) => setLim("monthly_count", e.target.value)} /></Field>
          <Field label="Max value per month (UGX)"><Input inputMode="numeric" value={lim.monthly_value ?? ""} onChange={(e) => setLim("monthly_value", e.target.value)} /></Field>
        </div>
      </Card>
      {error && <Banner tone="danger">{error.message}</Banner>}
      <div className="flex justify-end"><Button pending={saving} disabled={!d.name || d.product_ids.length === 0} onClick={() => onSave(d)}>Save draft</Button></div>
    </div>
  );
}
