"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { BarList, Card, ErrorState, Loading, PageHeader, Select, Sparkbars, Stat } from "@/components/ui";

const READINESS: Record<string, string> = { READY_NOW: "Ready now", ALMOST_READY: "Almost ready", NO_CURRENT_MATCH: "No current match" };
const TYPES: Record<string, string> = { SME: "Business (SME)", SALARIED: "Salaried", AGRICULTURE: "Farmer" };

export default function Demand() {
  const [days, setDays] = useState("90");
  const d = useApi<any>(`/inst/intelligence/demand?days=${days}`, [days]);
  if (d.loading && !d.data) return <Loading rows={6} />;
  if (d.error) return <ErrorState error={d.error} onRetry={d.reload} />;
  const x = d.data;
  const relabel = (o: Record<string, number>, map: Record<string, string>) => Object.fromEntries(Object.entries(o).map(([k, v]) => [map[k] || k, v]));
  return (
    <>
      <PageHeader title="Demand Intelligence" subtitle={x.note} actions={<Select value={days} onChange={(e) => setDays(e.target.value)} options={[["30", "Last 30 days"], ["90", "Last 90 days"], ["180", "Last 180 days"]]} className="!w-40" />} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Financing requests" value={x.total_needs} />
        <Stat label="Requested value" value={money(x.total_value)} tone="gold" />
        <Stat label="Average ticket" value={x.total_needs ? money(x.total_value / x.total_needs) : "—"} />
        <Card className="col-span-2 md:col-span-1"><div className="text-[12px] text-muted">Weekly requests (12 weeks)</div><Sparkbars values={x.weekly_trend} height={40} /></Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <Card title="By region"><BarList data={x.by_region} /></Card>
        <Card title="Requested value by region"><BarList data={x.value_by_region} format={money} /></Card>
        <Card title="By district"><BarList data={x.by_district} /></Card>
        <Card title="By sector"><BarList data={x.by_sector} /></Card>
        <Card title="By purpose"><BarList data={x.by_purpose} /></Card>
        <Card title="Ticket sizes"><BarList data={x.ticket_sizes} /></Card>
        <Card title="Customer type"><BarList data={relabel(x.by_customer_type, TYPES)} /></Card>
        <Card title="Readiness"><BarList data={relabel(x.by_readiness, READINESS)} /></Card>
        <Card title="Your match bands"><BarList data={x.match_bands} empty="No matches in this period." /></Card>
      </div>
    </>
  );
}
