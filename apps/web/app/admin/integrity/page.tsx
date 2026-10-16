"use client";

import { useState } from "react";
import { ActionError } from "@/components/ActionError";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, StateBadge, Textarea } from "@/components/ui";

export default function Integrity() {
  const r = useApi<any>("/admin/integrity");
  const [dec, setDec] = useState<{ id: string; result: string } | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const { can } = useMe();
  const open = (id: string, result: string) => { setErr(null); setNote(""); setDec({ id, result }); };
  async function save() {
    setErr(null);
    setNotice(null);
    try {
      r.setData(await api(`/admin/integrity/${dec!.id}/decide`, { body: { result: dec!.result, note } }));
      setDec(null);
      setNote("");
    } catch (e) {
      const x = e as ApiError;
      if (x.status !== 409) return setErr(x);
      // A decided case is final (one-time decision); show what was decided instead.
      setDec(null);
      setNote("");
      setNotice("This case had already been decided. The list has been refreshed.");
      r.reload();
    }
  }
  return (
    <>
      <PageHeader title="Marketplace integrity" subtitle={r.data?.note || "Duplicate, velocity, device and synthetic-pattern signals."} />
      {notice && <Banner tone="info" className="mb-4">{notice}</Banner>}
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : r.data.cases.length === 0 ? <EmptyState title="No integrity cases" /> : (
        <div className="space-y-3">
          {r.data.cases.map((c: any) => (
            <div key={c.id} className="rounded-xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2"><StateBadge state={c.risk_state} /><span className="font-medium">{c.subject_type} {c.context?.reference || c.subject_id.slice(0, 8)}</span><span className="text-[12px] text-muted">score {c.score} · {dateTime(c.created_at)}</span></div>
                {c.state === "OPEN" ? (can("admin.review") ? (
                  <div className="flex gap-2"><Button size="sm" onClick={() => open(c.id, "ALLOW")}>Allow & release</Button><Button size="sm" variant="danger" onClick={() => open(c.id, "BLOCK")}>Block</Button></div>
                ) : <Badge tone="warning">awaiting decision</Badge>) : <Badge tone={c.result === "ALLOW" ? "success" : "danger"}>{c.result?.toLowerCase()}</Badge>}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">{c.signals.map((s: any, i: number) => <Badge key={i} tone="warning">{s.kind.replace(/_/g, " ").toLowerCase()} (+{s.weight})</Badge>)}</div>
              {c.note && <p className="mt-2 text-[13px] text-muted">“{c.note}”</p>}
            </div>
          ))}
        </div>
      )}
      <Modal open={!!dec} onClose={() => setDec(null)} title={dec?.result === "ALLOW" ? "Allow — route the held opportunity" : "Block — close and block the customer"} footer={<Button variant={dec?.result === "ALLOW" ? "primary" : "danger"} onClick={save} disabled={note.length < 3}>Confirm</Button>}>
        <Field label="Decision note (audited)" required><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <ActionError error={err} className="mt-3" />
      </Modal>
    </>
  );
}
