"use client";

import { useApi } from "@/lib/hooks";
import { dateTime, money } from "@/lib/format";
import { BarList, Card, ErrorState, KV, Loading, PageHeader, Sparkbars, Stat, StateBadge, Table, Td } from "@/components/ui";

export default function Market() {
  const r = useApi<any>("/admin/market");
  if (r.loading) return <Loading rows={6} />;
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  const { state: s, demand: dm, clearing_runs: runs, shadow } = r.data;
  return (
    <>
      <PageHeader title="Market State" subtitle="MARKET_STATE(t) = demand + supply + appetite + capacity + preferences + active opportunities + recent outcomes." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Active demand value" value={money(s.demand.active_value)} tone="gold" />
        <Stat label="Almost ready" value={s.demand.almost_ready} />
        <Stat label="Waiting Room" value={s.demand.waiting_room} />
        <Card><div className="text-[12px] text-muted">Weekly requests</div><Sparkbars values={dm.weekly_trend} height={40} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Appetites by capacity"><BarList data={s.supply.appetites_by_capacity} /></Card>
        <Card title="Opportunities by state"><BarList data={s.opportunities.by_state} /></Card>
        <Card title="Demand by region"><BarList data={dm.by_region} /></Card>
      </div>
      <Card title="Liquidity by segment" className="mt-4">
        <Table head={["Customer type", "Region", "Demand", "Matched", "Share", "Value", "Liquidity"]} empty={s.liquidity.length === 0}>
          {s.liquidity.map((l: any, i: number) => <tr key={i}><Td>{l.customer_type}</Td><Td>{l.region}</Td><Td className="num">{l.demand}</Td><Td className="num">{l.matched}</Td><Td className="num">{Math.round(l.matched_share * 100)}%</Td><Td className="num">{money(l.value)}</Td><Td><StateBadge state={{ HIGH: "ACTIVE", MEDIUM: "LIMITED", LOW: "PAUSED", ILLIQUID: "BLOCKED" }[l.liquidity as string]} label={l.liquidity.toLowerCase()} /></Td></tr>)}
        </Table>
      </Card>
      <div className="mt-4 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Card title="Market clearing runs" subtitle="Event-driven; deterministic clearing priority; every run is recorded.">
          <Table head={["When", "Trigger", "Needs", "Matches", "Newly ready", "ms"]} empty={runs.length === 0}>
            {runs.map((x: any) => <tr key={x.id}><Td>{dateTime(x.started_at)}</Td><Td className="text-[12px]">{x.trigger}</Td><Td className="num">{x.needs}</Td><Td className="num">{x.matches}</Td><Td className="num">{x.newly_matched}</Td><Td className="num">{x.ms}</Td></tr>)}
          </Table>
        </Card>
        {shadow && (
          <Card title="Shadow algorithm" subtitle={shadow.note}>
            <KV items={[["Production eligible", shadow.production.eligible_matches], ["Production avg score", shadow.production.avg_score], [`Shadow (${shadow.shadow.algorithm})`, shadow.shadow.eligible_matches], ["Shadow avg score", shadow.shadow.avg_score]]} />
          </Card>
        )}
      </div>
    </>
  );
}
