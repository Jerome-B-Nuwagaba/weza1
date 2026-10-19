"use client";

import type { ApiError } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { useApi } from "@/lib/hooks";
import { money, STATE_LABEL } from "@/lib/format";
import { Bar, BarList, Button, Card, ErrorState, Loading, PageHeader, Stat, useToast } from "@/components/ui";

export default function Reports() {
  const r = useApi<any>("/inst/reports/outcomes");
  const { toast, node } = useToast();
  async function exportCsv() {
    try {
      await downloadFile("/inst/reports/export", "weza-opportunities.csv");
      toast("Export downloaded");
    } catch (e) {
      toast((e as ApiError).message || "Export failed. Please try again.");
    }
  }
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const d = r.data;
  const max = Math.max(1, ...d.funnel.map((f: any) => f.count));
  return (
    <>
      {node}
      <PageHeader title="Outcomes & reports" subtitle={d.label}
        actions={<Button variant="secondary" onClick={exportCsv}>Export CSV (no customer identity)</Button>} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3">
        <Stat label="Opportunities received" value={d.total} />
        <Stat label="Reported approved value" value={money(d.reported_approved_value)} />
        <Stat label="Reported disbursed value" value={money(d.reported_disbursed_value)} tone="gold" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Stage reached">
          <ul className="space-y-2">{d.funnel.map((f: any) => (
            <li key={f.stage} className="grid grid-cols-[170px_1fr_40px] items-center gap-3 text-[13px]"><span className="text-muted">{STATE_LABEL[f.stage]}</span><Bar value={f.count} max={max} tone={f.stage === "REPORTED_DISBURSED" ? "gold" : "blue"} /><span className="num text-right">{f.count}</span></li>
          ))}</ul>
        </Card>
        <Card title="Reported decline reasons"><BarList data={d.decline_reasons} empty="No declines reported." /></Card>
        <Card title="Opportunities by product"><BarList data={d.by_product} /></Card>
      </div>
    </>
  );
}
