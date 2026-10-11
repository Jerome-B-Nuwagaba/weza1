"use client";

import { ArrowLeft, FileText, Lock } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime, money, moneyFull, STATE_LABEL } from "@/lib/format";
import { FreshnessBadge, PriorityBadge, TargetBadge } from "@/components/opportunity";
import { Badge, Banner, Bar, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, ReasonChips, ScoreRing, Select, StateBadge, Textarea, useToast } from "@/components/ui";

const COMPONENTS: [string, string][] = [["product_fit", "Product fit"], ["appetite_fit", "Appetite fit"], ["preference_fit", "Preference fit"], ["readiness", "Readiness"], ["capacity_fit", "Capacity"]];
const FIELD_LABEL: Record<string, string> = { full_name: "Name", phone: "Phone", email: "Email", contact_channel: "Preferred contact", contact_window: "Contact window", nin: "NIN", business_name: "Business name", business_registered: "Business registered", employer: "Employer", employment_type: "Employment type", farm_activity: "Farming activity", monthly_turnover: "Monthly turnover", monthly_income: "Monthly income", annual_income: "Annual farm income", monthly_repayments: "Existing monthly repayments" };

export default function Opportunity360({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const o = useApi<any>(`/inst/opportunities/${id}`);
  const { toast, node } = useToast();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [assign, setAssign] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function status(state: string) {
    setBusy(true);
    setErr(null);
    try {
      o.setData(await api(`/inst/opportunities/${id}/status`, { body: { state }, idempotencyKey: true }));
      toast(`Marked ${STATE_LABEL[state].toLowerCase()}`);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  if (o.loading) return <Loading rows={6} />;
  if (o.error) return <ErrorState error={o.error} onRetry={o.reload} />;
  const d = o.data;
  const snap = d.snapshot || {};
  const match = snap.match || {};
  const cust = d.customer;
  const closed = ["REPORTED_DISBURSED", "REPORTED_DECLINED", "WITHDRAWN", "CLOSED", "EXPIRED", "REMATCH_ELIGIBLE"].includes(d.state);

  return (
    <div className="space-y-5">
      {node}
      <Link href="/institution/feed" className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink"><ArrowLeft className="h-4 w-4" /> Feed</Link>
      <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-5 md:flex-row md:items-center">
        <ScoreRing score={d.match_score} size={64} />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{d.reference}</h1>
            <StateBadge state={d.state} label={STATE_LABEL[d.state]} />
            <PriorityBadge p={d.priority} />
            <FreshnessBadge f={d.freshness} />
            <TargetBadge o={d} />
            {d.is_demo && <Badge tone="muted">Demo data</Badge>}
          </div>
          <div className="mt-1 text-[15px]"><span className="num font-semibold">{moneyFull(d.amount)}</span> · {d.need} · {d.product}</div>
          <div className="text-[13px] text-muted">Owner: {d.owner || "Unassigned"} · Qualified {dateTime(d.qualified_at)} · Quality score {d.quality_score}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {d.can_assign && <Button variant="secondary" onClick={() => setAssign(true)}>{d.owner ? "Reassign" : "Assign"}</Button>}
          {d.can_update && !closed && !d.integrity_hold && (
            <>
              {["ROUTED", "RECEIVED", "ASSIGNED"].includes(d.state) && <Button pending={busy} onClick={() => status("CONTACTED")}>Mark contacted</Button>}
              {d.state === "CONTACTED" && <Button pending={busy} onClick={() => status("PROCEEDING")}>Customer proceeding</Button>}
              {d.state === "PROCEEDING" && <Button pending={busy} onClick={() => status("SUBMITTED_TO_INSTITUTION")}>Submitted internally</Button>}
            </>
          )}
        </div>
      </div>
      {err && <Banner tone="danger">{err}</Banner>}
      {d.integrity_hold && <Banner tone="warning" title="On hold">WEZA is completing routine checks. Customer details are not shared until the hold is released.</Banner>}

      {d.can_update && !closed && !d.integrity_hold && (
        <Card title="What happened with this customer?" subtitle="One tap. Your institution makes the credit decision — WEZA records what you report.">
          <div className="flex flex-wrap gap-2">
            {d.state !== "REPORTED_APPROVED" && <Button variant="secondary" onClick={() => setOutcome("REPORTED_APPROVED")}>Reported approved…</Button>}
            {d.state === "REPORTED_APPROVED" && <Button variant="gold" onClick={() => setOutcome("REPORTED_DISBURSED")}>Reported disbursed…</Button>}
            {d.state !== "REPORTED_APPROVED" && <Button variant="secondary" onClick={() => setOutcome("REPORTED_DECLINED")}>Declined…</Button>}
            <Button variant="ghost" onClick={() => setOutcome("WITHDRAWN")}>Customer withdrew</Button>
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Customer" subtitle={cust.restricted ? undefined : "Shared under the customer's consent. Marketplace verification only — complete your own KYC."}>
          {cust.restricted ? (
            <div className="flex gap-3 text-[14px] text-muted">
              <Lock className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                {{ consent_not_valid: "The customer has withdrawn consent, so WEZA no longer discloses their details. Information you already received stays under your own obligations.",
                  not_assigned: "Identifiable details are visible to the assigned officer, their manager, administrators and compliance.",
                  role_not_identifiable: "Your role sees opportunity intelligence, not customer identity.",
                  not_routed: "Details are released once WEZA checks are complete.",
                  weza_staff_use_vault_lookup: "WEZA staff use the audited support lookup." }[cust.restriction_reason as string] || "Not shared with you."}
              </div>
            </div>
          ) : (
            <>
              <KV items={Object.entries(cust.fields).map(([k, v]) => [FIELD_LABEL[k] || k, typeof v === "number" ? moneyFull(v as number) : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v).replace(/_/g, " ")])} />
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge tone="success">Phone verified</Badge>
                {cust.verification?.nin_provided ? <Badge tone="success">NIN provided</Badge> : <Badge tone="muted">NIN not provided</Badge>}
              </div>
              {cust.documents?.length > 0 && (
                <div className="mt-4">
                  <div className="mb-1 text-[13px] font-medium">Authorised documents</div>
                  {cust.documents.map((doc: any) => (
                    <button key={doc.id} onClick={async () => { const r: Response = await api(`/inst/opportunities/${id}/documents/${doc.id}`, { raw: true }); window.open(URL.createObjectURL(await r.blob()), "_blank"); }} className="flex items-center gap-2 py-1 text-[14px] text-blue-800 hover:underline"><FileText className="h-4 w-4" />{doc.doc_type.replace(/_/g, " ")}</button>
                  ))}
                </div>
              )}
            </>
          )}
        </Card>

        <Card title="Why this matched" subtitle={`Algorithm ${match.algorithm_version} · weights v${match.weights_version} · ruleset ${String(match.ruleset_hash || "").slice(0, 8)}`}>
          <ul className="mb-4 space-y-2">
            {COMPONENTS.map(([k, l]) => (
              <li key={k} className="grid grid-cols-[110px_1fr_40px] items-center gap-3 text-[13px]">
                <span className="text-muted">{l}</span><Bar value={(d.components || {})[k] || 0} tone={k === "appetite_fit" ? "gold" : "blue"} /><span className="num text-right">{((d.components || {})[k] ?? 0).toFixed(2)}</span>
              </li>
            ))}
          </ul>
          <ReasonChips matched={(match.explanation?.matched || []).map((x: any) => x.text)} near={(match.explanation?.near_miss || []).map((x: any) => `${x.text} (${x.observed})`)} missing={(match.explanation?.outstanding || []).map((x: any) => x.text)} />
          <p className="mt-3 text-[12px] text-muted">The match score reflects fit with your configured product and appetite at the time of qualification. It is not a probability of approval.</p>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Financial need">
          <KV items={[["Requested", moneyFull(Number(snap.need?.amount))], ["Purpose", snap.need?.purpose], ["Customer type", snap.need?.customer_type], ["Sector", snap.need?.sector?.replace(/_/g, " ")], ["District", d.district], ["Preferred tenor", snap.need?.tenor_months ? `${snap.need.tenor_months} months` : "—"], ["Product", `${snap.product_version?.name} v${snap.product_version?.version}`], ["Appetite version", snap.appetite_version ? `v${snap.appetite_version.version}` : "—"]]} />
        </Card>
        <Card title="Consent">
          <KV items={[["Status", <StateBadge key="s" state={d.consent.status} />], ["Version", d.consent.version], ["Granted", dateTime(d.consent.granted_at)], ["Withdrawn", d.consent.withdrawn_at ? dateTime(d.consent.withdrawn_at) : "—"]]} />
          <div className="mt-3 flex flex-wrap gap-1.5">{d.consent.categories.map((c: string) => <Badge key={c} tone="muted">{c.toLowerCase()}</Badge>)}</div>
        </Card>
      </div>

      <Card title="Activity">
        <ol className="space-y-2 border-l-2 border-line pl-4">
          {d.activity.map((a: any, i: number) => (
            <li key={i} className="text-[14px]"><span className="font-medium">{STATE_LABEL[a.kind] || a.kind.replace(/_/g, " ").toLowerCase()}</span> <span className="text-muted">· {a.actor} · {dateTime(a.at)}</span>{a.note && <div className="text-[13px] text-muted">{a.note}</div>}</li>
          ))}
          {d.outcomes.map((x: any, i: number) => (
            <li key={"o" + i} className="text-[14px]"><span className="font-medium">{STATE_LABEL[x.state]}</span> <span className="text-muted">· {x.label} · {dateTime(x.reported_at)}</span>{x.reason && <div className="text-[13px] text-muted">Reason: {x.reason}</div>}{x.disbursed_amount && <div className="text-[13px] text-muted">Disbursed {money(x.disbursed_amount)}</div>}</li>
          ))}
        </ol>
      </Card>

      <OutcomeModal open={!!outcome} state={outcome} onClose={() => setOutcome(null)} id={id} reasons={d.decline_reasons} amount={d.amount} onDone={(r: any) => { o.setData(r); setOutcome(null); toast("Outcome recorded"); }} />
      <AssignModal open={assign} onClose={() => setAssign(false)} id={id} members={d.members} onDone={(r: any) => { o.setData(r); setAssign(false); toast("Assigned"); }} />
    </div>
  );
}

function OutcomeModal({ open, state, onClose, id, reasons, amount, onDone }: any) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [amt, setAmt] = useState(String(amount || ""));
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const body: any = { state, reason_note: note || null };
      if (state === "REPORTED_DECLINED") body.reason_category = reason;
      if (state === "REPORTED_APPROVED") body.approved_amount = Number(amt);
      if (state === "REPORTED_DISBURSED") { body.disbursed_amount = Number(amt); body.disbursed_on = day; }
      onDone(await api(`/inst/opportunities/${id}/outcome`, { body, idempotencyKey: true }));
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title={STATE_LABEL[state] || "Outcome"} footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={busy} onClick={save} disabled={state === "REPORTED_DECLINED" && !reason}>Save</Button></>}>
      <div className="space-y-3">
        {state === "REPORTED_DECLINED" && <Field label="Reason" required><Select value={reason} onChange={(e) => setReason(e.target.value)} options={[["", "Choose…"], ...Object.entries(reasons || {}) as [string, string][]]} /></Field>}
        {(state === "REPORTED_APPROVED" || state === "REPORTED_DISBURSED") && <Field label={state === "REPORTED_APPROVED" ? "Approved amount (UGX)" : "Disbursed amount (UGX)"}><Input inputMode="numeric" value={amt} onChange={(e) => setAmt(e.target.value.replace(/[^\d]/g, ""))} /></Field>}
        {state === "REPORTED_DISBURSED" && <Field label="Disbursed on"><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>}
        <Field label="Note (optional)"><Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="text-[12px] text-muted">Recorded as institution-reported. Declines help WEZA show appetite insights; WEZA never changes your rules automatically.</p>
        {err && <Banner tone="danger">{err}</Banner>}
      </div>
    </Modal>
  );
}

function AssignModal({ open, onClose, id, members, onDone }: any) {
  const [user, setUser] = useState("");
  const [err, setErr] = useState<string | null>(null);
  async function save() {
    try {
      onDone(await api(`/inst/opportunities/${id}/assign`, { body: { user_id: user } }));
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Assign opportunity" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button onClick={save} disabled={!user}>Assign</Button></>}>
      <Field label="Officer"><Select value={user} onChange={(e) => setUser(e.target.value)} options={[["", "Choose…"], ...(members || []).map((m: any) => [m.id, `${m.name}${m.team ? ` · ${m.team}` : ""}`] as [string, string])]} /></Field>
      {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
    </Modal>
  );
}
