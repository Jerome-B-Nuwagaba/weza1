"use client";

import { useState } from "react";
import { ActionError } from "@/components/ActionError";
import { useMe } from "@/components/StaffShell";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Table, Tabs, Td } from "@/components/ui";

export default function Deliveries() {
  const [status, setStatus] = useState("DEAD");
  const r = useApi<any>(`/admin/deliveries?status=${status}`, [status]);
  const { can } = useMe();
  const [err, setErr] = useState<ApiError | null>(null);
  async function replay(id: string) {
    setErr(null);
    try {
      await api(`/admin/deliveries/${id}/replay`, { method: "POST" });
      r.reload();
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <>
      <PageHeader title="Events & delivery" subtitle="Transactional outbox → consumers with bounded retry → dead letter. Replays are safe: consumers are idempotent." />
      <ActionError error={err} className="mb-4" />
      <Tabs tabs={[["DEAD", "Dead-lettered"], ["PENDING", "Pending / retrying"], ["DONE", "Delivered (recent)"]]} value={status} onChange={setStatus} />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : (
        <>
          {r.data.deliveries.length === 0 ? <EmptyState title={status === "DEAD" ? "No dead letters" : "Nothing here"} /> : (
            <Table head={["Event", "Consumer", "Attempts", "Error", "At", ""]}>
              {r.data.deliveries.map((d: any) => (
                <tr key={d.id}>
                  <Td>{d.event}</Td>
                  <Td>{d.consumer} {d.critical && <Badge tone="danger">critical</Badge>}</Td>
                  <Td className="num">{d.attempts}</Td>
                  <Td className="max-w-sm truncate text-[12px] text-muted">{d.error || "—"}</Td>
                  <Td>{dateTime(d.at)}</Td>
                  <Td>{can("admin.review") && d.status !== "DONE" && <Button size="sm" variant="secondary" onClick={() => replay(d.id)}>Replay</Button>}</Td>
                </tr>
              ))}
            </Table>
          )}
          <Card title="Notification failures" className="mt-4">
            {r.data.notification_failures.length === 0 ? <p className="text-[14px] text-muted">None.</p> : <ul className="space-y-1 text-[13px]">{r.data.notification_failures.map((n: any) => <li key={n.id}>{n.title} · {n.channel} · {n.status} · {n.error}</li>)}</ul>}
          </Card>
        </>
      )}
    </>
  );
}
