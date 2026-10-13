"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Banner, Button, ErrorState, Loading, PageHeader, Select, Table, Td, useToast } from "@/components/ui";

const LABELS: Record<string, string> = {
  OpportunityRouted: "New opportunity", HighMatchOpportunity: "High-match / high-value opportunity", OpportunityAssigned: "Assigned to me",
  ServiceTargetApproaching: "Service target approaching", ServiceTargetBreached: "Service target breached", DailyBrief: "WEZA Daily briefing", AppetiteInsight: "Appetite insight",
};

export default function Notifications() {
  const p = useApi<any>("/inst/notification-prefs");
  const [prefs, setPrefs] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => { if (p.data) setPrefs(p.data.prefs); }, [p.data]);
  if (p.loading) return <Loading />;
  if (p.error) return <ErrorState error={p.error} />;
  const set = (i: number, patch: any) => setPrefs(prefs.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  async function save() {
    try {
      p.setData(await api("/inst/notification-prefs", { method: "PUT", body: { prefs } }));
      toast("Notification preferences saved");
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  return (
    <>
      {node}
      <PageHeader title="Notification preferences" subtitle="Notifications are decision routing, not broadcasting: priority decides the channel, unacknowledged alerts escalate." actions={<Button onClick={save}>Save</Button>} />
      {!p.data.configured && <Banner tone="gold" className="mb-4">Defaults shown — save to confirm (required for activation).</Banner>}
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      <Table head={["Event", "In-app", "Email", "SMS", "Minimum priority", "Daily digest"]}>
        {prefs.map((x, i) => (
          <tr key={x.event_type}>
            <Td className="font-medium">{LABELS[x.event_type] || x.event_type}</Td>
            {["in_app", "email", "sms"].map((c) => (
              <Td key={c}><input type="checkbox" aria-label={c} checked={x.channels.includes(c)} disabled={c === "in_app"} onChange={(e) => set(i, { channels: e.target.checked ? [...x.channels, c] : x.channels.filter((y: string) => y !== c) })} /></Td>
            ))}
            <Td><Select value={x.min_priority} onChange={(e) => set(i, { min_priority: e.target.value })} options={[["NORMAL", "Normal"], ["HIGH", "High"], ["URGENT", "Urgent"]]} className="!h-8 !w-32" /></Td>
            <Td><input type="checkbox" aria-label="digest" checked={!!x.digest} onChange={(e) => set(i, { digest: e.target.checked })} /></Td>
          </tr>
        ))}
      </Table>
    </>
  );
}
