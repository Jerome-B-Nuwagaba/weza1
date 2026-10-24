"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, Card, ErrorState, Field, Input, Loading, Modal, PageHeader, Select, StateBadge, Table, Td } from "@/components/ui";

export default function Users() {
  const { can, me } = useMe();
  const u = useApi<any>("/inst/users");
  const [add, setAdd] = useState(false);
  const [team, setTeam] = useState(false);
  const [mfa, setMfa] = useState<any>(null);
  const [form, setForm] = useState<any>({ full_name: "", email: "", roles: ["OFFICER"], team_id: "", password: "" });
  const [teamName, setTeamName] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [roleEdit, setRoleEdit] = useState<{ id: string; name: string; roles: string[] } | null>(null);
  const [reset, setReset] = useState<{ id: string; name: string } | null>(null);
  const [newPw, setNewPw] = useState("");
  const [teamEdit, setTeamEdit] = useState<{ id: string; name: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(fn: () => Promise<any>, after?: () => void) {
    setErr(null);
    try {
      const r = await fn();
      if (r?.users) u.setData(r);
      else u.reload();
      after?.();
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  if (u.loading) return <Loading />;
  if (u.error) return <ErrorState error={u.error} />;
  const d = u.data;
  return (
    <>
      <PageHeader title="Users & roles" subtitle="Least privilege: officers see identifiable details only for opportunities assigned to them."
        actions={<>
          {!me.mfa_enrolled && <Button variant="secondary" onClick={async () => setMfa(await api("/auth/mfa/enrol", { method: "POST" }))}>Set up my MFA</Button>}
          {can("team.manage") && <Button variant="secondary" onClick={() => setTeam(true)}>New team</Button>}
          {can("users.manage") && <Button onClick={() => setAdd(true)}>Add user</Button>}
        </>} />
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      {notice && <Banner tone="success" className="mb-4">{notice}</Banner>}
      <Table head={["Name", "Roles", "Team", "MFA", "Status", ""]}>
        {d.users.map((x: any) => (
          <tr key={x.id}>
            <Td><div className="font-medium">{x.name}</div><div className="text-[12px] text-muted">{x.email}</div></Td>
            <Td><div className="flex flex-wrap gap-1">{x.roles.map((r: string) => <Badge key={r} tone="muted">{d.role_labels[r]}</Badge>)}</div></Td>
            <Td>{can("users.manage") ? <Select value={x.team_id || ""} onChange={(e) => run(() => api(`/inst/users/${x.id}`, { method: "PATCH", body: { team_id: e.target.value } }))} options={[["", "—"], ...d.teams.map((t: any) => [t.id, t.name])]} className="!h-9 !w-40 !text-[14px]" /> : x.team || "—"}</Td>
            <Td>{x.mfa_enrolled ? <Badge tone="success">On</Badge> : <Badge tone="muted">Off</Badge>}</Td>
            <Td><StateBadge state={x.status} /></Td>
            <Td>
              {can("users.manage") && (
                <div className="flex flex-wrap justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setRoleEdit({ id: x.id, name: x.name, roles: [...x.roles] })}>Roles</Button>
                  {x.id !== me.id && <Button size="sm" variant="ghost" onClick={() => { setNewPw(""); setReset({ id: x.id, name: x.name }); }}>Reset password</Button>}
                  {x.id !== me.id && <Button size="sm" variant="ghost" onClick={() => run(() => api(`/inst/users/${x.id}`, { method: "PATCH", body: { status: x.status === "ACTIVE" ? "DISABLED" : "ACTIVE" } }))}>{x.status === "ACTIVE" ? "Disable" : "Enable"}</Button>}
                </div>
              )}
            </Td>
          </tr>
        ))}
      </Table>
      {can("team.manage") && d.teams.length > 0 && (
        <Card title="Teams" subtitle="A team can be removed once it has no members, routing rules or open opportunities." className="mt-6">
          <ul className="divide-y divide-line">
            {d.teams.map((t: any) => (
              <li key={t.id} className="flex items-center justify-between gap-2 py-2 text-[14px]">
                <span>{t.name} <span className="text-muted">· {d.users.filter((x: any) => x.team_id === t.id).length} member(s)</span></span>
                <span className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setTeamEdit({ id: t.id, name: t.name })}>Rename</Button>
                  <Button size="sm" variant="ghost" onClick={() => run(() => api(`/inst/teams/${t.id}`, { method: "DELETE" }))}>Remove</Button>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card title="Roles" className="mt-6"><ul className="grid gap-2 text-[13.5px] md:grid-cols-2">{Object.entries(d.role_labels).map(([k, v]) => <li key={k}><b>{v as string}</b> — {ROLE_HELP[k]}</li>)}</ul></Card>

      <Modal open={add} onClose={() => setAdd(false)} title="Add user" footer={<><Button variant="secondary" onClick={() => setAdd(false)}>Cancel</Button><Button onClick={() => run(() => api("/inst/users", { body: { ...form, team_id: form.team_id || null } }), () => setAdd(false))}>Create</Button></>}>
        <div className="space-y-3">
          <Field label="Full name"><Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="At least 12 characters. Share securely; the user should enrol MFA."><Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Team"><Select value={form.team_id} onChange={(e) => setForm({ ...form, team_id: e.target.value })} options={[["", "—"], ...d.teams.map((t: any) => [t.id, t.name])]} /></Field>
          <Field label="Roles"><div className="flex flex-wrap gap-2">{d.roles.map((r: string) => <button key={r} type="button" onClick={() => setForm({ ...form, roles: form.roles.includes(r) ? form.roles.filter((x: string) => x !== r) : [...form.roles, r] })} className={`rounded-full border px-3 py-1 text-[13px] ${form.roles.includes(r) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{d.role_labels[r]}</button>)}</div></Field>
          {err && <Banner tone="danger">{err}</Banner>}
        </div>
      </Modal>
      <Modal open={team} onClose={() => setTeam(false)} title="New team" footer={<Button onClick={() => run(() => api("/inst/teams", { body: { name: teamName } }), () => setTeam(false))}>Create</Button>}>
        <Field label="Team name"><Input value={teamName} onChange={(e) => setTeamName(e.target.value)} /></Field>
      </Modal>
      <Modal open={!!roleEdit} onClose={() => setRoleEdit(null)} title={`Roles · ${roleEdit?.name || ""}`} footer={<><Button variant="secondary" onClick={() => setRoleEdit(null)}>Cancel</Button><Button disabled={!roleEdit?.roles.length} onClick={() => run(() => api(`/inst/users/${roleEdit!.id}`, { method: "PATCH", body: { roles: roleEdit!.roles } }), () => setRoleEdit(null))}>Save</Button></>}>
        <div className="flex flex-wrap gap-2">{d.roles.map((r: string) => <button key={r} type="button" onClick={() => roleEdit && setRoleEdit({ ...roleEdit, roles: roleEdit.roles.includes(r) ? roleEdit.roles.filter((x) => x !== r) : [...roleEdit.roles, r] })} className={`rounded-full border px-3 py-1 text-[13px] ${roleEdit?.roles.includes(r) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{d.role_labels[r]}</button>)}</div>
        <p className="mt-3 text-[12px] text-muted">Changes apply on the person&apos;s next request. Every change is audited.</p>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
      </Modal>
      <Modal open={!!reset} onClose={() => setReset(null)} title={`Reset password · ${reset?.name || ""}`} footer={<><Button variant="secondary" onClick={() => setReset(null)}>Cancel</Button><Button disabled={newPw.length < 12} onClick={() => run(() => api(`/inst/users/${reset!.id}/password`, { body: { new_password: newPw } }), () => { setNotice(`Password reset for ${reset!.name}. Their sessions were signed out — share the new password securely.`); setReset(null); })}>Reset</Button></>}>
        <Field label="New temporary password" hint="At least 12 characters. The person is signed out everywhere and should change it after signing in."><Input type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} /></Field>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
      </Modal>
      <Modal open={!!teamEdit} onClose={() => setTeamEdit(null)} title="Rename team" footer={<Button disabled={(teamEdit?.name.trim().length || 0) < 2} onClick={() => run(() => api(`/inst/teams/${teamEdit!.id}`, { method: "PATCH", body: { name: teamEdit!.name } }), () => setTeamEdit(null))}>Save</Button>}>
        <Field label="Team name"><Input value={teamEdit?.name || ""} onChange={(e) => teamEdit && setTeamEdit({ ...teamEdit, name: e.target.value })} /></Field>
      </Modal>
      <Modal open={!!mfa} onClose={() => setMfa(null)} title="Set up MFA" footer={<Button onClick={() => run(() => api("/auth/mfa/enrol/confirm", { body: { code } }), () => { setMfa(null); window.location.reload(); })}>Confirm</Button>}>
        <p className="text-[14px]">Add this secret to an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…), then enter the current code.</p>
        <code className="my-3 block break-all rounded bg-canvas p-3 text-[13px]">{mfa?.secret}</code>
        <Field label="6-digit code"><Input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} maxLength={6} /></Field>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
      </Modal>
    </>
  );
}

const ROLE_HELP: Record<string, string> = {
  INST_ADMIN: "users, settings, activation; approves products/appetite",
  EXECUTIVE: "strategic intelligence; approves appetite; no customer identity",
  BUSINESS: "products, mandates, simulations",
  CREDIT_RISK: "appetite, simulations, outcome patterns",
  MANAGER: "queues, assignment, service targets, team identity access",
  OFFICER: "assigned opportunities, contact, outcomes",
  COMPLIANCE: "consent and access logs",
  // The canonical WEZA V1 names. Each grants exactly the permissions of the working role above it.
  INSTITUTION_ADMIN: "users, settings, activation; approves products/appetite",
  INSTITUTION_MANAGER: "queues, assignment, service targets, team identity access",
  INSTITUTION_OFFICER: "assigned opportunities, contact, outcomes",
  COMPLIANCE_VIEWER: "consent and access logs",
};
