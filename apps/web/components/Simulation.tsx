"use client";

import { money } from "@/lib/format";
import { BarList, Card } from "./ui";

export function SimulationResult({ r, compare }: { r: any; compare?: any }) {
  const zone = (k: "inside" | "near" | "outside", label: string, tone: string) => (
    <div className={`rounded-xl border p-4 ${tone}`}>
      <div className="text-[12px] font-semibold uppercase tracking-wide opacity-80">{label}</div>
      <div className="num mt-1 text-2xl font-semibold">{r[k].count}</div>
      <div className="num text-[13px]">{money(r[k].value)} requested</div>
      {compare && <div className="num mt-1 text-[12px] opacity-75">was {compare[k].count} · {money(compare[k].value)}</div>}
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        {zone("inside", "Inside appetite", "border-gold-500/40 bg-gold-100 text-gold-700")}
        {zone("near", "Near appetite", "border-blue-100 bg-blue-50 text-blue-800")}
        {zone("outside", "Outside appetite", "border-line bg-surface text-muted")}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Most-missed criteria (near demand)"><BarList data={r.near_miss_reasons} empty="No near-miss demand." /></Card>
        <Card title="Inside — by region"><BarList data={r.by_region} empty="No matching demand." /></Card>
        <Card title="Inside — match bands"><BarList data={r.match_bands} empty="—" /></Card>
      </div>
      <p className="text-[12px] text-muted">{r.note} Based on {r.demand_considered} anonymised needs from the last {r.demand_window_days} days; groups under 5 are suppressed.</p>
    </div>
  );
}
