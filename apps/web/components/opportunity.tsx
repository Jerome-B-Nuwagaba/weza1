"use client";

import Link from "next/link";
import { money, minutesLabel, STATE_LABEL } from "@/lib/format";
import { Badge, cx, ScoreRing, StateBadge } from "./ui";

export function PriorityBadge({ p }: { p: string }) {
  if (p === "NORMAL") return null;
  return <Badge tone={p === "URGENT" ? "danger" : "gold"}>{p === "URGENT" ? "Urgent" : "High"}</Badge>;
}

/** Indicative terms an institution reported with an approval — always labelled as theirs, never a WEZA offer. */
export function TermsLine({ terms }: { terms: any }) {
  const parts = [
    terms.tenor_months && `${terms.tenor_months} months`,
    terms.interest_rate != null && `${terms.interest_rate}% ${terms.rate_period === "ANNUAL" ? "per year" : "per month"}`,
    terms.monthly_repayment != null && `${money(terms.monthly_repayment)}/month`,
    terms.fees != null && `fees ${money(terms.fees)}`,
  ].filter(Boolean);
  return (
    <div className="mt-1 rounded-lg bg-canvas px-3 py-2 text-[13px]">
      <div className="font-medium">Indicative terms{parts.length > 0 && `: ${parts.join(" · ")}`}</div>
      {terms.conditions && <div className="text-muted">Conditions: {terms.conditions}</div>}
      {terms.valid_until && <div className={terms.expired ? "text-danger" : "text-muted"}>{terms.expired ? "Expired" : "Valid until"} {terms.valid_until}</div>}
      <div className="text-[12px] italic text-muted">{terms.label}</div>
    </div>
  );
}

export function FreshnessBadge({ f }: { f: string }) {
  if (f === "FRESH") return null;
  return <Badge tone={f === "ATTENTION_REQUIRED" ? "warning" : "danger"}>{f === "ATTENTION_REQUIRED" ? "Needs attention" : f.toLowerCase()}</Badge>;
}

export function TargetBadge({ o }: { o: any }) {
  if (o.minutes_to_target === null || o.minutes_to_target === undefined) return null;
  const late = o.minutes_to_target < 0;
  const soon = !late && o.minutes_to_target < 120;
  return <Badge tone={late ? "danger" : soon ? "warning" : "muted"}>First contact {minutesLabel(o.minutes_to_target)}</Badge>;
}

export function OpportunityRow({ o, compact }: { o: any; compact?: boolean }) {
  return (
    <Link href={`/institution/opportunities/${o.id}`} className={cx("flex gap-4 border-b border-line px-4 py-3.5 last:border-0 hover:bg-canvas", o.match_score >= 90 && "bg-gold-100/30")}>
      <ScoreRing score={o.match_score} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="num font-semibold text-ink">{money(o.amount)}</span>
          <span className="truncate text-ink">{o.need || o.purpose_category}</span>
          <PriorityBadge p={o.priority} />
          <FreshnessBadge f={o.freshness} />
          {o.integrity_hold && <Badge tone="warning">On hold</Badge>}
          {o.is_demo && <Badge tone="muted">Demo</Badge>}
        </div>
        <div className="mt-0.5 text-[13px] text-muted">
          {o.reference} · {o.customer_type === "SME" ? "Business" : o.customer_type === "SALARIED" ? "Salaried" : o.customer_type === "AGRICULTURE" ? "Farmer" : "—"} · {o.sector?.replace(/_/g, " ") || "—"} · {o.district || "—"} · {o.product}
        </div>
        {!compact && o.why_matched?.length > 0 && <div className="mt-1 truncate text-[12.5px] text-muted">Why: {o.why_matched.slice(0, 4).join(" · ")}</div>}
      </div>
      <div className="hidden shrink-0 flex-col items-end gap-1 text-right sm:flex">
        <StateBadge state={o.state} label={STATE_LABEL[o.state]} />
        <TargetBadge o={o} />
        <span className="text-[12px] text-muted">{o.owner || "Unassigned"} · {o.next_action}</span>
      </div>
    </Link>
  );
}
