"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { FIELD_META, Rule, RuleBuilder } from "./RuleBuilder";
import { Banner, Button, Card, Field, Input, Select } from "./ui";

export type AppetiteTarget = {
  customer_type: string;
  sector: string;
  region: string;
  min_amount: string;
  max_amount: string;
  business_age_months: string;
};

export type AppetiteDraft = {
  name: string;
  product_ids: string[];
  criteria: Rule[];
  min_match_score: number;
  target_count?: number | null;
  target_value?: number | null;
  capacity_limits: Record<string, any>;
  campaign_from?: string | null;
  campaign_to?: string | null;
  routing_team_id?: string | null;
};

type EditorState = AppetiteDraft & { target: AppetiteTarget; targetMeta: Record<string, RuleMeta> };

type RuleMeta = { must?: boolean; weight?: number; label?: string };

export const EMPTY_TARGET: AppetiteTarget = {
  customer_type: "", sector: "", region: "", min_amount: "", max_amount: "", business_age_months: "",
};

export const EMPTY_APPETITE: AppetiteDraft = {
  name: "", product_ids: [], criteria: [], min_match_score: 60, capacity_limits: { daily_count: 20 },
  target_count: null, target_value: null, campaign_from: null, campaign_to: null, routing_team_id: null,
};

const one = (v: any) => (Array.isArray(v) && v.length === 1 ? String(v[0]) : "");
const pair = (v: any) => (Array.isArray(v) && v.length === 2 ? [String(v[0]), String(v[1])] : null);

/** The simple "who do you want" fields are stored as ordinary criteria, so the matching engine treats them
 * exactly like any other criterion. Anything the simple form cannot express stays in the advanced builder. */
function splitCriteria(criteria: Rule[]): { target: AppetiteTarget; rest: Rule[]; meta: Record<string, RuleMeta> } {
  const target: AppetiteTarget = { ...EMPTY_TARGET };
  const rest: Rule[] = [];
  const meta: Record<string, RuleMeta> = {};
  for (const c of criteria || []) {
    const keep = { must: c.must, weight: c.weight, label: c.label };
    if (c.field === "customer_type" && c.op === "in" && one(c.value)) {
      target.customer_type = one(c.value);
      meta.customer_type = keep;
      continue;
    }
    if (c.field === "sector" && c.op === "in" && one(c.value)) {
      target.sector = one(c.value);
      meta.sector = keep;
      continue;
    }
    if (c.field === "region" && c.op === "in" && one(c.value)) {
      target.region = one(c.value);
      meta.region = keep;
      continue;
    }
    if (c.field === "amount" && c.op === "between" && pair(c.value)) {
      const p = pair(c.value)!;
      target.min_amount = p[0];
      target.max_amount = p[1];
      meta.amount = keep;
      continue;
    }
    if (c.field === "business_age_months" && c.op === "gte" && c.value !== "" && c.value != null) {
      target.business_age_months = String(c.value);
      meta.business_age_months = keep;
      continue;
    }
    rest.push(c);
  }
  return { target, rest, meta };
}

function targetCriteria(t: AppetiteTarget, meta: Record<string, RuleMeta>): Rule[] {
  const out: Rule[] = [];
  const add = (field: string, op: string, value: any) =>
    out.push({ field, op, value, weight: meta[field]?.weight ?? 1, must: meta[field]?.must ?? true, label: meta[field]?.label });
  if (t.customer_type) add("customer_type", "in", [t.customer_type]);
  if (t.sector) add("sector", "in", [t.sector]);
  if (t.region) add("region", "in", [t.region]);
  if (t.min_amount !== "" && t.max_amount !== "") add("amount", "between", [Number(t.min_amount), Number(t.max_amount)]);
  if (t.business_age_months !== "") add("business_age_months", "gte", Number(t.business_age_months));
  return out;
}

