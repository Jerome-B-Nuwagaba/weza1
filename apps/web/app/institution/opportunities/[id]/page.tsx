"use client";

import { ArrowLeft, FileText, Lock } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime, money, moneyFull, STATE_LABEL } from "@/lib/format";
import { AwaitingBadge, FreshnessBadge, IdentityBadge, PriorityBadge, TargetBadge, TermsLine } from "@/components/opportunity";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Bar, Button, Card, cx, ErrorState, Field, Input, KV, Loading, Modal, ReasonChips, ScoreRing, Select, StateBadge, Textarea, useToast } from "@/components/ui";

const COMPONENTS: [string, string][] = [["product_fit", "Product fit"], ["appetite_fit", "Appetite fit"], ["preference_fit", "Preference fit"], ["readiness", "Readiness"], ["capacity_fit", "Capacity"]];
const FIELD_LABEL: Record<string, string> = { full_name: "Name", phone: "Phone", email: "Email", contact_channel: "Preferred contact", contact_window: "Contact window", nin: "NIN", business_name: "Business name", business_registered: "Business registered", employer: "Employer", employment_type: "Employment type", farm_activity: "Farming activity", monthly_turnover: "Monthly turnover", monthly_income: "Monthly income", annual_income: "Annual farm income", monthly_repayments: "Existing monthly repayments", payout_phone: "Number to receive the money", business_registration_number: "Business registration no.", trading_licence_number: "Trading licence no.", trading_licence_expiry: "Trading licence expires" };
// The statuses an institution officer records. WEZA records what the institution reports — it never decides.
const STATUS_ACTION: Record<string, { label: string; variant?: "secondary" | "gold" | "ghost" }> = {
  CONTACTED: { label: "Mark contacted" },
  INFORMATION_REQUESTED: { label: "More information requested…" },
  PROCEEDING: { label: "Customer proceeding" },
  SUBMITTED_TO_INSTITUTION: { label: "Send for institution review" },
};

