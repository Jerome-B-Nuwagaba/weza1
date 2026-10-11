"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button, inputCls, Select } from "./ui";

export const FIELD_META: Record<string, { label: string; kind: "money" | "months" | "enum" | "bool" | "ratio" | "text"; options?: [string, string][] }> = {
  amount: { label: "Requested amount (UGX)", kind: "money" },
  tenor_months: { label: "Repayment period (months)", kind: "months" },
  customer_type: { label: "Customer type", kind: "enum", options: [["SME", "Business (SME)"], ["SALARIED", "Salaried"], ["AGRICULTURE", "Farmer"]] },
  sector: { label: "Sector", kind: "enum" },
  region: { label: "Region", kind: "enum", options: [["Central", "Central"], ["Eastern", "Eastern"], ["Northern", "Northern"], ["Western", "Western"]] },
  district: { label: "District", kind: "text" },
  purpose_category: { label: "Purpose", kind: "enum" },
  business_age_months: { label: "Business age (months)", kind: "months" },
  monthly_turnover: { label: "Monthly turnover (UGX)", kind: "money" },
  business_registered: { label: "Business registered", kind: "bool" },
  employment_type: { label: "Employment type", kind: "enum", options: [["permanent", "Permanent"], ["contract", "Contract"], ["casual", "Casual"]] },
  employment_months: { label: "Time with employer (months)", kind: "months" },
  monthly_income: { label: "Monthly take-home (UGX)", kind: "money" },
  farm_activity: { label: "Farming activity", kind: "enum", options: [["crops", "Crops"], ["livestock", "Livestock"], ["poultry", "Poultry"], ["dairy", "Dairy"], ["fish", "Fish"], ["mixed", "Mixed"]] },
  operating_months: { label: "Operating history (months)", kind: "months" },
  annual_income: { label: "Annual farm income (UGX)", kind: "money" },
  monthly_repayments: { label: "Existing monthly repayments (UGX)", kind: "money" },
  debt_service_ratio: { label: "Repayments ÷ capacity (0–1)", kind: "ratio" },
  has_nin: { label: "National ID provided", kind: "bool" },
};

export type Rule = { field: string; op: string; value: any; label?: string; weight?: number; must?: boolean };

const OPS_FOR: Record<string, [string, string][]> = {
  money: [["gte", "at least"], ["lte", "at most"], ["between", "between"]],
  months: [["gte", "at least"], ["lte", "at most"]],
  ratio: [["lte", "at most"], ["gte", "at least"]],
  enum: [["in", "is one of"], ["not_in", "is not"]],
  text: [["in", "is one of"]],
  bool: [["is_true", "is yes"]],
};

export function RuleBuilder({ rules, onChange, cfg, appetite }: { rules: Rule[]; onChange: (r: Rule[]) => void; cfg: any; appetite?: boolean }) {
  const meta = (f: string) => {
    const m = FIELD_META[f];
    if (f === "sector" && cfg) return { ...m, options: Object.entries(cfg.sectors) as [string, string][] };
    if (f === "purpose_category" && cfg) return { ...m, options: Object.entries(cfg.purpose_categories) as [string, string][] };
    return m;
  };
  const set = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-2">
      {rules.length === 0 && <p className="text-[13px] text-muted">No {appetite ? "criteria" : "rules"} yet.</p>}
      {rules.map((r, i) => {
        const m = meta(r.field);
        const ops = OPS_FOR[m.kind];
        return (
          <div key={i} className="grid grid-cols-1 gap-2 rounded-lg border border-line p-3 md:grid-cols-[1.3fr_0.9fr_1.6fr_auto]">
            <Select value={r.field} onChange={(e) => set(i, { field: e.target.value, op: OPS_FOR[meta(e.target.value).kind][0][0], value: defaultValue(meta(e.target.value).kind) })} options={Object.entries(FIELD_META).map(([k, v]) => [k, v.label])} aria-label="Field" />
            <Select value={r.op} onChange={(e) => set(i, { op: e.target.value, value: e.target.value === "between" ? [0, 0] : r.value })} options={ops} aria-label="Operator" />
            <ValueInput kind={m.kind} op={r.op} value={r.value} options={m.options} onChange={(v) => set(i, { value: v })} />
            <div className="flex items-center gap-2">
              {appetite && (
                <>
                  <label className="flex items-center gap-1 text-[12px] text-muted" title="Must-have criteria exclude non-matching demand; others shape appetite fit"><input type="checkbox" checked={!!r.must} onChange={(e) => set(i, { must: e.target.checked })} /> must</label>
                  <Select value={String(r.weight ?? 1)} onChange={(e) => set(i, { weight: Number(e.target.value) })} options={[["1", "×1"], ["2", "×2"], ["3", "×3"]]} className="!w-16" aria-label="Weight" />
                </>
              )}
              <button onClick={() => onChange(rules.filter((_, j) => j !== i))} className="rounded p-2 text-muted hover:bg-danger-bg hover:text-danger" aria-label="Remove"><Trash2 className="h-4 w-4" /></button>
            </div>
            <input value={r.label || ""} onChange={(e) => set(i, { label: e.target.value })} placeholder="Label shown in explanations (optional)" className={`${inputCls} h-9 text-[13px] md:col-span-4`} />
          </div>
        );
      })}
      <Button size="sm" variant="secondary" onClick={() => onChange([...rules, { field: "monthly_turnover", op: "gte", value: 1000000, weight: 1 }])}><Plus className="h-4 w-4" /> Add {appetite ? "criterion" : "rule"}</Button>
    </div>
  );
}

function defaultValue(kind: string) {
  return kind === "enum" || kind === "text" ? [] : kind === "bool" ? true : kind === "ratio" ? 0.5 : 0;
}

function ValueInput({ kind, op, value, options, onChange }: { kind: string; op: string; value: any; options?: [string, string][]; onChange: (v: any) => void }) {
  if (kind === "bool") return <span className="flex items-center text-[13px] text-muted">—</span>;
  if (options && (op === "in" || op === "not_in")) {
    const arr: string[] = Array.isArray(value) ? value : [];
    return (
      <div className="flex flex-wrap gap-1">
        {options.map(([v, l]) => (
          <button key={v} type="button" onClick={() => onChange(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])} className={`rounded-full border px-2 py-0.5 text-[12px] ${arr.includes(v) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{l}</button>
        ))}
      </div>
    );
  }
  if (op === "in") return <input className={`${inputCls} h-10`} value={(Array.isArray(value) ? value : []).join(", ")} onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} placeholder="Comma-separated" />;
  if (op === "between") {
    const [a, b] = Array.isArray(value) ? value : [0, 0];
    return (
      <div className="flex gap-2">
        <input className={`${inputCls} h-10`} inputMode="numeric" value={a} onChange={(e) => onChange([Number(e.target.value || 0), b])} />
        <input className={`${inputCls} h-10`} inputMode="numeric" value={b} onChange={(e) => onChange([a, Number(e.target.value || 0)])} />
      </div>
    );
  }
  return <input className={`${inputCls} h-10`} inputMode="decimal" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />;
}
