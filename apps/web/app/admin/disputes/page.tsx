"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime, moneyFull } from "@/lib/format";
import { ActionError } from "@/components/ActionError";
import { useMe } from "@/components/StaffShell";
import { Button, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Select, StateBadge, Textarea } from "@/components/ui";

export default function Disputes() {
  const { can } = useMe();
  const r = useApi<any>("/admin/disputes");
  const [mv, setMv] = useState<{ d: any; state: string } | null>(null);
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  async function save() {
    setErr(null);
    try {
      r.setData(await api(`/admin/disputes/${mv!.d.id}/move`, { body: { state: mv!.state, decision: decision || null, note } }));
      setMv(null);
      setNote("");
      setDecision("");
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <>
      <PageHeader title="Billing disputes" subtitle="OPEN → UNDER REVIEW ⇄ FURTHER INVESTIGATION → DECIDED → CLOSED. Reversals and credits are new events; history is never edited." />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : r.data.disputes.length === 0 ? <EmptyState title="No disputes" /> : (
        <div className="space-y-3">
          {r.data.disputes.map((d: any) => (
            <div key={d.id} className="rounded-xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div><span className="font-medium">{d.institution}</span> <span className="text-muted">· {d.reference} · {moneyFull(d.amount)} · {d.reason_label}</span></div>
                <div className="flex items-center gap-2"><StateBadge state={d.state === "DECIDED" || d.state === "CLOSED" ? "DONE" : "OPEN"} label={d.state.replace(/_/g, " ").toLowerCase()} />{d.decision && <StateBadge state={d.decision === "CHARGE_VALID" ? "ACTIVE" : "REVERSED"} label={d.decision.replace(/_/g, " ").toLowerCase()} />}</div>
              </div>
              <p className="mt-1 text-[14px]">{d.description}</p>
              <p className="text-[12px] text-muted">Opportunity state: {d.opportunity_state?.toLowerCase().replace(/_/g, " ")} · opened {dateTime(d.created_at)}</p>
              {can("admin.dispute_decide") && d.allowed.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{d.allowed.map((s: string) => <Button key={s} size="sm" variant={s === "DECIDED" ? "primary" : "secondary"} onClick={() => setMv({ d, state: s })}>{s === "DECIDED" ? "Decide…" : s.replace(/_/g, " ").toLowerCase()}</Button>)}</div>}
            </div>
          ))}
        </div>
      )}
      <Modal open={!!mv} onClose={() => setMv(null)} title={mv?.state === "DECIDED" ? "Decide dispute" : `Move to ${mv?.state.toLowerCase().replace(/_/g, " ")}`} footer={<Button onClick={save} disabled={mv?.state === "DECIDED" && !decision}>Confirm</Button>}>
        <div className="space-y-3">
          {mv?.state === "DECIDED" && <Field label="Decision"><Select value={decision} onChange={(e) => setDecision(e.target.value)} options={[["", "Choose…"], ["CHARGE_VALID", "Charge valid"], ["CHARGE_REVERSED", "Charge reversed (reversal event)"], ["OPPORTUNITY_REPLACED", "Opportunity replaced (credit event)"]]} /></Field>}
          <Field label="Note"><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <ActionError error={err} />
        </div>
      </Modal>
    </>
  );
}
