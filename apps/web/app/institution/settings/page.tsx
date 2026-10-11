"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, ErrorState, Field, Input, KV, Loading, PageHeader, StateBadge, Textarea, useToast } from "@/components/ui";

const REGIONS = ["Central", "Eastern", "Northern", "Western"];

export default function Settings() {
  const { can } = useMe();
  const w = useApi<any>("/inst/workspace");
  const [p, setP] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => w.data && setP({ display_name: w.data.institution.display_name, description: w.data.institution.profile.description || "", website: w.data.institution.profile.website || "", regions_served: w.data.institution.profile.regions_served || [] }), [w.data]);
  if (w.loading || !p) return <Loading />;
  if (w.error) return <ErrorState error={w.error} />;
  const i = w.data.institution;
  async function save() {
    try {
      w.setData(await api("/inst/workspace", { method: "PATCH", body: p }));
      toast("Saved");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <div className="max-w-3xl space-y-4">
      {node}
      <PageHeader title="Institution settings" actions={<StateBadge state={i.status} />} />
      <Card title="Registration">
        <KV items={[["Legal name", i.legal_name], ["Type", i.type], ["Licence", i.licence_no], ["Regulator", i.regulator], ["Verified", i.verified_at ? date(i.verified_at) : "Pending"], ["Marketplace terms", `v${i.terms_version}`]]} />
        {i.status_reason && <p className="mt-2 text-[13px] text-muted">Last status note: {i.status_reason}</p>}
      </Card>
      <Card title="Marketplace profile" subtitle="Shown to customers on option cards.">
        <div className="space-y-3">
          <Field label="Display name"><Input value={p.display_name} onChange={(e) => setP({ ...p, display_name: e.target.value })} disabled={!can("institution.settings")} /></Field>
          <Field label="Description"><Textarea rows={3} value={p.description} onChange={(e) => setP({ ...p, description: e.target.value })} disabled={!can("institution.settings")} /></Field>
          <Field label="Website"><Input value={p.website} onChange={(e) => setP({ ...p, website: e.target.value })} disabled={!can("institution.settings")} /></Field>
          <Field label="Regions served" hint="Used for the customer's 'near me' preference."><div className="flex gap-2">{REGIONS.map((r) => <button key={r} type="button" disabled={!can("institution.settings")} onClick={() => setP({ ...p, regions_served: p.regions_served.includes(r) ? p.regions_served.filter((x: string) => x !== r) : [...p.regions_served, r] })} className={`rounded-full border px-3 py-1 text-[13px] ${p.regions_served.includes(r) ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{r}</button>)}</div></Field>
        </div>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
        {can("institution.settings") && <Button className="mt-4" onClick={save}>Save</Button>}
      </Card>
      <Banner tone="info" title="Zero core integration">WEZA never connects to your core banking, CRM, LOS or customer databases. Everything WEZA knows about your supply is configured here by your team.</Banner>
    </div>
  );
}
