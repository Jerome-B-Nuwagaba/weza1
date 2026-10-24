"use client";

import { useApi } from "@/lib/hooks";
import { OpportunityRow } from "@/components/opportunity";
import { Badge, Card, ErrorState, Loading, PageHeader, Table, Td } from "@/components/ui";

export default function Team() {
  const t = useApi<any>("/inst/team");
  if (t.loading) return <Loading />;
  if (t.error) return <ErrorState error={t.error} />;
  const officers = t.data.members.filter((m: any) => m.role_set?.includes("OFFICER") || m.role_set?.includes("MANAGER"));
  return (
    <>
      <PageHeader title="Team" subtitle="Distribution, contact performance, ageing and service-target breaches. Reassign from any opportunity." />
      <Table head={["Officer", "Team", "Open", "Ageing <1d / 1–3d / 3–7d / >7d", "Contact rate (30d)", "Breaches"]}>
        {officers.map((m: any) => (
          <tr key={m.id}>
            <Td><div className="font-medium">{m.name}</div><div className="text-[12px] text-muted">{m.roles.join(", ").toLowerCase()}</div></Td>
            <Td>{m.team || "—"}</Td>
            <Td className="num font-semibold">{m.open}</Td>
            <Td className="num">{m.aging["<1d"]} / {m.aging["1-3d"]} / {m.aging["3-7d"]} / <span className={m.aging[">7d"] ? "text-danger" : ""}>{m.aging[">7d"]}</span></Td>
            <Td className="num">{m.contact_rate !== null ? `${m.contact_rate}%` : "—"}</Td>
            <Td>{m.breached ? <Badge tone="danger">{m.breached}</Badge> : <span className="text-muted">0</span>}</Td>
          </tr>
        ))}
      </Table>
      <Card title={`Unassigned high-match opportunities (${t.data.unassigned_high_match.length})`} className="mt-6 overflow-hidden">
        {t.data.unassigned_high_match.length === 0 ? <p className="text-[14px] text-muted">None — good.</p> : <div className="-m-5">{t.data.unassigned_high_match.map((o: any) => <OpportunityRow key={o.id} o={o} compact />)}</div>}
      </Card>
    </>
  );
}
