"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { moneyFull } from "@/lib/format";
import { ActionError } from "@/components/ActionError";
import { useMe } from "@/components/StaffShell";
import { Button, ErrorState, Field, Input, Loading, Modal, PageHeader, Stat, Table, Td } from "@/components/ui";

export default function Commercial() {
  const { can } = useMe();
  const r = useApi<any>("/admin/commercial");
  const [edit, setEdit] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  async function save() {
    try {
      r.setData(await api(`/admin/contracts/${edit.institution_id}`, { method: "PUT", body: edit.c }));
      setEdit(null);
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  const u = r.data.unit_economics;
  return (
    <>
      <PageHeader title="Commercial" subtitle={`Period ${r.data.period}. Subscription + Qualified Opportunity fees, contract-configurable per institution.`} />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Revenue this month" value={moneyFull(u.revenue_month)} tone="gold" />
        <Stat label="Qualified opportunities (all time)" value={u.qualified_opportunities_total} />
        <Stat label="Revenue per opportunity" value={u.revenue_per_opportunity !== null ? moneyFull(u.revenue_per_opportunity) : "—"} />
        <Stat label="AI cost per opportunity" value={u.ai_cost_usd_per_opportunity !== null ? `$${u.ai_cost_usd_per_opportunity}` : "—"} sub={`Total $${u.ai_cost_usd_total}`} />
      </div>
      <Table head={["Institution", "Plan", "Subscription", "Included used", "Billable", "Adjustments", "Total due", ""]} empty={r.data.institutions.length === 0}>
        {r.data.institutions.map((x: any) => (
          <tr key={x.institution_id}>
            <Td className="font-medium">{x.institution}</Td>
            <Td>{x.contract?.plan || "—"}</Td>
            <Td className="num">{moneyFull(x.statement.subscription_fee)}</Td>
            <Td className="num">{x.statement.included_used} / {x.statement.included_opportunities}</Td>
            <Td className="num">{x.statement.billable_count} · {moneyFull(x.statement.billable_amount)}</Td>
            <Td className="num">{moneyFull(x.statement.adjustments)}</Td>
            <Td className="num font-semibold">{moneyFull(x.statement.total_due)}</Td>
            <Td>{can("admin.commercial") && x.contract && <Button size="sm" variant="ghost" onClick={() => setEdit({ institution_id: x.institution_id, name: x.institution, c: { ...x.contract } })}>Edit contract</Button>}</Td>
          </tr>
        ))}
      </Table>
      <Modal open={!!edit} onClose={() => setEdit(null)} title={`Contract — ${edit?.name}`} footer={<Button onClick={save}>Save new contract version</Button>}>
        {edit && (
          <div className="grid grid-cols-2 gap-3">
            {[["plan", "Plan"], ["subscription_fee", "Subscription (UGX)"], ["included_opportunities", "Included / month"], ["opportunity_price", "Price per opportunity"], ["duplicate_window_days", "Duplicate window (days)"], ["dispute_window_days", "Dispute window (days)"], ["min_match_score", "Min match for billing"]].map(([k, l]) => (
              <Field key={k} label={l}><Input value={edit.c[k]} onChange={(e) => setEdit({ ...edit, c: { ...edit.c, [k]: k === "plan" ? e.target.value : Number(e.target.value) } })} /></Field>
            ))}
            <p className="col-span-2 text-[12px] text-muted">The current contract is end-dated and a new one starts today; past billing is unaffected.</p>
            <ActionError error={err} className="col-span-2" />
          </div>
        )}
      </Modal>
    </>
  );
}
