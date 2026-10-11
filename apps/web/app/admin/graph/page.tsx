"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { Badge, Banner, Button, Card, cx, EmptyState, Input, KV, Loading, PageHeader, StateBadge, Tabs } from "@/components/ui";

const ORDER = ["Customer", "FinancialNeed", "Match", "Consent", "Opportunity", "Institution", "Officer", "Outcome", "CommercialEvent"];
const LABEL: Record<string, string> = { FinancialNeed: "Financial Need", CommercialEvent: "Commercial event" };

function Inspector() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") || "");
  const [g, setG] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState<any>(null);
  const [tab, setTab] = useState("workflow");

  async function load(query: string) {
    if (!query) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api(`/admin/graph?q=${encodeURIComponent(query)}`);
      setG(r);
      setSel(null);
    } catch (e) {
      setErr((e as ApiError).message);
      setG(null);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (params.get("q")) load(params.get("q")!);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const byKind: Record<string, any[]> = {};
  g?.nodes.forEach((n: any) => (byKind[n.kind] ||= []).push(n));
  const rel = (id: string) => g?.edges.filter((e: any) => e.from === id || e.to === id) || [];

  return (
    <>
      <PageHeader title="Graph Inspector" subtitle="Customer → Need → Match → Consent → Opportunity → Institution → Officer → Outcome — with workflow state, events, decisions, audit and AI calls. Every inspection is audited." />
      <form onSubmit={(e) => { e.preventDefault(); router.replace(`/admin/graph?q=${encodeURIComponent(q)}`); load(q); }} className="mb-4 flex gap-2">
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Opportunity reference (OPP-…) or any ID" />
        <Button type="submit" pending={busy}>Inspect</Button>
      </form>
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      {!g ? (!busy && <EmptyState title="Search for an opportunity or need">Try an OPP- reference from Opportunity monitoring.</EmptyState>) : (
        <>
          <div className="scroll-thin mb-4 overflow-x-auto rounded-xl border border-line bg-surface p-4">
            <div className="flex min-w-max gap-3">
              {ORDER.filter((k) => byKind[k]).map((k, i) => (
                <div key={k} className="flex items-stretch gap-3">
                  {i > 0 && <div className="flex items-center text-muted">→</div>}
                  <div className="w-52 space-y-2">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">{LABEL[k] || k}</div>
                    {byKind[k].slice(0, 12).map((n: any) => (
                      <button key={n.id} onClick={() => setSel(n)} className={cx("block w-full rounded-lg border px-3 py-2 text-left text-[12.5px]", sel?.id === n.id ? "border-blue-600 bg-blue-50" : "border-line hover:border-blue-400", n.data?.state === "INVALIDATED" || n.data?.state === "EXCLUDED" ? "opacity-60" : "")}>
                        <div className="font-medium text-ink">{n.label}</div>
                        {n.data?.state && <div className="text-muted">{String(n.data.state).toLowerCase()}</div>}
                      </button>
                    ))}
                    {byKind[k].length > 12 && <div className="text-[12px] text-muted">+{byKind[k].length - 12} more</div>}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {sel && (
            <Card title={`${sel.kind}: ${sel.label}`} className="mb-4" action={<Button size="sm" variant="ghost" onClick={() => setSel(null)}>Close</Button>}>
              <div className="mb-2 flex flex-wrap gap-1.5">{rel(sel.id).map((e: any, i: number) => <Badge key={i} tone="muted">{e.rel}</Badge>)}</div>
              <pre className="scroll-thin max-h-96 overflow-auto rounded-lg bg-canvas p-3 text-[12px]">{JSON.stringify(sel.data, null, 2)}</pre>
            </Card>
          )}
          <Tabs tabs={[["workflow", "Workflow graph"], ["events", `Events (${g.events.length})`], ["decisions", `Decisions (${g.decisions.length})`], ["audit", `Audit (${g.audit.length})`], ["ai", `AI calls (${g.ai_calls.length})`]]} value={tab} onChange={setTab} />
          {tab === "workflow" && (g.graph ? (
            <div className="grid gap-4 lg:grid-cols-[1fr_2fr]">
              <Card title={`${g.graph.type} v${g.graph.version}`}>
                <KV items={[["Current node", <Badge key="n" tone="gold">{g.graph.current_node}</Badge>], ["Status", <StateBadge key="s" state={g.graph.status} />], ["Waiting for", g.graph.waiting_for || "—"], ["Next timer", dateTime(g.graph.next_action_at)], ["Attempts", g.graph.attempts], ["Error", g.graph.error ? JSON.stringify(g.graph.error) : "—"]]} />
                <pre className="scroll-thin mt-3 max-h-64 overflow-auto rounded-lg bg-canvas p-3 text-[11.5px]">{JSON.stringify(g.graph.state, null, 2)}</pre>
              </Card>
              <Card title="Transitions">
                <ol className="space-y-1 text-[13px]">{g.transitions.map((t: any, i: number) => <li key={i} className="flex flex-wrap gap-2"><span className="text-muted">{dateTime(t.at)}</span><span>{t.from} → <b>{t.to}</b></span><Badge tone="muted">{t.trigger}</Badge><Badge tone={t.autonomy === 0 ? "gold" : "neutral"}>AL{t.autonomy}</Badge></li>)}</ol>
              </Card>
            </div>
          ) : <p className="text-[14px] text-muted">No workflow instance (seeded/demo record).</p>)}
          {tab === "events" && (
            <div className="space-y-1.5">{g.events.map((e: any, i: number) => (
              <details key={i} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]">
                <summary className="cursor-pointer"><b>{e.type}</b> <span className="text-muted">· {e.topic} · {dateTime(e.at)}</span> {e.deliveries.map((d: any, j: number) => <Badge key={j} tone={d.status === "DONE" ? "success" : d.status === "DEAD" ? "danger" : "warning"} className="ml-1">{d.consumer}</Badge>)}</summary>
                <pre className="mt-2 overflow-auto text-[11.5px]">{JSON.stringify({ data: e.data, deliveries: e.deliveries }, null, 2)}</pre>
              </details>
            ))}</div>
          )}
          {tab === "decisions" && (
            <div className="space-y-1.5">{g.decisions.map((d: any, i: number) => (
              <details key={i} className="rounded-lg border border-line bg-surface px-3 py-2 text-[13px]">
                <summary className="cursor-pointer"><b>{d.type}</b> <span className="text-muted">· {dateTime(d.at)} · {d.algorithm || ""} {d.ruleset || ""}</span></summary>
                <pre className="mt-2 overflow-auto text-[11.5px]">{JSON.stringify({ output: d.output, inputs: d.inputs }, null, 2)}</pre>
              </details>
            ))}</div>
          )}
          {tab === "audit" && <ul className="space-y-1 text-[13px]">{g.audit.map((a: any, i: number) => <li key={i}><span className="text-muted">{dateTime(a.at)}</span> · <b>{a.action}</b> · {a.actor}{a.reason && ` · ${a.reason}`}</li>)}</ul>}
          {tab === "ai" && (g.ai_calls.length === 0 ? <p className="text-[14px] text-muted">No AI calls — deterministic path.</p> : <ul className="space-y-1 text-[13px]">{g.ai_calls.map((a: any, i: number) => <li key={i}>{dateTime(a.at)} · <b>{a.capability}</b> · {a.model} · {a.latency_ms}ms · {a.tokens} tokens {a.fallback && <Badge tone="warning">fallback</Badge>}{a.error && <Badge tone="danger">{a.error}</Badge>}</li>)}</ul>)}
        </>
      )}
    </>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Inspector />
    </Suspense>
  );
}
