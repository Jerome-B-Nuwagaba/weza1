"use client";

import { Building2, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { ActionError } from "@/components/ActionError";
import { useMe } from "@/components/StaffShell";
import { Badge, Button, Card, ErrorState, Field, Input, Loading, Modal, PageHeader, Select, StateBadge, Stat, Table, Td, Textarea } from "@/components/ui";

const TYPES = ["Commercial Bank", "Credit Institution", "Microfinance Deposit-taking Institution", "SACCO",
  "Tier 4 Microfinance", "Fintech Lender", "Other"];
const REGULATORS = ["Bank of Uganda", "Uganda Microfinance Regulatory Authority", "Other"];
const FILTERS: [string, string][] = [["", "All"], ["DRAFT", "Draft"], ["ACTIVE", "Active"], ["PAUSED", "Paused"],
  ["SUSPENDED", "Suspended"], ["REJECTED", "Rejected"]];

/** The Weza Staff list: every institution, its status, and whether it is ready to trade. */
export default function StaffInstitutions() {
  const { can } = useMe();
  const router = useRouter();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const r = useApi<any>(`/staff/institutions${status ? `?status=${status}` : ""}`);

  if (r.loading) return <Loading rows={6} />;
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  const all = r.data.institutions as any[];
  const counts = r.data.counts as Record<string, number>;
  const rows = q ? all.filter((i) => `${i.display_name} ${i.legal_name}`.toLowerCase().includes(q.toLowerCase())) : all;
  const draft = all.filter((i) => i.status === "DRAFT");
  const live = all.filter((i) => i.status === "ACTIVE");
  const notReady = all.filter((i) => i.status !== "ACTIVE" && !i.ready && i.status !== "REJECTED");

  return (
    <>
      <PageHeader
        eyebrow="Weza Staff"
        title="Institutions"
        subtitle="Bring an institution into the marketplace: create it, give it an administrator, and activate it once it is ready to trade."
        actions={can("admin.institution_onboard") ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New institution</Button> : undefined}
      />
      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Institutions" value={all.length} />
        <Stat label="In draft" value={draft.length} sub="not trading yet" />
        <Stat label="Trading" value={live.length} tone="gold" />
        <Stat label="Awaiting setup" value={notReady.length} sub="not ready to activate" />
      </div>
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px] flex-1">
            <Field label="Search"><Input placeholder="Name or legal name" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
          </div>
          <div className="w-[200px]">
            <Field label="Status">
              <Select value={status} onChange={(e) => setStatus(e.target.value)} options={FILTERS} />
            </Field>
          </div>
        </div>
      </Card>
      <Table
        head={["Institution", "Type", "Status", "Readiness", "Primary contact", "Created"]}
        empty={rows.length === 0}
      >
        {rows.map((i) => (
          <tr key={i.id}>
            <Td>
              <Link href={`/staff/institutions/${i.id}`} className="font-medium text-blue-800 hover:underline">{i.display_name}</Link>
              <div className="text-[12px] text-muted">{i.legal_name}</div>
            </Td>
            <Td>{i.type}</Td>
            <Td><StateBadge state={i.status} /></Td>
            <Td>
              {i.status === "ACTIVE" ? <Badge tone="success">Trading</Badge>
                : i.ready ? <Badge tone="success">Ready to activate</Badge>
                : <Badge tone="warning">{i.missing.length} check{i.missing.length === 1 ? "" : "s"} left</Badge>}
            </Td>
            <Td className="text-[13px]">{i.primary_contact ? `${i.primary_contact.name} · ${i.primary_contact.email}` : <span className="text-muted">Not set</span>}</Td>
            <Td>{date(i.created_at)}</Td>
          </tr>
        ))}
      </Table>
      {Object.keys(counts).length > 0 && (
        <p className="mt-3 text-[13px] text-muted">
          {Object.entries(counts).map(([k, v]) => `${v} ${k.toLowerCase().replace(/_/g, " ")}`).join(" · ")}
        </p>
      )}
      <CreateInstitution open={creating} onClose={() => setCreating(false)} onCreated={(id) => router.push(`/staff/institutions/${id}`)} />
    </>
  );
}

/** Create an institution in Draft. It trades nothing until it is activated. */
function CreateInstitution({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const [f, setF] = useState<any>({ legal_name: "", display_name: "", institution_type: "", licence_no: "", regulator: "", website: "", description: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [pending, setPending] = useState(false);
  const set = (k: string, v: string) => setF((p: any) => ({ ...p, [k]: v }));

  async function submit() {
    setPending(true);
    setErr(null);
    try {
      const created = await api<any>("/staff/institutions", { method: "POST", body: f });
      setF({ legal_name: "", display_name: "", institution_type: "", licence_no: "", regulator: "", website: "", description: "" });
      onCreated(created.id);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      wide
      title="New institution"
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button pending={pending} disabled={f.legal_name.trim().length < 2 || !f.institution_type} onClick={submit}>Create in draft</Button>
        </>
      }
    >
      <div className="space-y-4">
        <ActionError error={err} />
        <p className="text-[13px] text-muted">
          The institution starts in Draft. It receives nothing until you activate it, and activation needs an
          administrator, a product, a mandate and routing — its own team sets those up.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Legal name" required><Input value={f.legal_name} onChange={(e) => set("legal_name", e.target.value)} placeholder="Flow Bank Limited" /></Field>
          <Field label="Trading name" hint="What customers will see"><Input value={f.display_name} onChange={(e) => set("display_name", e.target.value)} placeholder="Flow Bank" /></Field>
          <Field label="Institution type" required>
            <Select value={f.institution_type} onChange={(e) => set("institution_type", e.target.value)} options={[["", "Choose…"], ...TYPES]} />
          </Field>
          <Field label="Regulator">
            <Select value={f.regulator} onChange={(e) => set("regulator", e.target.value)} options={[["", "Choose…"], ...REGULATORS]} />
          </Field>
          <Field label="Licence number"><Input value={f.licence_no} onChange={(e) => set("licence_no", e.target.value)} placeholder="BOU/CB/0001" /></Field>
          <Field label="Website"><Input value={f.website} onChange={(e) => set("website", e.target.value)} placeholder="https://" /></Field>
        </div>
        <Field label="Description"><Textarea rows={2} value={f.description} onChange={(e) => set("description", e.target.value)} placeholder="What this institution does." /></Field>
      </div>
    </Modal>
  );
}