export function AppetiteEditor({ initial, onSave, saving, error }: { initial: AppetiteDraft; onSave: (d: AppetiteDraft) => void; saving: boolean; error?: ApiError | null }) {
  const [d, setD] = useState<EditorState>(() => {
    const { target, rest, meta } = splitCriteria(initial.criteria);
    return { ...initial, criteria: rest, target, targetMeta: meta, routing_team_id: (initial.capacity_limits || {}).routing_team_id || null };
  });
  const [products, setProducts] = useState<any[]>([]);
  const [teams, setTeams] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => {
    api("/inst/products").then((r) => setProducts(r.products)).catch(() => undefined);
    api("/inst/routing").then((r) => setTeams(r.teams || [])).catch(() => undefined);
    api("/public/config").then(setCfg).catch(() => undefined);
  }, []);
  const lim = d.capacity_limits || {};
  const setLim = (k: string, v: string) => setD({ ...d, capacity_limits: { ...lim, [k]: Number(v || 0) } });
  const setT = (patch: Partial<AppetiteTarget>) => setD({ ...d, target: { ...d.target, ...patch } });
  const sectors: [string, string][] = cfg ? (Object.entries(cfg.sectors) as [string, string][]) : [];
  const regions: [string, string][] = FIELD_META.region.options || [];

  function save() {
    const criteria = [...d.criteria, ...targetCriteria(d.target, d.targetMeta)];
    const capacity_limits: Record<string, any> = { ...lim };
    if (d.routing_team_id) capacity_limits.routing_team_id = d.routing_team_id;
    else delete capacity_limits.routing_team_id;
    onSave({
      name: d.name, product_ids: d.product_ids, criteria, min_match_score: d.min_match_score,
      target_count: d.target_count, target_value: d.target_value, capacity_limits,
      campaign_from: d.campaign_from, campaign_to: d.campaign_to, routing_team_id: d.routing_team_id,
    });
  }

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

      <Card title="Who to serve" subtitle="Who this mandate is for. Each filled field must match — a customer outside it is not offered.">
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Customer type">
            <Select value={d.target.customer_type} onChange={(e) => setT({ customer_type: e.target.value })} options={[["", "Any"], ...(FIELD_META.customer_type.options || [])]} />
          </Field>
          <Field label="Sector">
            <Select value={d.target.sector} onChange={(e) => setT({ sector: e.target.value })} options={[["", "Any"], ...sectors]} />
          </Field>
          <Field label="Geography">
            <Select value={d.target.region} onChange={(e) => setT({ region: e.target.value })} options={[["", "Anywhere"], ...regions]} />
          </Field>
          <Field label="Minimum business age (months)" hint="How long the business must have been trading.">
            <Input inputMode="numeric" value={d.target.business_age_months} onChange={(e) => setT({ business_age_months: e.target.value })} placeholder="e.g. 12" />
          </Field>
          <Field label="Minimum amount (UGX)">
            <Input inputMode="numeric" value={d.target.min_amount} onChange={(e) => setT({ min_amount: e.target.value })} />
          </Field>
          <Field label="Maximum amount (UGX)">
            <Input inputMode="numeric" value={d.target.max_amount} onChange={(e) => setT({ max_amount: e.target.value })} />
          </Field>
          <Field label="Routing destination" hint="The desk that receives opportunities matched by this mandate.">
            <Select value={d.routing_team_id || ""} onChange={(e) => setD({ ...d, routing_team_id: e.target.value || null })} options={[["", "Unassigned queue"], ...teams.map((t: any) => [t.id, t.name] as [string, string])]} />
          </Field>
        </div>
      </Card>

      <Card title="Additional criteria" subtitle="Anything else that shapes appetite fit. 'Must' criteria exclude; others are weighted.">
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
      <div className="flex justify-end"><Button pending={saving} disabled={!d.name || d.product_ids.length === 0} onClick={save}>Save draft</Button></div>
    </div>
  );
}
