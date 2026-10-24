"use client";

import Link from "next/link";
import {
  AlertCircle, ArrowRight, Box, Briefcase, Building2, ChevronRight, Clock, Factory, FileText, GraduationCap,
  HeartPulse, MessageCircle, PhoneCall, ShieldAlert, Sprout, Store, Target, Truck, UserRound, Utensils, Zap,
} from "lucide-react";
import { useApi } from "@/lib/hooks";
import { ago, moneyFull } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { InstitutionAskPanel } from "@/components/InstitutionAskPanel";
import { Badge, Banner, Button, cx, ErrorState, Loading } from "@/components/ui";

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

const initials = (text: string) =>
  text.split(/[\s·]+/).filter((w) => /^[A-Za-z]/.test(w)).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "W";

/** The sector glyph shown beside each priority opportunity. */
function sectorIcon(key?: string | null) {
  const k = (key || "").toLowerCase();
  if (/agri|farm/.test(k)) return Sprout;
  if (/energy|solar/.test(k)) return Zap;
  if (/food|restaurant|hospitality|catering/.test(k)) return Utensils;
  if (/manufactur/.test(k)) return Factory;
  if (/retail|wholesale|trade/.test(k)) return Store;
  if (/health|pharma|clinic/.test(k)) return HeartPulse;
  if (/transport|logistic/.test(k)) return Truck;
  if (/educat|school/.test(k)) return GraduationCap;
  if (/service/.test(k)) return Briefcase;
  return Building2;
}

const MATCH: Record<string, [string, string]> = {
  HIGH: ["High match", "success"], GOOD: ["Good match", "warning"], UNDER_REVIEW: ["Under review", "neutral"],
};

/** Each "needs attention" item, phrased as the action it asks for. */
function attentionItem(a: any): { icon: any; tint: string; title: string; text: string } {
  const who = [a.reference, a.product || a.customer].filter(Boolean).join(" · ");
  if (a.kind === "UNASSIGNED") return { icon: UserRound, tint: "bg-warning-bg text-warning-dot", title: "Assign an officer", text: `${who} is waiting for an owner.` };
  if (a.kind === "SERVICE_TARGET")
    return a.severity === "high"
      ? { icon: PhoneCall, tint: "bg-danger-bg text-danger-dot", title: "Make first contact", text: `${who} — first contact is overdue.` }
      : { icon: PhoneCall, tint: "bg-warning-bg text-warning-dot", title: "Make first contact", text: `${who} — first contact is due soon.` };
  if (a.kind === "ON_HOLD") return { icon: ShieldAlert, tint: "bg-info-bg text-info-dot", title: "On hold", text: `${who} is held pending WEZA checks.` };
  if (a.kind === "STALE") return { icon: Clock, tint: "bg-warning-bg text-warning-dot", title: "Review inactive opportunities", text: a.text };
  return { icon: MessageCircle, tint: "bg-info-bg text-info-dot", title: a.action || "Review", text: a.text };
}

function Tile({ href, icon: Icon, tint, label, children, sub }: {
  href: string; icon: any; tint: string; label: string; children: React.ReactNode; sub: React.ReactNode;
}) {
  return (
    <Link href={href} className="group flex min-w-0 items-start gap-4 rounded-xl border border-line bg-surface p-5 transition-colors hover:border-[#b9cbc2] 2xl:gap-5 2xl:p-6">
      <span className={cx("flex h-14 w-14 shrink-0 items-center justify-center rounded-full 2xl:h-16 2xl:w-16", tint)}>
        <Icon className="h-6 w-6 2xl:h-7 2xl:w-7" strokeWidth={1.75} aria-hidden />
      </span>
      <span className="min-w-0 flex-1 pt-0.5">
        <span className="flex items-start justify-between gap-2">
          <span className="text-[17px] font-medium leading-6 text-ink">{label}</span>
          <ChevronRight className="mt-0.5 h-5 w-5 shrink-0 text-muted transition-transform group-hover:translate-x-0.5" strokeWidth={2} aria-hidden />
        </span>
        <span className="mt-1.5 block">{children}</span>
        <span className="mt-1.5 block text-[15px] leading-5 text-muted">{sub}</span>
      </span>
    </Link>
  );
}