export default function Opportunity360({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useMe();
  const o = useApi<any>(`/inst/opportunities/${id}`);
  const { toast, node } = useToast();
  const [outcome, setOutcome] = useState<string | null>(null);
  const [assign, setAssign] = useState(false);
  const [ask, setAsk] = useState(false);
  const [note, setNote] = useState("");
  const [noteBusy, setNoteBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function status(state: string) {
    setBusy(true);
    setErr(null);
    try {
      o.setData(await api(`/inst/opportunities/${id}/status`, { body: { state, note: note.trim() || null }, idempotencyKey: true }));
      setNote("");
      toast(`Marked ${STATE_LABEL[state].toLowerCase()}`);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveNote() {
    if (!note.trim()) return;
    setNoteBusy(true);
    setErr(null);
    try {
      o.setData(await api(`/inst/opportunities/${id}/note`, { body: { note: note.trim() } }));
      setNote("");
      toast("Note saved");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setNoteBusy(false);
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
      <Link href={me && me.permissions.includes("opportunity.update_status") ? "/institution/my-day" : "/institution/feed"} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-ink"><ArrowLeft className="h-4 w-4" /> {me && me.permissions.includes("opportunity.update_status") ? "My queue" : "Feed"}</Link>
      <div className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-5 md:flex-row md:items-center">
        <ScoreRing score={d.match_score} size={64} />
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{d.reference}</h1>
            <StateBadge state={d.state} label={STATE_LABEL[d.state]} />
            <PriorityBadge p={d.priority} />
            <FreshnessBadge f={d.freshness} />
            <TargetBadge o={d} />
            <AwaitingBadge o={d} />
            {d.is_demo && <Badge tone="muted">Demo data</Badge>}
          </div>
          <div className="mt-1 text-[15px]"><span className="num font-semibold">{moneyFull(d.amount)}</span> · {d.need} · {d.product}</div>
          <div className="text-[13px] text-muted">Owner: {d.owner || "Unassigned"} · Qualified {dateTime(d.qualified_at)} · Quality score {d.quality_score}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {d.can_assign && <Button variant="secondary" onClick={() => setAssign(true)}>{d.owner ? "Reassign" : "Assign"}</Button>}
        </div>
      </div>
      {err && <Banner tone="danger">{err}</Banner>}
      {d.integrity_hold && <Banner tone="warning" title="On hold">WEZA is completing routine checks. Customer details are not shared until the hold is released.</Banner>}

      <Card title="Next action" subtitle="Your institution makes the credit decision. WEZA records the status you report — it never approves, declines or sends funds.">
        <ol className="mb-4 flex flex-wrap items-center gap-1.5">
          {(d.status_ladder || []).map((s: any) => (
            <li key={s.state} className={cx(
              "rounded-full border px-2.5 py-1 text-[12px]",
              s.current ? "border-blue-300 bg-blue-50 font-medium text-blue-800"
                : s.reached ? "border-line bg-canvas text-ink" : "border-dashed border-line text-muted")}>
              {s.label}
            </li>
          ))}
        </ol>
        {d.can_update && !closed && !d.integrity_hold && (
          <>
            <div className="mb-3">
              <Field label="Internal note (optional)" hint="Kept inside your institution. The customer never sees it.">
                <Textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Called the customer; they will send the turnover statements on Monday." />
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              {(d.next_states || []).map((s: string) => (
                <Button key={s} pending={busy} variant={STATUS_ACTION[s]?.variant} onClick={() => status(s)}>
                  {STATUS_ACTION[s]?.label || STATE_LABEL[s]}
                </Button>
              ))}
              {d.state !== "INFORMATION_REQUESTED" && (
                <Button variant="secondary" pending={busy} onClick={() => status("INFORMATION_REQUESTED")}>More information requested</Button>
              )}
              {d.can_add_note && (
                <Button variant="ghost" pending={noteBusy} onClick={saveNote} disabled={!note.trim()}>Save note only</Button>
              )}
            </div>
          </>
        )}
      </Card>

      {d.can_update && !closed && !d.integrity_hold && (
        <Card title="What happened with this customer?" subtitle="One tap. Your institution makes the credit decision — WEZA records what you report.">
          <div className="flex flex-wrap gap-2">
            {d.state !== "REPORTED_APPROVED" && <Button variant="secondary" onClick={() => setOutcome("REPORTED_APPROVED")}>Reported approved…</Button>}
            {d.state === "REPORTED_APPROVED" && <Button variant="gold" onClick={() => setOutcome("REPORTED_DISBURSED")}>Reported disbursed…</Button>}
            {d.state !== "REPORTED_APPROVED" && <Button variant="secondary" onClick={() => setOutcome("REPORTED_DECLINED")}>Declined…</Button>}
            <Button variant="ghost" onClick={() => setOutcome("WITHDRAWN")}>Customer withdrew</Button>
          </div>
          <p className="mt-3 text-[12px] text-muted">Approved and disbursed are your institution&apos;s own outcomes, reported back to WEZA and to the customer. WEZA does not make a credit decision and never moves money.</p>
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
                <IdentityBadge status={cust.verification?.identity?.status} label={cust.verification?.identity?.label} />
              </div>
              {cust.verification?.identity?.checked_at && <p className="mt-1 text-[12px] text-muted">Checked {dateTime(cust.verification.identity.checked_at)}. {cust.verification.note}</p>}
              {cust.credit_report && <CreditReport r={cust.credit_report} />}
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

      <InfoRequestsCard d={d} id={id} ask={ask} setAsk={setAsk} onChange={(r: any, msg: string) => { o.setData(r); toast(msg); }} />

      <Card title="Internal notes and activity" subtitle="Your institution's record of this opportunity. The customer sees only the status, not your notes.">
        <ol className="space-y-2 border-l-2 border-line pl-4">
          {d.activity.map((a: any, i: number) => (
            <li key={i} className="text-[14px]"><span className="font-medium">{a.kind === "NOTE" ? "Internal note" : STATE_LABEL[a.kind] || a.kind.replace(/_/g, " ").toLowerCase()}</span> <span className="text-muted">· {a.actor} · {dateTime(a.at)}</span>{a.note && <div className="text-[13px] text-muted">{a.note}</div>}</li>
          ))}
          {d.outcomes.map((x: any, i: number) => (
            <li key={"o" + i} className="text-[14px]"><span className="font-medium">{STATE_LABEL[x.state]}</span> <span className="text-muted">· {x.label} · {dateTime(x.reported_at)}</span>{x.reason && <div className="text-[13px] text-muted">Reason: {x.reason}</div>}{x.terms && <TermsLine terms={x.terms} />}{x.disbursed_amount && <div className="text-[13px] text-muted">Disbursed {money(x.disbursed_amount)}</div>}</li>
          ))}
        </ol>
      </Card>

      <OutcomeModal open={!!outcome} state={outcome} onClose={() => setOutcome(null)} id={id} reasons={d.decline_reasons} amount={d.amount} onDone={(r: any) => { o.setData(r); setOutcome(null); toast("Outcome recorded"); }} />
      <AssignModal open={assign} onClose={() => setAssign(false)} id={id} members={d.members} onDone={(r: any) => { o.setData(r); setAssign(false); toast("Assigned"); }} />
    </div>
  );
}

const REQUEST_TONE: Record<string, "warning" | "success" | "muted" | "danger"> = { OPEN: "warning", FULFILLED: "success", CANCELLED: "muted", EXPIRED: "danger" };
const REQUEST_LABEL: Record<string, string> = { OPEN: "Waiting for customer", FULFILLED: "Answered", CANCELLED: "Cancelled", EXPIRED: "Expired — no answer" };

function InfoRequestsCard({ d, id, ask, setAsk, onChange }: any) {
  const [err, setErr] = useState<string | null>(null);
  const reqs: any[] = d.info_requests || [];
  if (!d.can_request_info && reqs.length === 0) return null;

  async function cancel(rid: string) {
    setErr(null);
    try {
      onChange(await api(`/inst/opportunities/${id}/info-requests/${rid}/cancel`, { body: {} }), "Request cancelled");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }

  return (
    <Card title="Requests to customer" subtitle="Ask for a document or an answer through WEZA. The customer chooses whether to respond."
      action={d.can_request_info ? <Button variant="secondary" onClick={() => setAsk(true)}>Ask the customer…</Button> : undefined}>
      {err && <Banner tone="danger" className="mb-3">{err}</Banner>}
      {reqs.length === 0 ? (
        <p className="text-[14px] text-muted">No requests yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {reqs.map((r) => (
            <li key={r.id} className="py-3 text-[14px]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{r.kind === "DOCUMENT" ? r.doc_label : "Question"}</span>
                <Badge tone={REQUEST_TONE[r.status]}>{REQUEST_LABEL[r.status]}</Badge>
                <span className="text-[13px] text-muted">· {r.requested_by} · {dateTime(r.created_at)}{r.status === "OPEN" && r.due_at ? ` · due ${dateTime(r.due_at)}` : ""}</span>
                {r.status === "OPEN" && d.can_request_info && <Button variant="ghost" className="ml-auto" onClick={() => cancel(r.id)}>Cancel</Button>}
              </div>
              <div className="mt-1 text-muted">{r.message}</div>
              {r.fact_label && <div className="mt-1 text-[12px] text-muted">Answer updates the customer&apos;s profile: {r.fact_label} (self-reported)</div>}
              {r.response_text && <div className="mt-2 rounded-lg bg-canvas px-3 py-2"><span className="text-[12px] text-muted">Customer answered: </span>{r.response_text}</div>}
              {r.document_id && (
                <button onClick={async () => { const res: Response = await api(`/inst/opportunities/${id}/documents/${r.document_id}`, { raw: true }); window.open(URL.createObjectURL(await res.blob()), "_blank"); }} className="mt-2 flex items-center gap-2 text-blue-800 hover:underline"><FileText className="h-4 w-4" />Open {r.doc_label?.toLowerCase()}</button>
              )}
              {r.status === "CANCELLED" && r.cancel_reason && <div className="mt-1 text-[12px] text-muted">{r.cancel_reason}</div>}
            </li>
          ))}
        </ul>
      )}
      <RequestModal open={ask} onClose={() => setAsk(false)} id={id} docTypes={d.doc_types} factFields={d.fact_fields} canDocs={d.can_request_documents} onDone={(r: any) => { setAsk(false); onChange(r, "Request sent to customer"); }} />
    </Card>
  );
}

function RequestModal({ open, onClose, id, docTypes, factFields, canDocs, onDone }: any) {
  const [kind, setKind] = useState(canDocs ? "DOCUMENT" : "QUESTION");
  const [docType, setDocType] = useState("");
  const [factKey, setFactKey] = useState("");
  const [message, setMessage] = useState("");
  const [days, setDays] = useState("3");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function send() {
    setBusy(true);
    setErr(null);
    try {
      const body: any = { kind, message, due_in_days: Number(days) };
      if (kind === "DOCUMENT") body.doc_type = docType;
      if (kind === "QUESTION" && factKey) body.fact_key = factKey;
      onDone(await api(`/inst/opportunities/${id}/info-requests`, { body, idempotencyKey: true }));
      setMessage("");
      setDocType("");
      setFactKey("");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Ask the customer" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button pending={busy} onClick={send} disabled={!message.trim() || (kind === "DOCUMENT" && !docType)}>Send request</Button></>}>
      <div className="space-y-3">
        <Field label="What do you need?">
          <Select value={kind} onChange={(e) => setKind(e.target.value)} options={[...(canDocs ? [["DOCUMENT", "A document"]] : []), ["QUESTION", "An answer to a question"]] as [string, string][]} />
        </Field>
        {kind === "DOCUMENT" && <Field label="Document" required><Select value={docType} onChange={(e) => setDocType(e.target.value)} options={[["", "Choose…"], ...Object.entries(docTypes || {}) as [string, string][]]} /></Field>}
        <Field label={kind === "DOCUMENT" ? "Message to the customer" : "Your question"} required>
          <Textarea rows={3} maxLength={1000} value={message} onChange={(e) => setMessage(e.target.value)} placeholder={kind === "DOCUMENT" ? "e.g. Please share the last 6 months so we can assess turnover." : "e.g. How many staff does the business employ?"} />
        </Field>
        {kind === "QUESTION" && (
          <Field label="Save the answer to profile field (optional)" hint="The customer's answer updates their WEZA profile as self-reported and may open more options for them.">
            <Select value={factKey} onChange={(e) => setFactKey(e.target.value)} options={[["", "Don't save to profile"], ...Object.entries(factFields || {}) as [string, string][]]} />
          </Field>
        )}
        <Field label="Respond within"><Select value={days} onChange={(e) => setDays(e.target.value)} options={[["1", "1 day"], ["3", "3 days"], ["7", "7 days"], ["14", "14 days"]]} /></Field>
        {!canDocs && <p className="text-[12px] text-muted">This customer's consent doesn't include documents, so you can only ask questions.</p>}
        <p className="text-[12px] text-muted">Never ask for PINs, passwords or one-time codes — WEZA will block the request.</p>
        {err && <Banner tone="danger">{err}</Banner>}
      </div>
    </Modal>
  );
}

function OutcomeModal({ open, state, onClose, id, reasons, amount, onDone }: any) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [amt, setAmt] = useState(String(amount || ""));
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10));
  const [t, setT] = useState({ tenor_months: "", interest_rate: "", rate_period: "MONTHLY", fees: "", monthly_repayment: "", conditions: "", terms_valid_until: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const num = (v: string) => (v === "" ? null : Number(v));
  async function save() {
    setBusy(true);
    setErr(null);
    try {
      const body: any = { state, reason_note: note || null };
      if (state === "REPORTED_DECLINED") body.reason_category = reason;
      if (state === "REPORTED_APPROVED") {
        body.approved_amount = Number(amt);
        Object.assign(body, { tenor_months: num(t.tenor_months), interest_rate: num(t.interest_rate), rate_period: t.interest_rate ? t.rate_period : null, fees: num(t.fees), monthly_repayment: num(t.monthly_repayment), conditions: t.conditions || null, terms_valid_until: t.terms_valid_until || null });
      }
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
        {state === "REPORTED_APPROVED" && (
          <details className="rounded-lg border border-line p-3">
            <summary className="cursor-pointer text-[14px] font-medium">Indicative terms (optional)</summary>
            <p className="mt-1 text-[12px] text-muted">Shown to the customer as reported by you — not a WEZA offer. Leave blank to share terms directly.</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Field label="Tenor (months)"><Input inputMode="numeric" value={t.tenor_months} onChange={(e) => setT({ ...t, tenor_months: e.target.value.replace(/[^\d]/g, "") })} /></Field>
              <Field label="Interest rate (%)">
                <div className="flex gap-2">
                  <Input inputMode="decimal" value={t.interest_rate} onChange={(e) => setT({ ...t, interest_rate: e.target.value.replace(/[^\d.]/g, "") })} />
                  <Select value={t.rate_period} onChange={(e) => setT({ ...t, rate_period: e.target.value })} options={[["MONTHLY", "per month"], ["ANNUAL", "per year"]]} />
                </div>
              </Field>
              <Field label="Fees (UGX)"><Input inputMode="numeric" value={t.fees} onChange={(e) => setT({ ...t, fees: e.target.value.replace(/[^\d]/g, "") })} /></Field>
              <Field label="Monthly repayment (UGX)"><Input inputMode="numeric" value={t.monthly_repayment} onChange={(e) => setT({ ...t, monthly_repayment: e.target.value.replace(/[^\d]/g, "") })} /></Field>
              <Field label="Valid until"><Input type="date" value={t.terms_valid_until} onChange={(e) => setT({ ...t, terms_valid_until: e.target.value })} /></Field>
            </div>
            <div className="mt-3"><Field label="Conditions"><Textarea rows={2} maxLength={1000} value={t.conditions} onChange={(e) => setT({ ...t, conditions: e.target.value })} placeholder="e.g. Subject to site visit and guarantor" /></Field></div>
          </details>
        )}
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

const BAND_TONE: Record<string, "success" | "warning" | "danger" | "muted"> = { EXCELLENT: "success", GOOD: "success", FAIR: "warning", POOR: "danger" };

function CreditReport({ r }: { r: any }) {
  const phone = r.phone_on_record === true ? "Yes" : r.phone_on_record === false ? "No — confirm with the customer" : "Not checked";
  return (
    <div className="mt-4 rounded-xl border border-line p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium">Credit bureau (gnuGRID)</span>
        {r.credit_score_band && <Badge tone={BAND_TONE[r.credit_score_band] || "muted"}>{r.credit_score_band.toLowerCase()}</Badge>}
        {r.has_active_defaults && <Badge tone="danger">Active arrears</Badge>}
      </div>
      <KV items={[
        ["Credit score", r.numeric_score != null ? `${r.numeric_score}${r.score_grade ? ` (${r.score_grade})` : ""}` : "—"],
        ["Probability of default", r.probability_of_default || "—"],
        ["Open loans", String(r.active_loans_count ?? 0)],
        ["Outstanding balance", moneyFull(r.total_outstanding_balance_ugx || 0)],
        ["Worst arrears", r.worst_days_in_arrears != null ? `${r.worst_days_in_arrears} days` : "—"],
        ["Payout number on the bureau record", phone],
      ]} />
      <p className="mt-2 text-[12px] text-muted">Pulled {dateTime(r.pulled_at)} · ref {r.crb_reference_id}. {r.label}</p>
    </div>
  );
}
