"use client";

import Link from "next/link";
import {
  ArrowRight, Briefcase, Building2, ChevronRight, Clock, Factory, GraduationCap, HeartPulse, MessageCircle,
  PhoneCall, ShieldAlert, Sprout, Store, Truck, UserRound, Utensils, Zap,
} from "lucide-react";
import { useApi } from "@/lib/hooks";
import { ago, moneyFull } from "@/lib/format";
import { Badge, Banner, Button, cx, ErrorState, Loading, PageHeader } from "@/components/ui";

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

/** Priority opportunities and the needs-attention queue — moved here from the Command Centre, which now only
 * points to them. Both come from the same /inst/command-centre summary, scoped to what this person may see. */
export default function Priority() {
  const cc = useApi<any>("/inst/command-centre");
  const d = cc.data;
  const priority: any[] = d?.priority || [];
  const attention: any[] = d?.attention || [];

  return (
    <>
      <PageHeader title="Priority" subtitle="The strongest matches for your products and mandates, and what needs someone's attention now." />
      {cc.loading && !d ? <Loading rows={4} /> : cc.error ? <ErrorState error={cc.error} onRetry={cc.reload} /> : (
        <div className="space-y-6">
          {d.no_lead && (
            <Banner tone="info" title="No opportunities in your queue right now">
              {d.no_lead.text} <Link href={d.no_lead.link} className="font-medium underline">Explore</Link>
            </Banner>
          )}

          <div className="grid items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_400px]">
            <section aria-labelledby="priority-heading" className="rounded-xl border border-line bg-surface">
              <header className="flex flex-wrap items-start justify-between gap-4 px-6 pb-4 pt-6">
                <div>
                  <h2 id="priority-heading" className="text-[22px] font-bold leading-8 tracking-[-0.01em] text-ink">Priority opportunities</h2>
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

            <section id="needs-attention" aria-labelledby="attention-heading" className="scroll-mt-28 rounded-xl border border-line bg-surface">
              <header className="px-6 pb-3 pt-6">
                <h2 id="attention-heading" className="text-[22px] font-bold leading-8 tracking-[-0.01em] text-ink">Needs attention</h2>
                <p className="mt-1 text-[15px] text-muted">Items that require your review or input.</p>
              </header>
              {attention.length === 0 ? (
                <p className="px-6 pb-8 pt-2 text-[15px] text-muted">Nothing needs your attention. Nicely done.</p>
              ) : (
                <ul className="mx-6 mb-3 divide-y divide-line border-t border-line">
                  {attention.map((a, i) => {
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
        </div>
      )}
    </>
  );
}