/** The Command Centre, as designed in "WEZA Command Centre navigation update": a greeting, Ask Weza, four tiles
 * (new opportunities, needs attention, the active product, the active mandate), the priority opportunities and
 * what needs attention. Every figure is a count or record WEZA holds. */
export default function CommandCentre() {
  const { me } = useMe();
  const cc = useApi<any>("/inst/command-centre");
  const first = me.full_name.split(/\s+/)[0] || me.full_name;

  const hero = (
    <div>
      <h1 className="text-[34px] font-bold leading-tight tracking-[-0.02em] text-evergreen sm:text-[44px]">{greeting()}, {first}</h1>
      <p className="mt-1.5 text-[18px] text-muted sm:text-[22px]">Your institution workspace, ready for today.</p>
    </div>
  );

  if (me.institution && me.institution.status !== "ACTIVE")
    return (
      <div className="space-y-8">
        {hero}
        <Banner tone="gold" title="Your workspace isn't live yet">Complete the activation checklist to start receiving qualified opportunities.</Banner>
        <Button href="/institution/onboarding">Open activation checklist</Button>
      </div>
    );

  const d = cc.data;
  const k = d?.kpis;
  const priority: any[] = d?.priority || [];
  const attention: any[] = d?.attention || [];
  const regions: string[] = k?.featured_mandate?.regions || [];

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

          <div className="grid gap-5 sm:grid-cols-2 2xl:grid-cols-4">
            <Tile href="/institution/feed" icon={FileText} tint="bg-leaf-tint text-olive" label="New opportunities"
              sub="Matched to your mandate">
              <span className="num block text-[32px] font-bold leading-none tracking-[-0.02em] text-ink 2xl:text-[34px]">{k.new_24h}</span>
            </Tile>
            <Tile href="#needs-attention" icon={AlertCircle} tint="bg-danger-bg text-danger-dot" label="Needs attention"
              sub="Require your review">
              <span className="num block text-[32px] font-bold leading-none tracking-[-0.02em] text-ink 2xl:text-[34px]">{k.attention}</span>
            </Tile>
            <Tile href={k.featured_product ? `/institution/products/${k.featured_product.id}` : "/institution/products"} icon={Box}
              tint="bg-leaf-tint text-olive" label="Active product"
              sub={!k.featured_product ? "No product is live yet" : k.featured_product.open_opportunities > 0 ? "Matched opportunities available" : "No matched opportunities yet"}>
              <span className="line-clamp-2 block text-[20px] font-bold leading-7 text-ink 2xl:text-[22px]">{k.featured_product?.name || "None active"}</span>
            </Tile>
            <Tile href={k.featured_mandate ? `/institution/appetite/${k.featured_mandate.id}` : "/institution/appetite"} icon={Target}
              tint="bg-leaf-tint text-olive" label="Active mandate"
              sub={!k.featured_mandate ? "No mandate is live yet" : regions.length ? `Across ${regions.join(", ").replace(/, ([^,]*)$/, " and $1")}` : "Across all regions"}>
              <span className="line-clamp-2 block text-[20px] font-bold leading-7 text-ink 2xl:text-[22px]">{k.featured_mandate?.name || "None active"}</span>
            </Tile>
          </div>

          <div className="grid items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_400px]">
            <section className="rounded-xl border border-line bg-surface">
              <header className="flex items-start justify-between gap-4 px-6 pb-4 pt-6">
                <div>
                  <h2 className="text-[24px] font-bold leading-8 tracking-[-0.01em] text-ink">Priority opportunities</h2>
                  <p className="mt-1 text-[15px] text-muted">Top matched opportunities based on your product, mandate and risk appetite.</p>
                </div>
                <Link href="/institution/feed" className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap py-1 text-[16px] font-medium text-evergreen hover:underline">
                  View all opportunities <ArrowRight className="h-5 w-5" strokeWidth={2} aria-hidden />
                </Link>
              </header>
              {priority.length === 0 ? (
                <p className="px-6 pb-8 pt-2 text-[15px] text-muted">No open opportunities yet.</p>
              ) : (
                <div className="mx-6 mb-6 overflow-x-auto rounded-lg border border-line scroll-thin">
                  <table className="w-full min-w-[600px] text-left">
                    <thead className="bg-soft text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">
                      <tr>
                        <th className="whitespace-nowrap px-4 py-3.5 font-semibold">Business name</th>
                        <th className="whitespace-nowrap px-4 py-3.5 font-semibold">Amount (UGX)</th>
                        <th className="whitespace-nowrap px-4 py-3.5 font-semibold">Sector</th>
                        <th className="whitespace-nowrap px-4 py-3.5 font-semibold">Match status</th>
                        <th className="whitespace-nowrap px-4 py-3.5 font-semibold">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {priority.map((o) => {
                        const Icon = sectorIcon(o.sector);
                        const [label, tone] = MATCH[o.match_status] || MATCH.GOOD;
                        const name = o.business_name || o.reference;
                        return (
                          <tr key={o.id}>
                            <td className="px-4 py-3.5">
                              <span className="flex items-center gap-4">
                                <span aria-hidden className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-evergreen text-[14px] font-semibold text-white">
                                  {initials(o.business_name || o.description)}
                                </span>
                                <span className="min-w-0">
                                  <span className="block truncate text-[15px] font-medium text-ink">{name}</span>
                                  <span className="block truncate text-[14px] text-muted">{o.business_name ? o.description : [o.description, o.need].filter(Boolean).join(" · ")}</span>
                                </span>
                              </span>
                            </td>
                            <td className="num whitespace-nowrap px-4 py-3.5 text-[15px] text-ink">{moneyFull(o.amount)}</td>
                            <td className="px-4 py-3.5">
                              <span className="flex items-center gap-2.5 whitespace-nowrap text-[15px] text-ink">
                                <Icon className="h-5 w-5 shrink-0 text-leaf" strokeWidth={2} aria-hidden />
                                {o.sector_label || "—"}
                              </span>
                            </td>
                            <td className="px-4 py-3.5"><Badge tone={tone} dot>{label}</Badge></td>
                            <td className="px-4 py-3.5"><Button size="sm" href={`/institution/opportunities/${o.id}`} aria-label={`Review ${name}`}>Review</Button></td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section id="needs-attention" className="scroll-mt-28 rounded-xl border border-line bg-surface">
              <header className="flex items-start justify-between gap-3 px-6 pb-3 pt-6">
                <div>
                  <h2 className="text-[24px] font-bold leading-8 tracking-[-0.01em] text-ink">Needs attention</h2>
                  <p className="mt-1 text-[15px] text-muted">Items that require your review or input.</p>
                </div>
                <Link href="/institution/feed" className="inline-flex shrink-0 items-center gap-2 whitespace-nowrap py-1 text-[16px] font-medium text-evergreen hover:underline">
                  View all <ArrowRight className="h-5 w-5" strokeWidth={2} aria-hidden />
                </Link>
              </header>
              {attention.length === 0 ? (
                <p className="px-6 pb-8 pt-2 text-[15px] text-muted">Nothing needs your attention. Nicely done.</p>
              ) : (
                <ul className="mx-6 mb-3 divide-y divide-line border-t border-line">
                  {attention.slice(0, 5).map((a, i) => {
                    const item = attentionItem(a);
                    const Icon = item.icon;
                    return (
                      <li key={a.id || `${a.kind}-${i}`}>
                        <Link href={a.id ? `/institution/opportunities/${a.id}` : a.link || "/institution/feed"}
                          className="group -mx-2 flex items-start gap-4 rounded-lg px-2 py-4 hover:bg-soft/70">
                          <span className={cx("flex h-12 w-12 shrink-0 items-center justify-center rounded-full", item.tint)}>
                            <Icon className="h-[22px] w-[22px]" strokeWidth={1.75} aria-hidden />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block text-[16px] font-semibold leading-6 text-ink">{item.title}</span>
                            <span className="block text-[14px] leading-5 text-muted">{item.text}</span>
                            {a.updated_at && <span className="mt-1 block text-[13px] text-muted">{ago(a.updated_at)}</span>}
                          </span>
                          <ChevronRight className="mt-3.5 h-5 w-5 shrink-0 text-muted" strokeWidth={2} aria-hidden />
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
