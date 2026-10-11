"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, StateBadge, Textarea } from "@/components/ui";

export default function Insights() {
  const { can } = useMe();
  const r = useApi<any>("/inst/intelligence/insights");
  const [decide, setDecide] = useState<{ id: string; status: string } | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    try {
      r.setData(await api(`/inst/intelligence/insights/${decide!.id}`, { body: { status: decide!.status, note } }));
      setDecide(null);
      setNote("");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <>
      <PageHeader title="Insights" subtitle="WEZA compares your configured appetite with the outcomes you report. It recommends a review — it never changes your rules." />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} /> : r.data.insights.length === 0 ? <EmptyState title="No insights yet">Insights appear once enough outcomes have been reported.</EmptyState> : (
        <div className="space-y-4">
          {r.data.insights.map((i: any) => (
            <Card key={i.id} title={i.title} subtitle={`${i.kind.replace(/_/g, " ").toLowerCase()} · ${date(i.created_at)}`} action={<StateBadge state={i.status === "OPEN" ? "OPEN" : "DONE"} label={i.status.toLowerCase()} />}>
              <p className="text-[14px]">{i.narrative}</p>
              {i.decision_note && <p className="mt-2 text-[13px] text-muted">Decision: “{i.decision_note}”</p>}
              {i.status === "OPEN" && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {i.appetite_id && <Button size="sm" href={`/institution/appetite/${i.appetite_id}`}>Open appetite & simulate</Button>}
                  {can("appetite.edit") && <Button size="sm" variant="secondary" onClick={() => setDecide({ id: i.id, status: "ACTIONED" })}>Mark actioned</Button>}
                  {can("appetite.edit") && <Button size="sm" variant="ghost" onClick={() => setDecide({ id: i.id, status: "DISMISSED" })}>Dismiss</Button>}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
      <Modal open={!!decide} onClose={() => setDecide(null)} title={decide?.status === "DISMISSED" ? "Dismiss insight" : "Mark actioned"} footer={<><Button variant="secondary" onClick={() => setDecide(null)}>Cancel</Button><Button onClick={save} disabled={note.length < 3}>Save</Button></>}>
        <Field label="Reason (recorded in audit)" required><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
      </Modal>
    </>
  );
}
