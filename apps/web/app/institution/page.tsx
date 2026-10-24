"use client";

import Link from "next/link";
import { AlertCircle, ArrowRight, Box, CheckCircle2, FileText, Lightbulb, Rocket, Target, TrendingUp } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { useMe } from "@/components/StaffShell";
import { InstitutionAskPanel } from "@/components/InstitutionAskPanel";
import { Button, cx } from "@/components/ui";

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

type Insight = { key: string; icon: any; tint: string; title: string; text: string; href: string; cta: string };

/** At most three pointers into the workspace, most pressing first. Each one leads to the page that owns the work;
 * the Command Centre never repeats that page's content. */
function insightsFrom(d: any, can: (p: string) => boolean): Insight[] {
  const k = d.kpis || {};
  const out: Insight[] = [];
  if (k.attention > 0)
    out.push({ key: "attention", icon: AlertCircle, tint: "bg-danger-bg text-danger-dot",
      title: `${plural(k.attention, "item needs", "items need")} attention`,
      text: k.attention_high > 0 ? `${plural(k.attention_high, "is", "are")} urgent — unassigned or past the first-contact target.` : "Assignments, first contact or inactive opportunities to review.",
      href: "/institution/priority#needs-attention", cta: "Review" });
  if (k.new_24h > 0)
    out.push({ key: "new", icon: FileText, tint: "bg-leaf-tint text-olive",
      title: `${plural(k.new_24h, "new opportunity", "new opportunities")} today`,
      text: "Matched to your mandate in the last 24 hours.", href: "/institution/priority", cta: "See priority" });
  if (!k.featured_product && can("product.read"))
    out.push({ key: "product", icon: Box, tint: "bg-warning-bg text-warning-dot", title: "No product is live yet",
      text: "Customers are matched only to active products.", href: "/institution/products", cta: "Open products" });
  else if (!k.featured_mandate && can("appetite.read"))
    out.push({ key: "mandate", icon: Target, tint: "bg-warning-bg text-warning-dot", title: "No mandate is live yet",
      text: "A live mandate tells WEZA which customers to route to you.", href: "/institution/appetite", cta: "Open mandates" });
  if (d.no_lead && can("analytics.read"))
    out.push({ key: "no-lead", icon: TrendingUp, tint: "bg-info-bg text-info-dot", title: "Demand just outside your mandate",
      text: d.no_lead.text, href: d.no_lead.link, cta: "Explore" });
  if (d.insights_open > 0 && can("analytics.read"))
    out.push({ key: "recommendations", icon: Lightbulb, tint: "bg-leaf-tint text-olive",
      title: `${plural(d.insights_open, "recommendation", "recommendations")} to review`,
      text: "Suggestions from your outcomes and market demand.", href: "/institution/insights", cta: "Review" });
  return out.slice(0, 3);
}

/** The questions offered under Ask Weza: only ones this role can get an answer to. */
function suggestionsFor(d: any | undefined, can: (p: string) => boolean): string[] {
  const s: string[] = [];
  if (can("opportunity.read_meta")) s.push("Show opportunities requiring my review");
  const top = d?.priority?.[0];
  if (can("opportunity.read_meta") && top?.reference) s.push(`Explain why ${top.reference} was matched`);
  if (can("product.read")) s.push("Which of our products are active?");
  if (can("opportunity.read_meta")) s.push("Show current team workload");
  return s.slice(0, 4);
}

function InsightRow({ item }: { item: Insight }) {
  const Icon = item.icon;
  return (
    <li>
      <Link href={item.href}
        className="group flex items-center gap-4 rounded-xl px-4 py-4 transition-colors hover:bg-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-evergreen">
        <span className={cx("flex h-11 w-11 shrink-0 items-center justify-center rounded-full", item.tint)}><Icon className="h-5 w-5" strokeWidth={1.75} aria-hidden /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-[16px] font-semibold leading-6 text-ink">{item.title}</span>
          <span className="line-clamp-2 block text-[14px] leading-5 text-muted">{item.text}</span>
        </span>
        <span className="hidden shrink-0 items-center gap-1.5 text-[14px] font-medium text-evergreen sm:inline-flex">
          {item.cta}<ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </span>
        <ArrowRight className="h-5 w-5 shrink-0 text-evergreen sm:hidden" aria-hidden />
      </Link>
    </li>
  );
}

/** The Command Centre: the calm front door to the workspace. A greeting, Ask Weza, a few suggestions it can
 * answer for this role, and up to three insights that each link to where the work lives. Opportunity tables,
 * products and mandates live in their own sections (Opportunities › Priority & attention, Products & Appetite). */
export default function CommandCentre() {
  const { me, can } = useMe();
  const live = !me.institution || me.institution.status === "ACTIVE";
  const cc = useApi<any>(live ? "/inst/command-centre" : null);
  const first = me.full_name.split(/\s+/)[0] || me.full_name;
  const d = cc.data;

  let below: React.ReactNode;
  if (!live) {
    below = (
      <ul className="divide-y divide-line">
        <InsightRow item={{ key: "activation", icon: Rocket, tint: "bg-warning-bg text-warning-dot", title: "Your workspace isn't live yet",
          text: "Complete the activation checklist to start receiving qualified opportunities.", href: "/institution/onboarding", cta: "Open checklist" }} />
      </ul>
    );
  } else if (cc.loading && !d) {
    below = (
      <div className="space-y-2 p-2" aria-busy="true" aria-label="Loading insights">
        {[0, 1, 2].map((i) => <div key={i} className="skeleton h-16 w-full rounded-xl" />)}
      </div>
    );
  } else if (cc.error) {
    below = (
      <div className="flex flex-col items-center gap-3 px-4 py-6 text-center" role="alert">
        <p className="text-[15px] text-muted">We couldn't load insights from your workspace. Ask Weza and every section still work.</p>
        <Button size="sm" variant="secondary" onClick={cc.reload}>Try again</Button>
      </div>
    );
  } else {
    const items = insightsFrom(d, can);
    below = items.length ? (
      <ul className="divide-y divide-line">{items.map((i) => <InsightRow key={i.key} item={i} />)}</ul>
    ) : (
      <div className="flex items-center gap-4 px-4 py-5">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-leaf-tint text-olive"><CheckCircle2 className="h-5 w-5" strokeWidth={1.75} aria-hidden /></span>
        <span className="text-[15px] text-muted">You're up to date. New matches will appear in{" "}
          <Link href="/institution/feed" className="font-medium text-evergreen underline-offset-2 hover:underline">Opportunities</Link>.</span>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col items-center pb-10 pt-4 text-center sm:pt-12 2xl:pt-20">
      <h1 className="text-[32px] font-bold leading-tight tracking-[-0.02em] text-evergreen sm:text-[44px]">{greeting()}, {first}</h1>
      <p className="mt-2 max-w-xl text-[17px] text-muted sm:text-[19px]">
        Ask about your opportunities, products and team — or tell Weza where you'd like to start.
      </p>

      <div className="mt-8 w-full sm:mt-10">
        <InstitutionAskPanel suggestions={live ? suggestionsFor(d, can) : []} />
      </div>

      <section aria-labelledby="workspace-insights" className="mt-10 w-full text-left sm:mt-12">
        <h2 id="workspace-insights" className="mb-2 px-1 text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">Insights from your workspace</h2>
        <div className="rounded-2xl border border-line bg-surface p-1.5">{below}</div>
      </section>
    </div>
  );
}
