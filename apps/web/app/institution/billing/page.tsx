"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, moneyFull } from "@/lib/format";
import { Banner, Button, Card, ErrorState, Field, KV, Loading, Modal, PageHeader, Select, Stat, StateBadge, Table, Td, Textarea } from "@/components/ui";

export default function Billing() {
  const b = useApi<any>("/inst/billing");
  const [dispute, setDispute] = useState<any>(null);
  const [reason, setReason] = useState("");
  const [desc, setDesc] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (b.loading) return <Loading />;
  if (b.error) return <ErrorState error={b.error} />;
  const d = b.data;
  const s = d.statement;
  async function submit() {
    setErr(null);
    try {
      await api(`/inst/billing/events/${dispute.id}/dispute`, { body: { reason, description: desc }, idempotencyKey: true });
      setDispute(null);
      b.reload();
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <>
      <PageHeader title="Billing" subtitle="Subscription plus Qualified Opportunity fees under your contract's definition. Corrections are credits or reversals — history is never edited." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={`Total due · ${s.period}`} value={moneyFull(s.total_due)} tone="gold" />
        <Stat label="Included in plan" value={`${s.included_used} / ${s.included_opportunities}`} />
        <Stat label="Billable opportunities" value={s.billable_count} sub={moneyFull(s.billable_amount)} />
        <Stat label="Credits & reversals" value={moneyFull(s.adjustments)} />
      </div>
      {d.contract && (
        <Card title={`Contract · ${d.contract.plan} plan`} className="mb-4">
          <KV items={[["Subscription", moneyFull(d.contract.subscription_fee)], ["Included opportunities / month", d.contract.included_opportunities], ["Price per Qualified Opportunity", moneyFull(d.contract.opportunity_price)], ["Duplicate window", `${d.contract.duplicate_window_days} days`], ["Dispute window", `${d.contract.dispute_window_days} days`], ["Minimum match for billing", d.contract.qualified_definition.min_match_score]]} />
        </Card>
      )}
      <Table head={["Date", "Opportunity", "Kind", "Status", "Amount", ""]}>
        {d.events.map((e: any) => (
          <tr key={e.id}>
            <Td>{date(e.created_at)}</Td>
            <Td className="num">{e.reference || "—"}</Td>
            <Td>{e.kind.replace(/_/g, " ").toLowerCase()}</Td>
            <Td><StateBadge state={e.status === "BILLABLE" ? "ACTIVE" : e.status} label={e.status.replace(/_/g, " ").toLowerCase()} />{e.dispute && <span className="ml-1 text-[12px] text-muted">dispute {e.dispute.state.toLowerCase()}{e.dispute.decision ? `: ${e.dispute.decision.toLowerCase().replace(/_/g, " ")}` : ""}</span>}</Td>
            <Td className="num">{moneyFull(e.amount)}</Td>
            <Td>{d.can_dispute && !e.dispute && ["BILLABLE", "INCLUDED_IN_PLAN"].includes(e.status) && <Button size="sm" variant="ghost" onClick={() => setDispute(e)}>Dispute</Button>}</Td>
          </tr>
        ))}
      </Table>
      <Modal open={!!dispute} onClose={() => setDispute(null)} title={`Dispute ${dispute?.reference || ""}`} footer={<><Button variant="secondary" onClick={() => setDispute(null)}>Cancel</Button><Button onClick={submit} disabled={!reason || desc.length < 10}>Submit dispute</Button></>}>
        <div className="space-y-3">
          <Field label="Reason"><Select value={reason} onChange={(e) => setReason(e.target.value)} options={[["", "Choose…"], ...Object.entries(d.dispute_reasons) as [string, string][]]} /></Field>
          <Field label="Evidence / description" hint="WEZA Commercial reviews disputes within 10 business days."><Textarea rows={4} value={desc} onChange={(e) => setDesc(e.target.value)} /></Field>
          {err && <Banner tone="danger">{err}</Banner>}
        </div>
      </Modal>
    </>
  );
}
