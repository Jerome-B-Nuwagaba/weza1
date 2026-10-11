"use client";

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Banner, Button, Card, ErrorState, Field, Input, Loading, PageHeader, Select, useToast } from "@/components/ui";

const TYPES: [string, string][] = [["SME", "Business"], ["SALARIED", "Salaried"], ["AGRICULTURE", "Farmer"]];
const REGIONS = ["Central", "Eastern", "Northern", "Western"];

export default function Routing() {
  const r = useApi<any>("/inst/routing");
  const [rules, setRules] = useState<any[]>([]);
  const [targets, setTargets] = useState<any>({});
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => {
    if (r.data) {
      setRules(r.data.rules);
      setTargets(r.data.targets);
    }
  }, [r.data]);
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const d = r.data;
  const set = (i: number, patch: any) => setRules(rules.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const setC = (i: number, patch: any) => set(i, { conditions: { ...rules[i].conditions, ...patch } });
  const toggle = (arr: string[] = [], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  const move = (i: number, dir: -1 | 1) => { const n = [...rules]; [n[i], n[i + dir]] = [n[i + dir], n[i]]; setRules(n); };
  async function save() {
    setErr(null);
    try {
      r.setData(await api("/inst/routing", { method: "PUT", body: { rules, targets } }));
      toast("Routing saved");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <>
      {node}
      <PageHeader title="Routing & service targets" subtitle="Rules run top to bottom; the first match assigns the opportunity to a team (least-loaded officer). No match → Unassigned queue + manager alert." actions={d.can_edit && <Button onClick={save}>Save</Button>} />
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      <Card title="Service targets" className="mb-4">
        <div className="grid gap-4 md:grid-cols-3">
          <Field label="Acknowledge within (minutes)"><Input inputMode="numeric" value={targets.ack_within_minutes ?? ""} onChange={(e) => setTargets({ ...targets, ack_within_minutes: Number(e.target.value) })} disabled={!d.can_edit} /></Field>
          <Field label="First contact within (minutes)"><Input inputMode="numeric" value={targets.first_contact_within_minutes ?? ""} onChange={(e) => setTargets({ ...targets, first_contact_within_minutes: Number(e.target.value) })} disabled={!d.can_edit} /></Field>
          <Field label="Escalate to WEZA after (minutes)"><Input inputMode="numeric" value={targets.escalate_after_minutes ?? ""} onChange={(e) => setTargets({ ...targets, escalate_after_minutes: Number(e.target.value) })} disabled={!d.can_edit} /></Field>
        </div>
      </Card>
      <div className="space-y-3">
        {rules.map((x, i) => (
          <Card key={i}>
            <div className="mb-3 flex items-center gap-2">
              <span className="num flex h-6 w-6 items-center justify-center rounded-full bg-blue-50 text-[12px] font-semibold text-blue-800">{i + 1}</span>
              <Input value={x.name} onChange={(e) => set(i, { name: e.target.value })} className="!h-9 flex-1" disabled={!d.can_edit} />
              {d.can_edit && <><button disabled={i === 0} onClick={() => move(i, -1)} aria-label="Up" className="p-1 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button><button disabled={i === rules.length - 1} onClick={() => move(i, 1)} aria-label="Down" className="p-1 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button><button onClick={() => setRules(rules.filter((_, j) => j !== i))} aria-label="Remove" className="p-1 text-muted hover:text-danger"><Trash2 className="h-4 w-4" /></button></>}
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Customer types (any if none)"><div className="flex flex-wrap gap-1.5">{TYPES.map(([v, l]) => <Chip key={v} on={(x.conditions.customer_types || []).includes(v)} onClick={() => setC(i, { customer_types: toggle(x.conditions.customer_types, v) })}>{l}</Chip>)}</div></Field>
              <Field label="Regions (any if none)"><div className="flex flex-wrap gap-1.5">{REGIONS.map((v) => <Chip key={v} on={(x.conditions.regions || []).includes(v)} onClick={() => setC(i, { regions: toggle(x.conditions.regions, v) })}>{v}</Chip>)}</div></Field>
              <Field label="Products (any if none)"><div className="flex flex-wrap gap-1.5">{d.products.map((p: any) => <Chip key={p.id} on={(x.conditions.product_ids || []).includes(p.id)} onClick={() => setC(i, { product_ids: toggle(x.conditions.product_ids, p.id) })}>{p.name}</Chip>)}</div></Field>
              <div className="grid grid-cols-2 gap-2">
                <Field label="Min amount"><Input inputMode="numeric" value={x.conditions.min_amount ?? ""} onChange={(e) => setC(i, { min_amount: e.target.value ? Number(e.target.value) : null })} /></Field>
                <Field label="Max amount"><Input inputMode="numeric" value={x.conditions.max_amount ?? ""} onChange={(e) => setC(i, { max_amount: e.target.value ? Number(e.target.value) : null })} /></Field>
              </div>
              <Field label="Route to team"><Select value={x.target_team_id || ""} onChange={(e) => set(i, { target_team_id: e.target.value || null })} options={[["", "Choose team…"], ...d.teams.map((t: any) => [t.id, t.name])]} /></Field>
            </div>
          </Card>
        ))}
        {d.can_edit && <Button variant="secondary" onClick={() => setRules([...rules, { name: `Rule ${rules.length + 1}`, conditions: {}, target_team_id: d.teams[0]?.id || null, active: true }])}><Plus className="h-4 w-4" /> Add rule</Button>}
      </div>
    </>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" onClick={onClick} className={`rounded-full border px-2.5 py-0.5 text-[12.5px] ${on ? "border-blue-600 bg-blue-600 text-white" : "border-line text-muted"}`}>{children}</button>;
}
