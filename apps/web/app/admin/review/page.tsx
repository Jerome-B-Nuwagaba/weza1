"use client";

import Link from "next/link";
import { useState } from "react";
import { ActionError } from "@/components/ActionError";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { Badge, Button, EmptyState, ErrorState, Field, Loading, Modal, PageHeader, Tabs, Textarea } from "@/components/ui";

const ACTIONS: Record<string, [string, string][]> = {
  DUPLICATE_HOLD: [["release", "Release & route"], ["close", "Close as duplicate"]],
  DEAD_LETTER: [["replay", "Replay event"], ["dismiss", "Dismiss"]],
  default: [["resolve", "Mark resolved"], ["dismiss", "Dismiss"]],
};

export default function Review() {
  const [status, setStatus] = useState("OPEN");
  const r = useApi<any>(`/admin/review?status=${status}`, [status]);
  const [act, setAct] = useState<{ item: any; action: string } | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  async function save() {
    setErr(null);
    try {
      r.setData(await api(`/admin/review/${act!.item.id}/resolve`, { body: { action: act!.action, note } }));
      setAct(null);
      setNote("");
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  const link = (i: any) => i.object_type === "institution" ? `/admin/institutions/${i.object_id}` : i.object_type === "integrity_case" ? "/admin/integrity" : i.object_type === "opportunity" ? `/admin/graph?q=${i.object_id}` : i.object_type === "customer" ? null : null;
  return (
    <>
      <PageHeader title="Human Control Centre" subtitle="Where WEZA stops and asks a person: low-confidence AI, conflicts, integrity, routing failures, duplicates, failed events and workflows." />
      <Tabs tabs={[["OPEN", "Open"], ["RESOLVED", "Resolved"]]} value={status} onChange={setStatus} />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : r.data.items.length === 0 ? <EmptyState title="Nothing waiting for a human" /> : (
        <div className="space-y-2">
          {r.data.items.map((i: any) => (
            <div key={i.id} className="flex flex-col gap-2 rounded-xl border border-line bg-surface p-4 md:flex-row md:items-center md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2"><Badge tone={i.severity === "HIGH" ? "danger" : "warning"}>{i.kind.replace(/_/g, " ").toLowerCase()}</Badge><span className="font-medium">{i.title}</span></div>
                <div className="mt-0.5 text-[12px] text-muted">{dateTime(i.created_at)}{i.due_at && ` · due ${dateTime(i.due_at)}`}{Object.keys(i.detail || {}).length > 0 && ` · ${JSON.stringify(i.detail).slice(0, 140)}`}{i.resolution && ` · ${i.resolution}`}</div>
              </div>
              {status === "OPEN" && (
                <div className="flex flex-wrap gap-2">
                  {link(i) && <Button size="sm" variant="secondary" href={link(i)!}>Open</Button>}
                  {i.kind !== "INSTITUTION_VERIFICATION" && i.kind !== "INTEGRITY" && (ACTIONS[i.kind] || ACTIONS.default).map(([a, l]) => <Button key={a} size="sm" variant={a === "dismiss" ? "ghost" : "primary"} onClick={() => setAct({ item: i, action: a })}>{l}</Button>)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <Modal open={!!act} onClose={() => setAct(null)} title={act ? `${act.action} — ${act.item.title}` : ""} footer={<Button onClick={save} disabled={note.length < 3}>Confirm</Button>}>
        <Field label="Note (audited)" required><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <ActionError error={err} className="mt-3" />
      </Modal>
    </>
  );
}
