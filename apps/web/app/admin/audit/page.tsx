"use client";

import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { Badge, ErrorState, Input, Loading, PageHeader, Table, Td } from "@/components/ui";

export default function AuditLog() {
  const [action, setAction] = useState("");
  const r = useApi<any>(`/admin/audit?limit=300${action ? `&action=${encodeURIComponent(action)}` : ""}`, [action]);
  return (
    <>
      <PageHeader title="Audit trail" subtitle="Append-only (database-enforced). Actor, action, object, before/after, reason and correlation ID." />
      <Input className="mb-4 !w-80" placeholder="Filter action, e.g. consent, kill_switch, product" value={action} onChange={(e) => setAction(e.target.value)} />
      {r.loading && !r.data ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : (
        <Table head={["When", "Actor", "Institution", "Action", "Object", "Reason", "Change"]} empty={r.data.events.length === 0}>
          {r.data.events.map((a: any, i: number) => (
            <tr key={i}>
              <Td className="whitespace-nowrap">{dateTime(a.at)}</Td>
              <Td className="text-[13px]">{a.actor}<div className="text-[11px] text-muted">{a.actor_type}</div></Td>
              <Td className="text-[13px]">{a.institution || "—"}</Td>
              <Td><Badge tone="muted">{a.action}</Badge></Td>
              <Td className="text-[12px]">{a.object}<div className="text-muted">{a.object_id?.slice(0, 13)}</div></Td>
              <Td className="text-[12px] text-muted">{a.reason || "—"}</Td>
              <Td className="max-w-xs truncate text-[11px] text-muted">{a.after ? JSON.stringify(a.after) : ""}</Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
