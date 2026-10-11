"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Banner, Button, Card, PageHeader, Stat, StateBadge, Table, Td } from "@/components/ui";

export default function Sandbox() {
  const [r, setR] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setErr(null);
    try {
      setR(await api("/inst/sandbox/runs", { method: "POST" }));
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="Configuration sandbox" subtitle="Test your latest product, appetite and routing configuration — including drafts — against 60 synthetic customers. Nothing is stored as a real opportunity or billed." actions={<Button pending={busy} onClick={run}>Run sandbox</Button>} />
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      {!r ? <Card><p className="text-[14px] text-muted">Synthetic scenarios include typical demand, small high-volume tickets, large tickets, young businesses and rural agriculture.</p></Card> : !r.ready ? <Banner tone="warning">{r.message}</Banner> : (
        <>
          <Banner tone="gold" className="mb-4">{r.note}</Banner>
          <div className="mb-4 grid grid-cols-3 gap-3">
            <Stat label="Would route" value={r.summary.WOULD_ROUTE || 0} tone="gold" />
            <Stat label="Eligible, below threshold" value={r.summary.BELOW_THRESHOLD || 0} />
            <Stat label="Excluded" value={r.summary.EXCLUDED || 0} />
          </div>
          <Table head={["Synthetic", "Scenario", "Customer", "Amount", "Best product", "Score", "Outcome", "Routed to / reason"]}>
            {r.results.map((x: any) => (
              <tr key={x.synthetic_id}>
                <Td className="num text-muted">{x.synthetic_id}</Td>
                <Td>{x.scenario.replace(/_/g, " ")}</Td>
                <Td>{x.customer_type} · {x.region}</Td>
                <Td className="num">{x.amount}</Td>
                <Td>{x.product} <Badge tone="muted">v{x.product_version} {x.product_status.toLowerCase()}</Badge></Td>
                <Td className="num">{Math.round(x.score)}</Td>
                <Td><StateBadge state={x.outcome === "WOULD_ROUTE" ? "ACTIVE" : x.outcome === "EXCLUDED" ? "REJECTED" : "LIMITED"} label={x.outcome.replace(/_/g, " ").toLowerCase()} /></Td>
                <Td className="text-[13px] text-muted">{x.routed_to || x.reasons.join(" · ")}</Td>
              </tr>
            ))}
          </Table>
        </>
      )}
    </>
  );
}
