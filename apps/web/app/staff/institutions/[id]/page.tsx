"use client";

import { CheckCircle2, Circle, KeyRound, PauseCircle, PlayCircle, UserPlus } from "lucide-react";
import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { ActionError } from "@/components/ActionError";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, StateBadge, Table, Td, Textarea } from "@/components/ui";

/** The Weza Staff detail page: identity, the people and supply behind the institution, the activation
 *  checklist, and the two actions that change whether it trades. */
export default function StaffInstitution({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useMe();
  const r = useApi<any>(`/staff/institutions/${id}`);
  const [err, setErr] = useState<ApiError | null>(null);
  const [contact, setContact] = useState(false);
  const [admin, setAdmin] = useState(false);
  const [action, setAction] = useState<"activate" | "pause" | null>(null);

  async function run(fn: () => Promise<any>, done: () => void) {
    setErr(null);
    try {
      const x = await fn();
      if (x?.id) r.setData(x);
      else r.reload();
      done();
    } catch (e) {
      setErr(e as ApiError);
    }
  }

  if (r.loading) return <Loading rows={6} />;
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  const d = r.data;
  const rd = d.readiness;
  const active = d.status === "ACTIVE";
  const canActivate = can("admin.institution_activate");

  return (
    <>
      <PageHeader
        eyebrow="Weza Staff"
        title={d.display_name}
        subtitle={`${d.legal_name} · ${d.type}${d.licence_no ? ` · ${d.licence_no}` : ""}`}
        actions={
          <>
            <StateBadge state={d.status} />
            {canActivate && active && <Button variant="secondary" onClick={() => setAction("pause")}><PauseCircle className="h-4 w-4" /> Pause</Button>}
            {canActivate && !active && d.status !== "REJECTED" && d.status !== "CLOSED" && (
              <Button variant="gold" disabled={!rd.ready} onClick={() => setAction("activate")}><PlayCircle className="h-4 w-4" /> Activate</Button>
            )}
          </>
        }
      />
      <ActionError error={err} className="mb-4" />
      {active && <Banner tone="success" title="Trading on WEZA" className="mb-4">This institution receives opportunities matched to its active mandate. Pausing it takes it out of the market immediately.</Banner>}
      {!active && d.status !== "REJECTED" && d.status !== "CLOSED" && (
        <Banner tone={rd.ready ? "gold" : "info"} title={rd.ready ? "Ready to activate" : "Not ready yet"} className="mb-4">
          {rd.ready
            ? "Every condition holds. Activating makes this institution live and brings its approved mandate on."
            : "The institution's own team sets its products, mandate and routing up in its workspace. The checklist below names what is still missing."}
        </Banner>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Registration">
          <KV items={[
            ["Legal name", d.legal_name],
            ["Type", d.type],
            ["Regulator", d.regulator],
            ["Licence", d.licence_no || "—"],
            ["Created", date(d.created_at)],
            ["Live since", date(d.activation?.activated_at)],
            ["Verified by", d.activation?.verified_by || "—"],
          ]} />
          {d.status_reason && <p className="mt-2 text-[13px] text-muted">Status note: {d.status_reason}</p>}
        </Card>

        <Card
          title="Primary contact"
          subtitle="The person WEZA reaches first"
          action={can("admin.institution_onboard") ? <Button size="sm" variant="ghost" onClick={() => setContact(true)}>{d.primary_contact ? "Change" : "Set contact"}</Button> : undefined}
        >
          {d.primary_contact ? (
            <KV items={[
              ["Name", d.primary_contact.name],
              ["Email", d.primary_contact.email],
              ["Phone", d.primary_contact.phone || "—"],
              ["Title", d.primary_contact.title || "—"],
            ]} />
          ) : (
            <p className="text-[14px] text-muted">No primary contact yet. Record who WEZA should call first.</p>
          )}
        </Card>

        <Card
          title="Administrator"
          subtitle="The institution's own sign-in"
          action={can("admin.institution_onboard") && !d.people.some((p: any) => p.is_administrator)
            ? <Button size="sm" onClick={() => setAdmin(true)}><UserPlus className="h-4 w-4" /> Create</Button>
            : undefined}
        >
          {d.people.length === 0 ? (
            <p className="text-[14px] text-muted">No users yet. An institution cannot trade without an administrator.</p>
          ) : (
            <ul className="divide-y divide-line">
              {d.people.map((p: any) => (
                <li key={p.id} className="flex items-center justify-between gap-3 py-2.5">
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-medium text-ink">{p.full_name}</span>
                    <span className="block truncate text-[12.5px] text-muted">{p.email}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {p.is_administrator && <Badge tone="gold">Administrator</Badge>}
                    <StateBadge state={p.status} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Activation checklist" subtitle="All four must hold before the institution can trade">
          <ul className="divide-y divide-line">
            {rd.conditions.map((c: any) => (
              <li key={c.key} className="flex items-start justify-between gap-3 py-2.5">
                <span className="flex items-start gap-2.5 text-[14px]">
                  {c.done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-muted" />}
                  <span>
                    <span className={c.done ? "text-ink" : "font-medium text-ink"}>{c.label}</span>
                    <span className="mt-0.5 block text-[12.5px] text-muted">{c.detail}</span>
                  </span>
                </span>
              </li>
            ))}
          </ul>
          {!rd.ready && <p className="mt-3 text-[13px] text-muted">Next: {rd.next?.label}.</p>}
        </Card>

        <Card title="Supply" className="lg:col-span-2" subtitle="What the institution offers the market">
          <Table head={["Item", "Status", ""]} empty={d.products.length + d.appetites.length === 0}>
            {d.products.map((p: any) => (
              <tr key={p.id}><Td>Product · {p.name}</Td><Td><StateBadge state={p.status} /></Td><Td /></tr>
            ))}
            {d.appetites.map((a: any) => (
              <tr key={a.id}><Td>Mandate · {a.name}</Td><Td><StateBadge state={a.status} /></Td><Td /></tr>
            ))}
          </Table>
          <p className="mt-3 text-[13px] text-muted">
            The institution's own team manages products, mandates and routing in its workspace. A mandate approved
            while the institution is still in draft goes live the moment the institution is activated.
          </p>
        </Card>
      </div>

      <ContactModal open={contact} onClose={() => setContact(false)} institution={d}
        onSave={(body) => run(() => api(`/staff/institutions/${id}/contact`, { method: "PUT", body }), () => setContact(false))} />
      <AdministratorModal open={admin} onClose={() => setAdmin(false)} institutionId={id}
        onSave={(body) => run(() => api(`/staff/institutions/${id}/administrator`, { method: "POST", body }), () => setAdmin(false))} />
      <ActionModal kind={action} onClose={() => setAction(null)} ready={rd.ready}
        onConfirm={(reason) => run(() => api(`/staff/institutions/${id}/${action}`, { method: "POST", body: { reason } }), () => setAction(null))} />
    </>
  );
}

function ContactModal({ open, onClose, institution, onSave }: {
  open: boolean; onClose: () => void; institution: any; onSave: (body: any) => void;
}) {
  const c = institution.primary_contact;
  const [f, setF] = useState<any>({ name: "", email: "", phone: "", title: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const set = (k: string, v: string) => setF((p: any) => ({ ...p, [k]: v }));
  async function save() {
    setPending(true);
    setErr(null);
    try {
      await onSave(f);
      setF({ name: "", email: "", phone: "", title: "" });
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setPending(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title={c ? "Change the primary contact" : "Record the primary contact"}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={pending} disabled={f.name.trim().length < 2 || !f.email.trim()} onClick={save}>Save contact</Button></>}>
      <div className="space-y-4">
        <ActionError error={err} />
        <Field label="Name" required><Input value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Priya Head" /></Field>
        <Field label="Email" required><Input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} placeholder="priya@bank.demo" /></Field>
        <Field label="Phone"><Input value={f.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+256700000001" /></Field>
        <Field label="Title"><Input value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="Head of Credit" /></Field>
      </div>
    </Modal>
  );
}

function AdministratorModal({ open, onClose, institutionId, onSave }: {
  open: boolean; onClose: () => void; institutionId: string; onSave: (body: any) => void;
}) {
  const [f, setF] = useState<any>({ full_name: "", email: "", password: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const set = (k: string, v: string) => setF((p: any) => ({ ...p, [k]: v }));
  async function save() {
    setPending(true);
    setErr(null);
    try {
      await onSave(f);
      setF({ full_name: "", email: "", password: "" });
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setPending(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Create the institution administrator"
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={pending} disabled={f.full_name.trim().length < 2 || !f.email.trim() || f.password.length < 12} onClick={save}>Create administrator</Button></>}>
      <div className="space-y-4">
        <ActionError error={err} />
        <p className="text-[13px] text-muted">
          The administrator is a normal institution account: they sign in with the same login and MFA as any other
          institution user. Set an initial password and share it with them securely.
        </p>
        <Field label="Full name" required><Input value={f.full_name} onChange={(e) => set("full_name", e.target.value)} placeholder="Priya Head" /></Field>
        <Field label="Email" required><Input type="email" value={f.email} onChange={(e) => set("email", e.target.value)} placeholder="admin@bank.demo" /></Field>
        <Field label="Initial password" required hint="At least 12 characters.">
          <Input type="text" value={f.password} onChange={(e) => set("password", e.target.value)} placeholder="At least 12 characters" />
        </Field>
        <p className="flex items-start gap-2 text-[13px] text-muted">
          <KeyRound className="mt-0.5 h-4 w-4 shrink-0" />
          The administrator can add their own colleagues, and the institution's team builds its products, mandate
          and routing before you activate it.
        </p>
      </div>
    </Modal>
  );
}

function ActionModal({ kind, onClose, ready, onConfirm }: {
  kind: "activate" | "pause" | null; onClose: () => void; ready: boolean; onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const activating = kind === "activate";
  async function confirm() {
    setPending(true);
    setErr(null);
    try {
      await onConfirm(reason);
      setReason("");
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setPending(false);
    }
  }
  return (
    <Modal open={!!kind} onClose={onClose} title={activating ? "Activate this institution" : "Pause this institution"}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant={activating ? "gold" : "danger"} pending={pending} disabled={reason.trim().length < 3} onClick={confirm}>{activating ? "Activate" : "Pause"}</Button></>}>
      <div className="space-y-4">
        <ActionError error={err} />
        {activating ? (
          <p className="text-[14px]">
            This institution goes live: it starts receiving opportunities matched to its mandate, and any mandate
            approved while it was in draft goes live with it.
          </p>
        ) : (
          <p className="text-[14px]">
            This institution stops receiving opportunities immediately. Its live matches are withdrawn and the
            market is re-cleared. Pausing is audited and can be undone.
          </p>
        )}
        <Field label="Reason (audited)" required>
          <Textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)}
            placeholder={activating ? "Licence checked with the regulator." : "Licence renewal under review."} />
        </Field>
      </div>
    </Modal>
  );
}
