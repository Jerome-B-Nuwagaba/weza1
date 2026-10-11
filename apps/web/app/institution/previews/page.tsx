"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Badge, Banner, Button, EmptyState, ErrorState, Loading, PageHeader, StateBadge } from "@/components/ui";

export default function Previews() {
  const { can } = useMe();
  const p = useApi<any>("/inst/previews");
  async function interest(id: string, state: string) {
    await api(`/inst/previews/${id}/interest`, { body: { state } });
    p.reload();
  }
  return (
    <>
      <PageHeader title="Opportunity Previews" subtitle="Non-identifiable demand matching your active appetite. Interest is not approval and never reveals who the customer is." />
      <Banner tone="info" className="mb-4">If you mark interest, the customer is told that an institution is interested and decides whether to share their details with you.</Banner>
      {p.loading ? <Loading /> : p.error ? <ErrorState error={p.error} /> : !p.data.enabled ? <EmptyState title="Previews are not enabled for this marketplace" /> : p.data.previews.length === 0 ? <EmptyState title="No previews right now" /> : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {p.data.previews.map((x: any) => (
            <div key={x.id} className="rounded-xl border border-line bg-surface p-4">
              <div className="flex items-center justify-between"><span className="text-lg font-semibold">{x.amount_band}</span><Badge tone={x.match_band === "90+" ? "gold" : "neutral"}>Match {x.match_band}</Badge></div>
              <div className="mt-1 text-[14px]">{x.purpose_category?.replace(/_/g, " ")} · {x.customer_type} · {x.sector?.replace(/_/g, " ") || "—"}</div>
              <div className="text-[13px] text-muted">{x.region || "Region withheld"} · {x.readiness === "READY" ? "Ready" : "Almost ready"} · expires {date(x.expires_at)}</div>
              <div className="mt-3 flex items-center gap-2">
                {x.interest === "PENDING" && can("preview.interest") ? (
                  <><Button size="sm" onClick={() => interest(x.id, "INTERESTED")}>Interested</Button><Button size="sm" variant="secondary" onClick={() => interest(x.id, "NEED_MORE_INFORMATION")}>Need more info</Button><Button size="sm" variant="ghost" onClick={() => interest(x.id, "NOT_INTERESTED")}>Pass</Button></>
                ) : <StateBadge state={x.interest === "INTERESTED" ? "ACTIVE" : "DRAFT"} label={x.interest.replace(/_/g, " ").toLowerCase()} />}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
