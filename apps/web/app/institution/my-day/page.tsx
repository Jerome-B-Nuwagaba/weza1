"use client";

import { useApi } from "@/lib/hooks";
import { OpportunityRow } from "@/components/opportunity";
import { useMe } from "@/components/StaffShell";
import { Card, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";

export default function MyDay() {
  const { me } = useMe();
  const d = useApi<any>("/inst/my-day");
  if (d.loading) return <Loading />;
  if (d.error) return <ErrorState error={d.error} onRetry={d.reload} />;
  const s = d.data.sections;
  const total = Object.values(d.data.counts).reduce((a: number, b: any) => a + b, 0);
  return (
    <>
      <PageHeader title="My Day" subtitle={`${me.full_name.split(" ")[0]}, ${total} open opportunit${total === 1 ? "y" : "ies"} assigned to you. ${d.data.ordering}`} />
      {total === 0 ? <EmptyState title="Nothing assigned to you right now">New opportunities assigned by your routing rules will appear here.</EmptyState> : (
        <div className="space-y-5">
          {[["new", "Contact first", "New and assigned — the service-target clock is running."], ["follow_up", "Follow up", "Contacted or in your internal process."], ["awaiting_outcome", "Report the outcome", "Submitted internally or approved — record what happened."]].map(([k, t, sub]) => s[k].length > 0 && (
            <Card key={k} title={`${t} (${s[k].length})`} subtitle={sub} className="overflow-hidden">
              <div className="-m-5">{s[k].map((o: any) => <OpportunityRow key={o.id} o={o} compact />)}</div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
