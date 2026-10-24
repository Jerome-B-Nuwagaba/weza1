"use client";

import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime, money } from "@/lib/format";
import { ProductEditor } from "@/components/ProductEditor";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, StateBadge, Textarea, useToast } from "@/components/ui";

export default function ProductDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useMe();
  const p = useApi<any>(`/inst/products/${id}`);
  const [editing, setEditing] = useState(false);
  const [review, setReview] = useState<boolean | null>(null);
  const [statusTo, setStatusTo] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();

  async function act(fn: () => Promise<any>, msg: string) {
    setBusy(true);
    setErr(null);
    try {
      p.setData(await fn());
      toast(msg);
      return true;
    } catch (e) {
      setErr(e as ApiError);
      return false;
    } finally {
      setBusy(false);
    }
  }
  if (p.loading) return <Loading />;
  if (p.error) return <ErrorState error={p.error} onRetry={p.reload} />;
  const d = p.data;
  const latest = d.versions[0];
  const active = d.versions.find((v: any) => v.id === d.active_version_id);
  const shown = latest;
  const pending = latest.status === "PENDING_APPROVAL";
  const draft = latest.status === "DRAFT";

  return (
    <>
      {node}
      <PageHeader eyebrow="Products" title={d.name} subtitle={`${d.family.replace(/_/g, " ").toLowerCase()} · live version ${active ? "v" + active.version : "none"}`}
        actions={<>
          <StateBadge state={d.status} />
          {can("product.create") && !pending && <Button variant="secondary" onClick={() => setEditing(!editing)}>{editing ? "Close editor" : draft ? "Edit draft" : "Edit (new version)"}</Button>}
          {can("product.create") && draft && <Button pending={busy} onClick={() => act(() => api(`/inst/products/${id}/submit`, { method: "POST" }), "Submitted for approval")}>Submit for approval</Button>}
          {d.status === "ACTIVE" && can("product.approve") && <Button variant="secondary" onClick={() => setStatusTo("PAUSED")}>Pause</Button>}
          {d.status === "PAUSED" && can("product.approve") && <Button onClick={() => setStatusTo("ACTIVE")}>Resume</Button>}
          {["ACTIVE", "PAUSED"].includes(d.status) && can("product.approve") && <Button variant="ghost" onClick={() => setStatusTo("ARCHIVED")}>Archive</Button>}
        </>} />
      {err && <Banner tone="danger" className="mb-4">{err.message}</Banner>}
      {pending && (
        <Banner tone="warning" title={`Version ${latest.version} is awaiting approval`} className="mb-4">
          Submitted by {latest.author || "a colleague"}. {latest.author_id === d.me ? "Someone other than you must approve it (maker-checker)." : can("product.approve") ? "Review the configuration below." : "An approver will review it."}
          {can("product.approve") && latest.author_id !== d.me && (
            <div className="mt-2 flex gap-2"><Button size="sm" onClick={() => setReview(true)}>Approve & activate</Button><Button size="sm" variant="secondary" onClick={() => setReview(false)}>Reject</Button></div>
          )}
        </Banner>
      )}
      {editing ? (
        <ProductEditor initial={{ name: shown.name, family: shown.family, terms: shown.terms, rules: shown.rules, requirements: shown.requirements }} saving={busy} error={err}
          onSave={async (draft) => { if (await act(async () => { await api(`/inst/products/${id}`, { method: "PUT", body: draft }); return api(`/inst/products/${id}`); }, "Draft saved")) setEditing(false); }} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <div className="space-y-4">
            <Card title={`Version ${shown.version}`} action={<StateBadge state={shown.status} />}>
              <KV items={[["Amount", `${money(shown.terms.min_amount)} – ${money(shown.terms.max_amount)}`], ["Tenor", `${shown.terms.min_tenor_months}–${shown.terms.max_tenor_months} months`], ["Customer type", shown.terms.customer_type ? ({ SME: "Business (SME)", SALARIED: "Salaried", AGRICULTURE: "Farmer" } as Record<string, string>)[shown.terms.customer_type] || shown.terms.customer_type : "—"], ["Pricing shown", shown.terms.pricing_display || "—"], ["Collateral", shown.terms.collateral_required ? "Required" : "Not required"], ["Digital process", shown.terms.digital_journey ? "Yes" : "No"], ["Ruleset", shown.ruleset_hash?.slice(0, 12)]]} />
            </Card>
            <Card title="Eligibility rules">
              {shown.rules.length === 0 ? <p className="text-[14px] text-muted">Amount range only.</p> : (
                <ul className="space-y-1.5 text-[14px]">{shown.rules.map((r: any, i: number) => <li key={i} className="flex gap-2"><Badge tone="muted">{r.field}</Badge>{r.label || `${r.op} ${JSON.stringify(r.value)}`}</li>)}</ul>
              )}
            </Card>
            <Card title="Requirements">
              {shown.requirements.length === 0 ? <p className="text-[14px] text-muted">None.</p> : <ul className="space-y-1 text-[14px]">{shown.requirements.map((r: any, i: number) => <li key={i}>{r.label} {r.required ? <Badge tone="warning">required</Badge> : <Badge tone="muted">optional</Badge>}</li>)}</ul>}
            </Card>
            {shown.provenance?.items?.length > 0 && (
              <Card title="Extraction provenance"><ul className="space-y-1 text-[13px] text-muted">{shown.provenance.items.map((x: any, i: number) => <li key={i}><b>{x.field}</b>: “{x.quote}”</li>)}</ul></Card>
            )}
          </div>
          <Card title="Version history">
            <ol className="space-y-3">
              {d.versions.map((v: any) => (
                <li key={v.id} className="text-[13px]">
                  <div className="flex items-center gap-2"><b>v{v.version}</b><StateBadge state={v.status} /></div>
                  <div className="text-muted">By {v.author || "—"} · {dateTime(v.created_at)}</div>
                  {v.approver && <div className="text-muted">Approved by {v.approver} · {dateTime(v.approved_at)}</div>}
                  {v.review_note && <div className="text-muted">“{v.review_note}”</div>}
                </li>
              ))}
            </ol>
          </Card>
        </div>
      )}
      <Modal open={review !== null} onClose={() => setReview(null)} title={review ? "Approve and activate" : "Reject version"} footer={<><Button variant="secondary" onClick={() => setReview(null)}>Cancel</Button><Button pending={busy} variant={review ? "primary" : "danger"} onClick={async () => { if (await act(() => api(`/inst/products/${id}/review`, { body: { approve: review, note } }), review ? "Approved — product live" : "Rejected")) setReview(null); }}>{review ? "Approve" : "Reject"}</Button></>}>
        <Field label="Note"><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {review && <p className="mt-2 text-[13px] text-muted">Once approved, WEZA re-runs market clearing and this version starts matching customers.</p>}
      </Modal>
      <Modal open={!!statusTo} onClose={() => setStatusTo(null)} title={statusTo === "PAUSED" ? "Pause product" : statusTo === "ARCHIVED" ? "Archive product" : "Resume product"} footer={<><Button variant="secondary" onClick={() => setStatusTo(null)}>Cancel</Button><Button pending={busy} onClick={async () => { if (await act(() => api(`/inst/products/${id}/status`, { body: { status: statusTo, reason: note } }), "Updated")) setStatusTo(null); }} disabled={note.length < 3}>Confirm</Button></>}>
        <Field label="Reason" required><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {statusTo === "PAUSED" && <p className="mt-2 text-[13px] text-muted">Customers stop seeing this product immediately. Already-routed opportunities are unaffected.</p>}
        {statusTo === "ARCHIVED" && <p className="mt-2 text-[13px] text-muted">Archiving is permanent: the product is withdrawn from customers and can&apos;t be resumed. Its versions and history are kept. Already-routed opportunities are unaffected.</p>}
      </Modal>
    </>
  );
}
