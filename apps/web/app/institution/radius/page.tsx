"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { RuleBuilder, Rule } from "@/components/RuleBuilder";
import { SimulationResult } from "@/components/Simulation";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";

export default function Radius() {
  const { can } = useMe();
  const r = useApi<any>("/inst/intelligence/radius");
  const cfg = useApi<any>("/public/config");
  const appetites = useApi<any>("/inst/appetites");
  const [whatIf, setWhatIf] = useState<{ base: any; criteria: Rule[]; product_ids: string[]; min: number; result?: any } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function open(a: any) {
    const det = await api(`/inst/appetites/${a.appetite_id}`);
    const v = det.versions.find((x: any) => x.id === det.active_version_id);
    setWhatIf({ base: a, criteria: v.criteria, product_ids: v.product_ids, min: v.min_match_score });
  }
  async function run() {
    if (!whatIf) return;
    setBusy(true);
    setErr(null);
    try {
      const result = await api("/inst/simulate", { body: { product_ids: whatIf.product_ids, criteria: whatIf.criteria, min_match_score: whatIf.min } });
      setWhatIf({ ...whatIf, result });
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="Opportunity Radius" subtitle="How restrictive or expansive is your appetite? Demand inside, just outside, and beyond your current mandates — from WEZA marketplace data only." />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : r.data.appetites.length === 0 ? (
        <EmptyState title="No active appetite yet">Activate an appetite to see your radius.</EmptyState>
      ) : (
        <div className="space-y-6">
          {r.data.appetites.map((a: any) => (
            <Card key={a.appetite_id} title={`${a.appetite} · v${a.version}`} action={can("appetite.simulate") && <Button size="sm" variant="secondary" onClick={() => open(a)}>Simulate a change</Button>}>
              <SimulationResult r={a} />
            </Card>
          ))}
        </div>
      )}
      {whatIf && (
        <Card title={`What-if: ${whatIf.base.appetite}`} className="mt-6" subtitle="Adjust criteria and simulate. Nothing is saved — changes go through Appetite Studio and approval.">
          <RuleBuilder rules={whatIf.criteria} onChange={(criteria) => setWhatIf({ ...whatIf, criteria, result: undefined })} cfg={cfg.data} appetite />
          <div className="mt-3 flex gap-2"><Button pending={busy} onClick={run}>Run what-if</Button><Button variant="ghost" onClick={() => setWhatIf(null)}>Close</Button></div>
          {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
          {whatIf.result && <div className="mt-4"><SimulationResult r={whatIf.result} compare={whatIf.base} /></div>}
          {appetites.data && <p className="mt-3 text-[12px] text-muted">WEZA never loosens your criteria automatically.</p>}
        </Card>
      )}
    </>
  );
}
