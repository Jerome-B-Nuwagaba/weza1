"use client";

import { ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money, STATE_LABEL } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Banner, Bar, Button, Card, ErrorState, Loading, Stat } from "@/components/ui";

const FUNNEL = ["ROUTED", "RECEIVED", "ASSIGNED", "CONTACTED", "PROCEEDING", "SUBMITTED_TO_INSTITUTION", "REPORTED_APPROVED", "REPORTED_DISBURSED", "REPORTED_DECLINED"];

export default function CommandCentre() {
  const { me, can } = useMe();
  const cc = useApi<any>("/inst/command-centre");
  const hour = new Date().getHours();
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  if (me.institution && me.institution.status !== "ACTIVE")
    return (
      <div className="space-y-4">
        <Banner tone="gold" title="Your workspace isn't live yet">Complete the activation checklist to start receiving qualified opportunities.</Banner>
        <Button href="/institution/onboarding">Open activation checklist</Button>
      </div>
    );
  if (cc.loading) return <Loading rows={6} />;
  if (cc.error) return <ErrorState error={cc.error} onRetry={cc.reload} />;
  const d = cc.data;
  const c = d.cards;
  const funnelMax = Math.max(1, ...FUNNEL.map((s) => d.funnel[s] || 0));
  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-line bg-surface p-6">
        <div className="text-[13px] text-muted">{greet}, {me.full_name.split(" ")[0]}.</div>
        <p className="mt-1 max-w-4xl font-serif text-[22px] leading-snug text-ink">{d.briefing}</p>
        {d.insights_open > 0 && can("analytics.read") && (
          <Link href="/institution/insights" className="mt-3 inline-flex items-center gap-1.5 text-[14px] font-medium text-gold-700"><Sparkles className="h-4 w-4" /> {d.insights_open} appetite insight{d.insights_open > 1 ? "s" : ""} to review <ArrowRight className="h-3.5 w-3.5" /></Link>
        )}
      </section>

      {d.no_lead && (
        <Banner tone="info" title="No opportunities in your queue right now">
          {d.no_lead.text} <Link href={d.no_lead.link} className="font-medium underline">Explore</Link>
        </Banner>
      )}

      <Card title="Needs your attention" subtitle="What requires action first — unassigned, service targets and holds.">
        {d.attention.length === 0 ? <p className="text-[14px] text-muted">Nothing urgent. Nicely done.</p> : (
          <ul className="divide-y divide-line">
            {d.attention.map((a: any, i: number) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex items-center gap-2 text-[14px]"><span className={`h-2 w-2 shrink-0 rounded-full ${a.severity === "high" ? "bg-danger" : a.severity === "medium" ? "bg-warning" : "bg-blue-400"}`} />{a.text}</span>
                <Button size="sm" variant="secondary" href={a.id ? `/institution/opportunities/${a.id}` : a.link}>{a.action}</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Stat label={c.new.label} value={c.new.value} href="/institution/feed" />
        <Stat label={c.qualified_demand.label} value={money(c.qualified_demand.value)} />
        <Stat label={c.high_match.label} value={c.high_match.value} tone="gold" href="/institution/feed?min_match=90" />
        <Stat label={c.unassigned.label} value={c.unassigned.value} href="/institution/feed?view=unassigned" />
        <Stat label={c.waiting.label} value={c.waiting.value} />
        <Stat label={c.avg_response.label} value={c.avg_response.value !== null ? `${c.avg_response.value}h` : "—"} />
        <Stat label={c.contacted.label} value={c.contacted.value} />
        <Stat label={c.progressing.label} value={c.progressing.value} />
        <Stat label={c.reported_approved.label} value={c.reported_approved.value} sub={c.reported_approved.sub} />
        <Stat label={c.reported_disbursed.label} value={c.reported_disbursed.value} sub={c.reported_disbursed.sub} tone="gold" />
        <Stat label={c.conversion.label} value={c.conversion.value !== null ? `${c.conversion.value}%` : "—"} />
      </div>

      <Card title="Marketplace pipeline" subtitle="Approvals and disbursements are as reported by your institution.">
        <ul className="space-y-2">
          {FUNNEL.map((s) => (
            <li key={s} className="grid grid-cols-[160px_1fr_40px] items-center gap-3 text-[13px]">
              <span className="text-muted">{STATE_LABEL[s]}</span>
              <Bar value={d.funnel[s] || 0} max={funnelMax} tone={s === "REPORTED_DISBURSED" ? "gold" : "blue"} />
              <span className="num text-right font-medium">{d.funnel[s] || 0}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
