"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { Badge, Banner, BarList, Card, ErrorState, Loading, PageHeader, Stat, StateBadge, Table, Td } from "@/components/ui";

const QUEUE_LABEL: Record<string, string> = { INSTITUTION_VERIFICATION: "Institution verification", INTEGRITY: "Integrity review", DUPLICATE_HOLD: "Duplicate holds", DEAD_LETTER: "Failed critical events", FACT_CONFLICT: "Fact conflicts", SERVICE_TARGET: "Institution non-response", GRAPH_FAILED: "Failed workflows" };

export default function ControlCentre() {
  const o = useApi<any>("/admin/overview");
  if (o.loading) return <Loading rows={6} />;
  if (o.error) return <ErrorState error={o.error} onRetry={o.reload} />;
  const d = o.data;
  const m = d.market;
  const ks = d.kill_switches;
  const ill = m.liquidity.filter((l: any) => l.liquidity === "ILLIQUID" || l.liquidity === "LOW");
  return (
    <>
      <PageHeader title="Network Control Centre" subtitle="Is the marketplace healthy, fair and safe? Demand, supply, flow, queues and controls." />
      {(ks.pause_all_routing?.on || ks.pause_billing_events?.on || (ks.ai_mode?.mode && ks.ai_mode.mode !== "AVAILABLE")) && (
        <Banner tone="warning" title="Network controls active" className="mb-4">
          {ks.pause_all_routing?.on && "All routing is paused. "}{ks.pause_billing_events?.on && "Billing-event creation is paused. "}{ks.ai_mode?.mode && ks.ai_mode.mode !== "AVAILABLE" && `AI mode: ${ks.ai_mode.mode}.`} <Link href="/admin/config" className="underline">Manage</Link>
        </Banner>
      )}
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label="Active financial demand" value={m.demand.active_needs} sub={money(m.demand.active_value)} />
        <Stat label="Ready now" value={m.demand.ready_now} tone="gold" />
        <Stat label="Unmatched" value={m.demand.unmatched} sub={`${m.demand.waiting_room} in Waiting Room`} />
        <Stat label="Active institutions" value={m.supply.active_institutions} sub={`${m.supply.active_products} products`} href="/admin/institutions" />
        <Stat label="Routing success" value={m.opportunities.routing_success_rate !== null ? `${Math.round(m.opportunities.routing_success_rate * 100)}%` : "—"} />
        <Stat label="Billable this month" value={m.commercial.billable_this_month} href="/admin/commercial" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Queues needing a human" action={<Link href="/admin/review" className="text-[13px] text-blue-800">Open</Link>}>
          {Object.keys(d.queues).length === 0 ? <p className="text-[14px] text-muted">All clear.</p> : (
            <ul className="space-y-2 text-[14px]">{Object.entries(d.queues).map(([k, v]) => <li key={k} className="flex justify-between"><span>{QUEUE_LABEL[k] || k}</span><Badge tone="warning">{v as number}</Badge></li>)}</ul>
          )}
        </Card>
        <Card title="Platform health">
          <ul className="space-y-2 text-[14px]">
            <li className="flex justify-between"><span>Dead-lettered events</span><Badge tone={m.platform.dead_letters ? "danger" : "success"}>{m.platform.dead_letters}</Badge></li>
            <li className="flex justify-between"><span>Notification failures</span><Badge tone={m.platform.notification_failures ? "danger" : "success"}>{m.platform.notification_failures}</Badge></li>
            <li className="flex justify-between"><span>Failed workflows</span><Badge tone={m.platform.graphs_failed ? "danger" : "success"}>{m.platform.graphs_failed}</Badge></li>
            <li className="flex justify-between"><span>AI calls (24h) / fallbacks</span><span className="num">{m.platform.ai_calls_24h} / {m.platform.ai_fallbacks_24h}</span></li>
          </ul>
        </Card>
        <Card title="Opportunities by freshness"><BarList data={m.opportunities.by_freshness} /></Card>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title="Liquidity — segments with low or no supply" subtitle="Share of active demand with a ready match. Intelligence, not a credit decision.">
          {ill.length === 0 ? <p className="text-[14px] text-muted">No illiquid segments.</p> : (
            <ul className="space-y-2 text-[14px]">{ill.slice(0, 8).map((l: any, i: number) => <li key={i} className="flex justify-between gap-2"><span>{l.customer_type} · {l.region}</span><span className="flex items-center gap-2"><span className="num text-muted">{l.demand} needs · {money(l.value)}</span><StateBadge state={l.liquidity === "ILLIQUID" ? "BLOCKED" : "LIMITED"} label={l.liquidity.toLowerCase()} /></span></li>)}</ul>
          )}
        </Card>
        <Card title="Largest unmet-demand gaps">
          <ul className="space-y-2 text-[14px]">{m.gaps.map((g: any, i: number) => <li key={i} className="flex justify-between gap-2"><span>{g.purpose} · {g.segment}</span><span className="num text-gold-700">{money(g.unmet_value)}</span></li>)}</ul>
        </Card>
      </div>
      <Card title="Institution responsiveness" className="mt-4">
        <Table head={["Institution", "Status", "Opportunities", "Avg first contact", "Unassigned", "Breaches"]}>
          {d.responsiveness.map((r: any) => (
            <tr key={r.id}><Td><Link href={`/admin/institutions/${r.id}`} className="font-medium text-blue-800 hover:underline">{r.institution}</Link></Td><Td><StateBadge state={r.status} /></Td><Td className="num">{r.opportunities}</Td><Td className="num">{r.avg_first_contact_h !== null ? `${r.avg_first_contact_h}h` : "—"}</Td><Td className="num">{r.unassigned}</Td><Td className="num">{r.breaches}</Td></tr>
          ))}
        </Table>
      </Card>
    </>
  );
}
