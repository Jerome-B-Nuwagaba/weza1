"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { Badge, ErrorState, Loading, PageHeader, StateBadge, Table, Tabs, Td } from "@/components/ui";

export default function Audit() {
  const a = useApi<any>("/inst/audit");
  const [tab, setTab] = useState("access");
  if (a.loading) return <Loading />;
  if (a.error) return <ErrorState error={a.error} />;
  const d = a.data;
  return (
    <>
      <PageHeader title="Consent & access log" subtitle="Every view of identifiable customer data is evaluated by the policy decision point and logged." />
      <Tabs tabs={[["access", "Data access decisions"], ["consents", "Consents"], ["audit", "Audit trail"]]} value={tab} onChange={setTab} />
      {tab === "access" && (
        <Table head={["When", "Actor", "Resource", "Decision", "Fields disclosed"]}>
          {d.access.map((x: any, i: number) => <tr key={i}><Td>{dateTime(x.at)}</Td><Td className="text-[12px]">{x.actor}</Td><Td className="text-[12px]">{x.resource}</Td><Td><Badge tone={x.result === "PERMIT" ? "success" : x.result === "DENY" ? "danger" : "warning"}>{x.result.replace(/_/g, " ").toLowerCase()}</Badge></Td><Td className="text-[12px] text-muted">{x.fields.join(", ") || "—"}</Td></tr>)}
        </Table>
      )}
      {tab === "consents" && (
        <Table head={["Granted", "Status", "Version", "Categories", "Withdrawn"]}>
          {d.consents.map((c: any) => <tr key={c.id}><Td>{dateTime(c.granted_at)}</Td><Td><StateBadge state={c.status} /></Td><Td>{c.version}</Td><Td className="text-[12px]">{c.categories.join(", ").toLowerCase()}</Td><Td>{c.withdrawn_at ? dateTime(c.withdrawn_at) : "—"}</Td></tr>)}
        </Table>
      )}
      {tab === "audit" && (
        <Table head={["When", "Actor", "Action", "Object", "Reason"]}>
          {d.audit.map((x: any, i: number) => <tr key={i}><Td>{dateTime(x.at)}</Td><Td>{x.actor}</Td><Td><Badge tone="muted">{x.action}</Badge></Td><Td className="text-[12px]">{x.object}</Td><Td className="text-[12px] text-muted">{x.reason || "—"}</Td></tr>)}
        </Table>
      )}
    </>
  );
}
