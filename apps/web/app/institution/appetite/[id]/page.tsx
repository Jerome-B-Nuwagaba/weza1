"use client";

import { use, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime, money } from "@/lib/format";
import { AppetiteEditor } from "@/components/AppetiteEditor";
import { SimulationResult } from "@/components/Simulation";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Bar, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, Select, StateBadge, Textarea, useToast } from "@/components/ui";

export default function AppetiteDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { can } = useMe();
  const a = useApi<any>(`/inst/appetites/${id}`);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [sim, setSim] = useState<any>(null);
  const [review, setReview] = useState<boolean | null>(null);
  const [lifecycle, setLifecycle] = useState<string | null>(null);
  const [capacity, setCapacity] = useState(false);
  const [note, setNote] = useState("");
  const [override, setOverride] = useState("");
  const { toast, node } = useToast();

  async function act(fn: () => Promise<any>, msg: string) {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      toast(msg);
      a.reload();
      return r ?? true;
    } catch (e) {
      setErr(e as ApiError);
      return false;
    } finally {
      setBusy(false);
    }
  }
  if (a.loading) return <Loading />;
  if (a.error) return <ErrorState error={a.error} onRetry={a.reload} />;
  const d = a.data;
  const latest = d.versions[0];
  const current = d.versions.find((v: any) => v.id === d.active_version_id) || latest;
  const workable = ["DRAFT", "SIMULATED"].includes(latest.status);
  const simulation = sim || latest.simulation;

  return (
    <>
      {node}
      <PageHeader eyebrow="Appetite Studio" title={d.name} subtitle={`Current v${current.version} · min match ${current.min_match_score} · ${current.criteria.length} criteria`}
        actions={<>
          <StateBadge state={d.lifecycle_status} />
          {d.lifecycle_status === "ACTIVE" && <StateBadge state={d.capacity_state} label={`Capacity ${d.capacity_state.toLowerCase()}`} />}
          {can("appetite.edit") && <Button variant="secondary" onClick={() => setEditing(!editing)}>{editing ? "Close editor" : workable ? "Edit draft" : "New version"}</Button>}
          {workable && can("appetite.simulate") && <Button pending={busy} onClick={async () => { const r = await act(() => api(`/inst/appetites/${id}/simulate`, { method: "POST" }), "Simulation complete"); if (r && r !== true) setSim(r); }}>Run simulation</Button>}
          {d.lifecycle_status === "ACTIVE" && can("appetite.activate") && <Button variant="secondary" onClick={() => setLifecycle("PAUSED")}>Pause</Button>}
          {d.lifecycle_status === "PAUSED" && can("appetite.activate") && <Button onClick={() => setLifecycle("ACTIVE")}>Resume</Button>}
          {d.lifecycle_status === "APPROVED" && can("appetite.activate") && <Button onClick={() => setLifecycle("ACTIVE")}>Activate</Button>}
          {can("appetite.edit") && d.lifecycle_status === "ACTIVE" && <Button variant="ghost" onClick={() => setCapacity(true)}>Capacity override</Button>}
        </>} />
      {err && <Banner tone="danger" className="mb-4">{err.message}</Banner>}
      {latest.status === "SIMULATED" && (
        <Banner tone="warning" title={`Version ${latest.version} simulated — awaiting approval`} className="mb-4">
          {latest.author_id === d.me ? "Someone other than you must approve it (maker-checker)." : "Review the simulation, then approve or reject."}
          {can("appetite.activate") && latest.author_id !== d.me && <div className="mt-2 flex gap-2"><Button size="sm" onClick={() => setReview(true)}>Approve</Button><Button size="sm" variant="secondary" onClick={() => setReview(false)}>Reject</Button></div>}
        </Banner>
      )}
      {latest.status === "DRAFT" && <Banner tone="info" className="mb-4">Version {latest.version} is a draft. Run a simulation before it can be approved.</Banner>}

      {editing ? (
        <AppetiteEditor saving={busy} error={err} initial={{ name: latest.name, product_ids: latest.product_ids, criteria: latest.criteria, min_match_score: latest.min_match_score, target_count: latest.target_count, target_value: latest.target_value, capacity_limits: latest.capacity_limits, campaign_from: latest.campaign_from, campaign_to: latest.campaign_to }}
          onSave={async (draft) => { if (await act(() => api(`/inst/appetites/${id}`, { method: "PUT", body: draft }), "Draft saved — simulate before approval")) setEditing(false); }} />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
            <Card title={`Criteria — v${latest.version}`} action={<StateBadge state={latest.status} />}>
              {latest.criteria.length === 0 ? <p className="text-[14px] text-muted">No extra criteria: all demand eligible for the selected products.</p> : (
                <ul className="space-y-1.5 text-[14px]">{latest.criteria.map((c: any, i: number) => <li key={i} className="flex flex-wrap items-center gap-2"><Badge tone={c.must ? "warning" : "muted"}>{c.must ? "must" : `×${c.weight}`}</Badge>{c.label || `${c.field} ${c.op} ${JSON.stringify(c.value)}`}</li>)}</ul>
              )}
              <div className="mt-4"><KV items={[["Target", latest.target_count ? `${latest.target_count} opportunities` : "—"], ["Target value", latest.target_value ? money(latest.target_value) : "—"], ["Campaign", latest.campaign_from ? `${latest.campaign_from} → ${latest.campaign_to}` : "Open-ended"], ["Daily capacity", latest.capacity_limits.daily_count ?? "—"]]} /></div>
            </Card>
            <Card title="Fulfilment">
              <div className="num text-2xl font-semibold">{d.fulfilled_count}{current.target_count ? <span className="text-[15px] text-muted"> / {current.target_count}</span> : ""}</div>
              <div className="text-[13px] text-muted">{money(d.fulfilled_value)} routed through this mandate</div>
              {current.target_count && <div className="mt-2"><Bar value={d.fulfilled_count} max={current.target_count} tone="gold" /></div>}
              <div className="mt-4 text-[12px] text-muted">Versions: {d.versions.map((v: any) => `v${v.version} ${v.status.toLowerCase()}${v.approved_at ? ` (${dateTime(v.approved_at)})` : ""}`).join(" · ")}</div>
            </Card>
          </div>
          {simulation ? <Card title="Simulation against WEZA demand"><SimulationResult r={simulation} /></Card> : null}
        </div>
      )}

      <Modal open={review !== null} onClose={() => setReview(null)} title={review ? "Approve appetite" : "Reject version"} footer={<><Button variant="secondary" onClick={() => setReview(null)}>Cancel</Button><Button pending={busy} variant={review ? "primary" : "danger"} onClick={async () => { if (await act(() => api(`/inst/appetites/${id}/review`, { body: { approve: review, note } }), review ? "Approved" : "Rejected")) setReview(null); }}>{review ? "Approve" : "Reject"}</Button></>}>
        <Field label="Note"><Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {review && <p className="mt-2 text-[13px] text-muted">If your institution is live, this version activates immediately and WEZA re-clears the market.</p>}
      </Modal>
      <Modal open={!!lifecycle} onClose={() => setLifecycle(null)} title={lifecycle === "PAUSED" ? "Pause appetite" : "Activate appetite"} footer={<><Button variant="secondary" onClick={() => setLifecycle(null)}>Cancel</Button><Button pending={busy} disabled={note.length < 3} onClick={async () => { if (await act(() => api(`/inst/appetites/${id}/status`, { body: { status: lifecycle, reason: note } }), "Updated")) setLifecycle(null); }}>Confirm</Button></>}>
        <Field label="Reason" required><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
      <Modal open={capacity} onClose={() => setCapacity(false)} title="Capacity override" footer={<><Button variant="secondary" onClick={() => setCapacity(false)}>Cancel</Button><Button pending={busy} disabled={note.length < 3} onClick={async () => { if (await act(() => api(`/inst/appetites/${id}/capacity`, { body: { override: override || null, reason: note } }), "Capacity updated")) setCapacity(false); }}>Save</Button></>}>
        <div className="space-y-3">
          <Field label="Override"><Select value={override} onChange={(e) => setOverride(e.target.value)} options={[["", "None (automatic from limits)"], ["LIMITED", "Limited — only highest-priority demand"], ["PAUSED", "Paused — receive nothing new"]]} /></Field>
          <Field label="Reason" required><Input value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>
    </>
  );
}
