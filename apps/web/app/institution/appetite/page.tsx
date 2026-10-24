"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Bar, Button, EmptyState, ErrorState, Loading, PageHeader, StateBadge } from "@/components/ui";

const CUSTOMER_TYPE: Record<string, string> = {
  SME: "Business (SME)", SALARIED: "Salaried", AGRICULTURE: "Farmer",
};

const one = (v: any) => (Array.isArray(v) && v.length === 1 ? String(v[0]) : "");
const pair = (v: any) => (Array.isArray(v) && v.length === 2 ? [Number(v[0]), Number(v[1])] : null);
const text = (v: any) => (Array.isArray(v) ? v.map((x) => String(x).replace(/_/g, " ").toLowerCase()).join(", ") : v ? String(v).replace(/_/g, " ").toLowerCase() : "");

export default function Appetites() {
  const { can } = useMe();
  const a = useApi<any>("/inst/appetites");
  const routing = useApi<any>("/inst/routing");
  const teams: Record<string, string> = {};
  for (const t of routing.data?.teams || []) teams[t.id] = t.name;
  return (
    <>
      <PageHeader title="Appetite" subtitle="Define the customers you want WEZA to find right now. Each change is a new version; activation needs a second approver." actions={can("appetite.edit") && <Button href="/institution/appetite/new">New appetite</Button>} />
      {a.loading ? <Loading /> : a.error ? <ErrorState error={a.error} onRetry={a.reload} /> : a.data.appetites.length === 0 ? (
        <EmptyState title="No appetite configured" action={can("appetite.edit") && <Button href="/institution/appetite/new">Define your first mandate</Button>}>Tell WEZA what customers you want — then simulate against real anonymised demand.{!can("appetite.edit") && " Appetite is defined by a Business/Product or Credit/Risk lead — add one under Users & roles if your institution has none yet."}</EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {a.data.appetites.map((x: any) => {
            const range = pair(x.amount_range);
            return (
              <Link key={x.id} href={`/institution/appetite/${x.id}`} className="rounded-xl border border-line bg-surface p-5 hover:border-blue-400">
                <div className="flex items-start justify-between gap-2">
                  <div className="font-semibold text-ink">{x.name}</div>
                  <div className="flex gap-1"><StateBadge state={x.lifecycle_status} />{x.lifecycle_status === "ACTIVE" && <StateBadge state={x.capacity_state} label={`Capacity ${x.capacity_state.toLowerCase()}`} />}</div>
                </div>
                <div className="mt-1 text-[13px] text-muted">v{x.active_version ?? x.latest_version} · {x.criteria} criteria · min match {x.min_match_score}{x.latest_status !== "APPROVED" && x.latest_version !== x.active_version ? ` · v${x.latest_version} ${x.latest_status.toLowerCase()}` : ""}</div>
                {x.lifecycle_status === "ACTIVE" && x.demand?.message && <div className="mt-1 text-[13px] text-muted">{x.demand.message}</div>}
                <dl className="mt-3 space-y-1 text-[13px]">
                  <div className="flex gap-2"><dt className="text-muted">Products</dt><dd className="font-medium text-ink">{x.products?.length ? x.products.map((p: any) => p.name).join(", ") : "—"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Customer type</dt><dd className="font-medium text-ink">{one(x.customer_type) ? CUSTOMER_TYPE[one(x.customer_type)] || text(one(x.customer_type)) : "Any"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Sector</dt><dd className="font-medium text-ink">{text(x.sector) || "Any"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Geography</dt><dd className="font-medium text-ink">{text(x.region) || "Anywhere"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Amount range</dt><dd className="font-medium text-ink">{range ? `${money(range[0])} – ${money(range[1])}` : "Any"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Min. business age</dt><dd className="font-medium text-ink">{x.business_age_months ? `${x.business_age_months} months` : "Any"}</dd></div>
                  <div className="flex gap-2"><dt className="text-muted">Routing destination</dt><dd className="font-medium text-ink">{x.routing_team_id ? teams[x.routing_team_id] || "Team" : "Unassigned queue"}</dd></div>
                </dl>
                {x.target_count && (
                  <div className="mt-3">
                    <div className="mb-1 flex justify-between text-[12px] text-muted"><span>Fulfilled {x.fulfilled_count} of {x.target_count}</span><span>{money(x.fulfilled_value)}</span></div>
                    <Bar value={x.fulfilled_count} max={x.target_count} tone="gold" />
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </>
  );
}
