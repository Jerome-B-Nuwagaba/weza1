"use client";

import { useApi } from "@/lib/hooks";
import { BarList, Card, ErrorState, Loading, PageHeader, Table, Td } from "@/components/ui";

export default function Loops() {
  const r = useApi<any>("/admin/loops");
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  const d = r.data;
  return (
    <>
      <PageHeader title="Loops & AI observability" subtitle="Node-level flow, where customers wait, loop budgets and AI cost, latency and fallbacks (last 30 days)." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Journey node entries"><BarList data={Object.fromEntries(Object.entries(d.node_entries).sort((a: any, b: any) => b[1] - a[1]).slice(0, 14)) as any} /></Card>
        <Card title="Currently waiting at node"><BarList data={d.waiting_at} empty="No waiting journeys." /></Card>
      </div>
      <Card title="Workflow instances" className="mt-4">
        <Table head={["Graph", "Status", "Count"]} empty={d.instances.length === 0}>{d.instances.map((x: any, i: number) => <tr key={i}><Td>{x.graph}</Td><Td>{x.status}</Td><Td className="num">{x.count}</Td></tr>)}</Table>
      </Card>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Agent loops">
          <Table head={["Loop", "Event", "Count"]} empty={d.loops.length === 0}>{d.loops.map((x: any, i: number) => <tr key={i}><Td>{x.loop}</Td><Td>{x.event}</Td><Td className="num">{x.count}</Td></tr>)}</Table>
        </Card>
        <Card title="AI Control Plane">
          <Table head={["Capability", "Calls", "Avg ms", "Tokens", "Fallbacks", "Schema failures"]} empty={d.ai.length === 0}>{d.ai.map((x: any, i: number) => <tr key={i}><Td>{x.capability}</Td><Td className="num">{x.calls}</Td><Td className="num">{x.avg_latency_ms}</Td><Td className="num">{x.tokens}</Td><Td className="num">{x.fallbacks}</Td><Td className="num">{x.validation_failures}</Td></tr>)}</Table>
          {d.ai.every((x: any) => x.tokens === 0) && <p className="mt-2 text-[12px] text-muted">No AI provider key configured — every capability is running its deterministic fallback.</p>}
        </Card>
      </div>
    </>
  );
}
