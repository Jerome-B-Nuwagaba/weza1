"use client";

import Link from "next/link";
import { Bell, Box, ChevronRight, Database, MoreVertical, Target } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { ago } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { InstitutionAskPanel } from "@/components/InstitutionAskPanel";
import { Badge, Banner, Button, Card, cx, ErrorState, Loading, Table, Td } from "@/components/ui";

const PRIORITY: Record<string, [string, string]> = { high: ["High", "danger"], medium: ["Medium", "warning"], low: ["Low", "neutral"] };

const initials = (name: string) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("");

function Tile({ href, icon: Icon, tint, label, value, sub }: {
  href: string; icon: any; tint: string; label: string; value: number; sub: React.ReactNode;
}) {
  return (
    <Link href={href} className="group flex items-center gap-5 rounded-2xl border border-line bg-surface p-6 shadow-xs transition-colors hover:border-blue-400">
      <span className={cx("flex h-14 w-14 shrink-0 items-center justify-center rounded-full", tint)}>
        <Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[16px] font-medium text-ink">{label}</span>
        <span className="num mt-1 block text-[32px] font-bold leading-none tracking-[-0.02em] text-ink">{value}</span>
        <span className="mt-2 block truncate text-[14px] text-muted">{sub}</span>
      </span>
      <ChevronRight className="h-5 w-5 shrink-0 text-muted transition-transform group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

/** The Command Centre (2026-10 mockup): a greeting, Ask Weza, four counts that open the work behind them, and
 * the cases that need someone now. Every number is a count WEZA holds — nothing is projected. */
export default function CommandCentre() {
  const { me } = useMe();
  const cc = useApi<any>("/inst/command-centre");
  const first = me.full_name.split(/\s+/)[0] || me.full_name;

  const hero = (
    <div className="pt-4 text-center sm:pt-8">
      <h1 className="font-serif text-[40px] font-semibold leading-tight tracking-[-0.02em] text-ink sm:text-[52px]">
        Hello, <span className="text-blue-600">{first}</span>
      </h1>
      <p className="mx-auto mt-3 max-w-2xl text-[16px] text-muted sm:text-[18px]">Manage credit opportunities, products and appetite across your institution.</p>
    </div>
  );

  if (me.institution && me.institution.status !== "ACTIVE")
    return (
      <div className="space-y-8">
        {hero}
        <Banner tone="gold" title="Your workspace isn't live yet" className="mx-auto max-w-3xl">Complete the activation checklist to start receiving qualified opportunities.</Banner>
        <div className="text-center"><Button href="/institution/onboarding">Open activation checklist</Button></div>
      </div>
    );

  const d = cc.data;
  const k = d?.kpis;
  const cases: any[] = d?.attention || [];

  return (
    <div className="space-y-8">
      {hero}
      <InstitutionAskPanel />

      {cc.loading && !d ? <Loading rows={4} /> : cc.error ? <ErrorState error={cc.error} onRetry={cc.reload} /> : (
        <>
          {d.no_lead && (
            <Banner tone="info" title="No opportunities in your queue right now">
              {d.no_lead.text} <Link href={d.no_lead.link} className="font-medium underline">Explore</Link>
            </Banner>
          )}

          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Tile href="#urgent-cases" icon={Bell} tint="bg-danger-bg text-danger" label="Needs attention" value={k.attention}
              sub={k.attention_high ? `${k.attention_high} high priority` : "Nothing high priority"} />
            <Tile href="/institution/feed" icon={Target} tint="bg-blue-50 text-blue-600" label="New opportunities" value={k.new_24h}
              sub={<><span className="font-medium text-success">+{k.new_7d}</span> this week</>} />
            <Tile href="/institution/products" icon={Box} tint="bg-violet-bg text-violet" label="Active product" value={k.active_products}
              sub={`of ${k.products_total} product${k.products_total === 1 ? "" : "s"}`} />
            <Tile href="/institution/appetite" icon={Database} tint="bg-teal-bg text-teal" label="Active appetite" value={k.active_mandates}
              sub={`of ${k.mandates_total} mandate${k.mandates_total === 1 ? "" : "s"}`} />
          </div>

          <div id="urgent-cases" className="scroll-mt-24">
            <Card title="Urgent cases" action={<Button variant="secondary" size="sm" href="/institution/feed">View all <ChevronRight className="h-4 w-4" /></Button>}>
              {cases.length === 0 ? (
                <p className="py-6 text-center text-[15px] text-muted">Nothing urgent. Nicely done.</p>
              ) : (
                <div className="-mx-6 -mb-6 overflow-hidden rounded-b-2xl border-t border-line">
                  <Table bare head={["Ref", "Customer", "Product", "Issue", "Priority", "Assigned to", "Updated", ""]}>
                    {cases.map((c, i) => {
                      const [label, tone] = PRIORITY[c.severity] || PRIORITY.low;
                      const href = c.id ? `/institution/opportunities/${c.id}` : c.link;
                      return (
                        <tr key={c.id || `${c.kind}-${i}`}>
                          <Td><Link href={href} className="num font-medium text-blue-600 hover:underline">{c.reference ? `#${c.reference}` : "—"}</Link></Td>
                          <Td className="text-ink">{c.customer || "—"}</Td>
                          <Td className="text-ink">{c.product || "—"}</Td>
                          <Td className="text-ink">{c.issue || c.text}</Td>
                          <Td><Badge tone={tone}>{label}</Badge></Td>
                          <Td>
                            {c.owner ? (
                              <span className="flex items-center gap-2.5 whitespace-nowrap text-ink">
                                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#5b7bb5] text-[12px] font-semibold text-white">{initials(c.owner)}</span>
                                {c.owner}
                              </span>
                            ) : <span className="text-muted">Unassigned</span>}
                          </Td>
                          <Td className="whitespace-nowrap text-muted">{c.updated_at ? ago(c.updated_at) : "—"}</Td>
                          <Td className="w-12 text-right">
                            <Link href={href} aria-label={`Open ${c.reference || "case"}`} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-canvas hover:text-ink">
                              <MoreVertical className="h-4 w-4" />
                            </Link>
                          </Td>
                        </tr>
                      );
                    })}
                  </Table>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
