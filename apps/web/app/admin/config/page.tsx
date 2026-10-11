"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, Card, ErrorState, Field, Input, KV, Loading, Modal, PageHeader, Select, useToast } from "@/components/ui";

const W_LABEL: Record<string, string> = { product_fit: "Product fit", appetite_fit: "Appetite fit", preference_fit: "Preference fit", readiness: "Readiness", capacity_fit: "Capacity fit" };

export default function Config() {
  const { can } = useMe();
  const c = useApi<any>("/admin/config");
  const [sw, setSw] = useState<{ key: string; value: any } | null>(null);
  const [reason, setReason] = useState("");
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => c.data && setWeights(c.data.match_weights.data), [c.data]);
  async function run(fn: () => Promise<any>, msg: string) {
    setErr(null);
    try {
      c.setData(await fn());
      toast(msg);
      return true;
    } catch (e) {
      setErr((e as ApiError).message);
      return false;
    }
  }
  if (c.loading) return <Loading />;
  if (c.error) return <ErrorState error={c.error} />;
  const d = c.data;
  const sum = Object.values(weights).reduce((a, b) => a + Number(b || 0), 0);
  const ks = Object.fromEntries(d.kill_switches.map((k: any) => [k.key, k]));
  return (
    <>
      {node}
      <PageHeader title="Configuration & network controls" subtitle="Every change is versioned or audited with a reason. Uganda is configuration, not hard-coded architecture." />
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      <Card title="Kill switches" subtitle="TSD §75 — audited, reason required." className="mb-4">
        <div className="space-y-3">
          <Row label="Pause all routing" on={!!ks.pause_all_routing.value.on} note={ks.pause_all_routing.reason} onToggle={() => setSw({ key: "pause_all_routing", value: { on: !ks.pause_all_routing.value.on } })} disabled={!can("admin.network_control")} />
          <Row label="Pause billing-event creation" on={!!ks.pause_billing_events.value.on} note={ks.pause_billing_events.reason} onToggle={() => setSw({ key: "pause_billing_events", value: { on: !ks.pause_billing_events.value.on } })} disabled={!can("admin.config")} />
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
            <span className="text-[14px] font-medium">AI mode <span className="font-normal text-muted">(AVAILABLE → DEGRADED → UNAVAILABLE)</span></span>
            <Select value={ks.ai_mode.value.mode || "AVAILABLE"} disabled={!can("admin.config")} onChange={(e) => setSw({ key: "ai_mode", value: { mode: e.target.value } })} options={["AVAILABLE", "DEGRADED", "UNAVAILABLE"]} className="!w-48" />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
            <span className="text-[14px] font-medium">Disabled channels</span>
            <div className="flex gap-2">{["web", "whatsapp", "sms"].map((ch) => { const list: string[] = ks.disabled_channels.value.channels || []; const off = list.includes(ch); return <button key={ch} disabled={!can("admin.config")} onClick={() => setSw({ key: "disabled_channels", value: { channels: off ? list.filter((x) => x !== ch) : [...list, ch] } })} className={`rounded-full border px-3 py-1 text-[13px] ${off ? "border-danger bg-danger-bg text-danger" : "border-line text-muted"}`}>{ch}{off ? " · off" : ""}</button>; })}</div>
          </div>
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={`Match weights · v${d.match_weights.version}`} subtitle="Composite weights are configurable and versioned (TSD §20). Must sum to 1.">
          <div className="space-y-2">
            {Object.keys(W_LABEL).map((k) => (
              <div key={k} className="grid grid-cols-[1fr_100px] items-center gap-3 text-[14px]"><span>{W_LABEL[k]}</span><Input type="number" step="0.05" min={0} max={1} value={weights[k] ?? 0} onChange={(e) => setWeights({ ...weights, [k]: Number(e.target.value) })} disabled={!can("admin.config")} /></div>
            ))}
          </div>
          <div className="mt-3 flex items-center justify-between"><Badge tone={Math.abs(sum - 1) < 0.001 ? "success" : "danger"}>Sum {sum.toFixed(2)}</Badge>{can("admin.config") && <Button size="sm" disabled={Math.abs(sum - 1) > 0.001} onClick={() => run(() => api("/admin/config/match-weights", { body: { weights, note: "Updated from Configuration" } }), "New weights version published")}>Publish new version</Button>}</div>
        </Card>
        <Card title="Feature flags">
          <ul className="space-y-2">{d.flags.map((f: any) => <li key={f.key}><Row label={f.label} on={f.enabled} onToggle={() => run(() => api("/admin/flags", { body: { key: f.key, enabled: !f.enabled } }), "Flag updated")} disabled={!can("admin.config")} /></li>)}</ul>
        </Card>
        <Card title={`Country configuration · Uganda v${d.country.version}`}>
          <KV items={[["Currency", d.country.data.currency], ["Phone", d.country.data.phone.prefix], ["Identity", d.country.data.identity_types.map((x: any) => x.code).join(", ")], ["Regions", Object.keys(d.country.data.regions).length], ["Sectors", Object.keys(d.country.data.sectors).length], ["Waiting Room", `${d.country.data.waiting_room_days} days`]]} />
        </Card>
        <Card title={`Consent text · v${d.consent_template.version}`} subtitle="Version-controlled legal text; never altered by AI translation.">
          <p className="max-h-48 overflow-auto whitespace-pre-line text-[13px] text-muted">{d.consent_template.text}</p>
          <p className="mt-2 text-[11px] text-muted">SHA-256 {d.consent_template.hash.slice(0, 24)}…</p>
        </Card>
      </div>
      <Modal open={!!sw} onClose={() => setSw(null)} title="Confirm network control change" footer={<><Button variant="secondary" onClick={() => setSw(null)}>Cancel</Button><Button variant="danger" disabled={reason.length < 3} onClick={async () => { if (await run(() => api("/admin/kill-switches", { body: { key: sw!.key, value: sw!.value, reason } }), "Control updated")) { setSw(null); setReason(""); } }}>Apply</Button></>}>
        <p className="mb-3 text-[14px]"><b>{sw?.key.replace(/_/g, " ")}</b> → {JSON.stringify(sw?.value)}</p>
        <Field label="Reason (audited)" required><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </>
  );
}

function Row({ label, on, onToggle, disabled, note }: { label: string; on: boolean; onToggle: () => void; disabled?: boolean; note?: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div><div className="text-[14px] font-medium">{label}</div>{note && <div className="text-[12px] text-muted">Last change: {note}</div>}</div>
      <button role="switch" aria-checked={on} disabled={disabled} onClick={onToggle} className={`relative h-6 w-11 shrink-0 rounded-full transition-colors disabled:opacity-50 ${on ? "bg-danger" : "bg-line"}`}>
        <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
      </button>
    </div>
  );
}
