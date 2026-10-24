"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, ErrorState, Loading, Stat } from "@/components/ui";

export default function CommandCentre() {
  const { me } = useMe();
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
  return (
    <div className="space-y-6">
      <section className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-[13px] text-muted">{greet}, {me.full_name.split(" ")[0]}.</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">Today&apos;s opportunities</h1>
          <p className="mt-1 max-w-3xl text-[14px] text-muted">{d.briefing}</p>
        </div>
        <Button href="/institution/feed">View opportunities</Button>
      </section>

      {d.no_lead && (
        <Banner tone="info" title="No opportunities in your queue right now">
          {d.no_lead.text} <Link href={d.no_lead.link} className="font-medium underline">Explore</Link>
        </Banner>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label={c.new.label} value={c.new.value} href="/institution/feed" />
        <Stat label={c.high_match.label} value={c.high_match.value} tone="gold" href="/institution/feed?min_match=90" />
        <Stat label={c.unassigned.label} value={c.unassigned.value} href="/institution/feed?view=unassigned" />
        <Stat label={c.waiting.label} value={c.waiting.value} />
      </div>

      <Card title="Needs your attention" subtitle="The few items that need an action now.">
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

      <Card title="Your matching setup" subtitle="Keep your active products and appetite current so WEZA can find relevant customer demand.">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" href="/institution/products">Manage products</Button>
          <Button variant="secondary" href="/institution/appetite">Manage appetite</Button>
          <Button variant="ghost" href="/institution/team">Review team routing</Button>
        </div>
      </Card>
    </div>
  );
}
