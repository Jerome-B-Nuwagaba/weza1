"use client";

import { CheckCircle2, Circle } from "lucide-react";
import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, Select, StateBadge, Table, Td, Textarea } from "@/components/ui";

export default function InstitutionAdmin({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useMe();
  const r = useApi<any>(`/admin/institutions/${id}`);
  const [verify, setVerify] = useState<boolean | null>(null);
  const [status, setStatus] = useState<string>("");
  const [target, setTarget] = useState<{ kind: string; id: string; to: string } | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function run(fn: () => Promise<any>, done: () => void) {
    setErr(null);
    try {
      const x = await fn();
      if (x?.legal_name) r.setData(x);
      else r.reload();
      done();
      setReason("");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const d = r.data;
  const pending = ["SUBMITTED", "UNDER_VERIFICATION"].includes(d.status);
  return (
    <>
      <PageHeader eyebrow="Institution" title={d.display_name} subtitle={`${d.legal_name} · ${d.type}`} actions={<>
        <StateBadge state={d.status} />
        {pending && can("admin.verify_institution") && <><Button onClick={() => setVerify(true)}>Approve</Button><Button variant="secondary" onClick={() => setVerify(false)}>Reject</Button></>}
        {!pending && can("admin.network_control") && d.allowed_transitions.length > 0 && <Button variant="secondary" onClick={() => setStatus(d.allowed_transitions[0])}>Change status…</Button>}
      </>} />
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      {pending && <Banner tone="gold" title="HUMAN_VERIFY_INSTITUTION" className="mb-4">Check the licence with the regulator and confirm the authorised representative before approving. Approval provisions the workspace; the institution still has to configure and activate.</Banner>}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Registration">
          <KV items={[["Licence", d.licence_no], ["Regulator", d.regulator], ["Terms accepted", `v${d.terms_version}`], ["Verified by", d.verified_by || "—"], ["Verified", date(d.verified_at)], ["Users", d.users]]} />
          {d.status_reason && <p className="mt-2 text-[13px] text-muted">Status note: {d.status_reason}</p>}
        </Card>
        <Card title="Contacts">
          <ul className="space-y-2 text-[14px]">{d.contacts.map((c: any, i: number) => <li key={i}><b>{c.kind.toLowerCase()}</b>: {c.name} · {c.email}{c.phone && ` · ${c.phone}`}</li>)}</ul>
        </Card>
        <Card title="Activation readiness">
          <ul className="space-y-1.5 text-[14px]">{d.checklist.items.map((i: any) => <li key={i.key} className="flex items-center gap-2">{i.done ? <CheckCircle2 className="h-4 w-4 text-success" /> : <Circle className="h-4 w-4 text-muted" />}{i.label}</li>)}</ul>
        </Card>
        <Card title="Supply">
          <Table head={["Item", "Status", ""]}>
            {d.products.map((p: any) => <tr key={p.id}><Td>Product · {p.name}</Td><Td><StateBadge state={p.status} /></Td><Td>{can("admin.network_control") && ["ACTIVE", "PAUSED"].includes(p.status) && <Button size="sm" variant="ghost" onClick={() => setTarget({ kind: "products", id: p.id, to: p.status === "ACTIVE" ? "PAUSED" : "ACTIVE" })}>{p.status === "ACTIVE" ? "Pause" : "Resume"}</Button>}</Td></tr>)}
            {d.appetites.map((a: any) => <tr key={a.id}><Td>Appetite · {a.name}</Td><Td><StateBadge state={a.status} /> <StateBadge state={a.capacity} label={`cap ${a.capacity.toLowerCase()}`} /></Td><Td>{can("admin.network_control") && ["ACTIVE", "PAUSED"].includes(a.status) && <Button size="sm" variant="ghost" onClick={() => setTarget({ kind: "appetites", id: a.id, to: a.status === "ACTIVE" ? "PAUSED" : "ACTIVE" })}>{a.status === "ACTIVE" ? "Pause" : "Resume"}</Button>}</Td></tr>)}
          </Table>
        </Card>
      </div>
      <Modal open={verify !== null} onClose={() => setVerify(null)} title={verify ? "Approve institution" : "Reject application"} footer={<Button variant={verify ? "primary" : "danger"} disabled={reason.length < 3} onClick={() => run(() => api(`/admin/institutions/${id}/verify`, { body: { approve: verify, reason } }), () => setVerify(null))}>{verify ? "Approve" : "Reject"}</Button>}>
        <Field label="Reason / evidence checked" required><Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
      <Modal open={!!status} onClose={() => setStatus("")} title="Change institution status" footer={<Button variant="danger" disabled={reason.length < 3} onClick={() => run(() => api(`/admin/institutions/${id}/status`, { body: { status, reason } }), () => setStatus(""))}>Apply</Button>}>
        <div className="space-y-3">
          <Field label="New status"><Select value={status} onChange={(e) => setStatus(e.target.value)} options={d.allowed_transitions} /></Field>
          <Field label="Reason (audited)" required><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
          <p className="text-[13px] text-muted">Pausing or suspending removes this institution from customers' options immediately and re-clears the market. Other participants are unaffected.</p>
        </div>
      </Modal>
      <Modal open={!!target} onClose={() => setTarget(null)} title={`${target?.to === "PAUSED" ? "Pause" : "Resume"} ${target?.kind === "products" ? "product" : "appetite"}`} footer={<Button disabled={reason.length < 3} onClick={() => run(() => api(`/admin/${target!.kind}/${target!.id}/status`, { body: { status: target!.to, reason } }), () => setTarget(null))}>Apply</Button>}>
        <Field label="Reason (audited)" required><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </>
  );
}
