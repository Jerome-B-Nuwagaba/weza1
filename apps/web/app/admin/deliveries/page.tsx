"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, Table, Tabs, Td } from "@/components/ui";

export default function Deliveries() {
  const [status, setStatus] = useState("DEAD");
  const r = useApi<any>(`/admin/deliveries?status=${status}`, [status]);
  return (
    <>
      <PageHeader title="Events & delivery" subtitle="Transactional outbox → consumers with bounded retry → dead letter. Replays are safe: consumers are idempotent." />
      <Tabs tabs={[["DEAD", "Dead-lettered"], ["PENDING", "Pending / retrying"], ["DONE", "Delivered (recent)"]]} value={status} onChange={setStatus} />
      {r.loading ? <Loading /> : r.error ? <ErrorState error={r.error} /> : (
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
                  <Td>{d.status !== "DONE" && <Button size="sm" variant="secondary" onClick={async () => { await api(`/admin/deliveries/${d.id}/replay`, { method: "POST" }); r.reload(); }}>Replay</Button>}</Td>
                </tr>
              ))}
            </Table>
          )}
          <Card title="Notification failures" subtitle="Retries with backoff (1 min → 1 h), then dead-lettered. Replay gives a dead notification a fresh set of attempts." className="mt-4">
            {r.data.notification_failures.length === 0 ? <p className="text-[14px] text-muted">None.</p> : (
              <Table head={["Notification", "Channel", "Status", "Attempts", "Next attempt", "Error", ""]}>
                {r.data.notification_failures.map((n: any) => (
                  <tr key={n.id}>
                    <Td>{n.title}</Td>
                    <Td>{n.channel}</Td>
                    <Td><Badge tone={n.status === "DEAD" ? "danger" : "warning"}>{n.status.toLowerCase()}</Badge></Td>
                    <Td className="num">{n.attempts}</Td>
                    <Td>{n.next_attempt_at ? dateTime(n.next_attempt_at) : "—"}</Td>
                    <Td className="max-w-sm truncate text-[12px] text-muted">{n.error || "—"}</Td>
                    <Td>{n.status === "DEAD" && <Button size="sm" variant="secondary" onClick={async () => { await api(`/admin/notifications/${n.id}/replay`, { method: "POST" }); r.reload(); }}>Replay</Button>}</Td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </>
      )}
    </>
  );
}
