"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Bar, Button, EmptyState, ErrorState, Loading, PageHeader, StateBadge } from "@/components/ui";

export default function Appetites() {
  const { can } = useMe();
  const a = useApi<any>("/inst/appetites");
  return (
    <>
      <PageHeader title="Appetite Studio" subtitle="Products are what you can offer. Appetite is what customers you want WEZA to find right now." actions={can("appetite.edit") && <Button href="/institution/appetite/new">New appetite</Button>} />
      {a.loading ? <Loading /> : a.error ? <ErrorState error={a.error} onRetry={a.reload} /> : a.data.appetites.length === 0 ? (
        <EmptyState title="No appetite configured" action={can("appetite.edit") && <Button href="/institution/appetite/new">Define your first mandate</Button>}>Tell WEZA what customers you want — then simulate against real anonymised demand.{!can("appetite.edit") && " Appetite is defined by a Business/Product or Credit/Risk lead — add one under Users & roles if your institution has none yet."}</EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {a.data.appetites.map((x: any) => (
            <Link key={x.id} href={`/institution/appetite/${x.id}`} className="rounded-xl border border-line bg-surface p-5 hover:border-blue-400">
              <div className="flex items-start justify-between gap-2">
                <div className="font-semibold text-ink">{x.name}</div>
                <div className="flex gap-1"><StateBadge state={x.lifecycle_status} />{x.lifecycle_status === "ACTIVE" && <StateBadge state={x.capacity_state} label={`Capacity ${x.capacity_state.toLowerCase()}`} />}</div>
              </div>
              <div className="mt-1 text-[13px] text-muted">v{x.active_version ?? x.latest_version} · {x.criteria} criteria · min match {x.min_match_score}{x.latest_status !== "APPROVED" && x.latest_version !== x.active_version ? ` · v${x.latest_version} ${x.latest_status.toLowerCase()}` : ""}</div>
              {x.target_count && (
                <div className="mt-3">
                  <div className="mb-1 flex justify-between text-[12px] text-muted"><span>Fulfilled {x.fulfilled_count} of {x.target_count}</span><span>{money(x.fulfilled_value)}</span></div>
                  <Bar value={x.fulfilled_count} max={x.target_count} tone="gold" />
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
