"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { Banner, Button, Card, ErrorState, Field, Input, Loading, PageHeader, Select, Table, Td, useToast } from "@/components/ui";

const LABELS: Record<string, string> = {
  OpportunityRouted: "New opportunity", HighMatchOpportunity: "High-match / high-value opportunity", OpportunityAssigned: "Assigned to me",
  ServiceTargetApproaching: "Service target approaching", ServiceTargetBreached: "Service target breached", InfoRequestFulfilled: "Customer answered my request", InfoRequestExpired: "My request to a customer expired", DailyBrief: "WEZA Daily briefing", WeeklyBrief: "WEZA Weekly briefing", AppetiteInsight: "Appetite insight",
};

export default function Notifications() {
  const p = useApi<any>("/inst/notification-prefs");
  const channels = useApi<any>("/inst/notification-channels");
  const phone = useApi<any>("/inst/me/phone");
  const [teamsUrl, setTeamsUrl] = useState("");
  const [mobile, setMobile] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<any[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const { toast, node } = useToast();
  useEffect(() => {
    if (p.data) setPrefs(p.data.prefs);
  }, [p.data]);
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
  const teamsOn = !!channels.data?.teams_configured;
  const smsOn = !!phone.data?.set;
  async function run(label: string, fn: () => Promise<any>, done: string) {
    setBusy(label);
    setErr(null);
    try {
      await fn();
      toast(done);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }
  const saveTeams = (url: string | null) => run("teams", async () => { channels.setData(await api("/inst/notification-channels", { method: "PUT", body: { teams_webhook_url: url } })); setTeamsUrl(""); }, url ? "Teams connected" : "Teams disconnected");
  const saveMobile = (value: string) => run("mobile", async () => { phone.setData(await api("/inst/me/phone", { method: "PUT", body: { phone: value } })); setMobile(""); }, value ? "Mobile number saved" : "Mobile number removed");
  return (
    <>
      {node}
      <PageHeader title="Notification preferences" subtitle="Notifications are decision routing, not broadcasting: priority decides the channel, unacknowledged alerts escalate." actions={<Button onClick={save}>Save</Button>} />
      {!p.data.configured && <Banner tone="gold" className="mb-4">Defaults shown — save to confirm (required for activation).</Banner>}
      {err && <Banner tone="danger" className="mb-4">{err}</Banner>}
      <div className="mb-5 grid gap-4 lg:grid-cols-2">
        <Card title="Microsoft Teams" subtitle={teamsOn ? "Connected. Choose Teams for any alert below." : "Post alerts to a Teams channel. Create a webhook for the channel (Workflows: post to a channel when a webhook request is received) and paste its address."}>
          <div className="flex flex-col gap-3">
            <Field label={teamsOn ? "Replace the connected channel" : "Webhook address"} hint="Kept encrypted and never shown again."><Input value={teamsUrl} onChange={(e) => setTeamsUrl(e.target.value)} placeholder="https://…webhook.office.com/…" autoComplete="off" /></Field>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" pending={busy === "teams"} disabled={!teamsUrl.trim()} onClick={() => saveTeams(teamsUrl.trim())}>{teamsOn ? "Replace" : "Connect"}</Button>
              {teamsOn && <Button size="sm" variant="secondary" pending={busy === "teams-test"} onClick={() => run("teams-test", () => api("/inst/notification-channels/teams/test", { method: "POST" }), "Test message sent to Teams")}>Send a test message</Button>}
              {teamsOn && <Button size="sm" variant="ghost" onClick={() => saveTeams(null)}>Disconnect</Button>}
            </div>
          </div>
        </Card>
        <Card title="Your mobile number" subtitle={smsOn ? `SMS alerts go to ${phone.data.masked}. Only you can see this.` : "Add a mobile number to receive SMS alerts for the events you choose. Only you can see it."}>
          <div className="flex flex-col gap-3">
            <Field label={smsOn ? "Replace the number" : "Mobile number"}><Input inputMode="tel" value={mobile} onChange={(e) => setMobile(e.target.value)} placeholder="0772 123 456" autoComplete="tel" /></Field>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" pending={busy === "mobile"} disabled={!mobile.trim()} onClick={() => saveMobile(mobile.trim())}>{smsOn ? "Replace" : "Add number"}</Button>
              {smsOn && <Button size="sm" variant="ghost" onClick={() => saveMobile("")}>Remove</Button>}
            </div>
          </div>
        </Card>
      </div>
      <Table head={["Event", "In-app", "Email", "SMS", "Teams", "Minimum priority", "Daily digest"]}>
        {prefs.map((x, i) => (
          <tr key={x.event_type}>
            <Td className="font-medium">{LABELS[x.event_type] || x.event_type}</Td>
            {["in_app", "email", "sms", "teams"].map((c) => (
              <Td key={c}><input type="checkbox" aria-label={c} title={c === "sms" && !smsOn ? "Add your mobile number above first" : c === "teams" && !teamsOn ? "Connect Teams above first" : undefined} checked={x.channels.includes(c)} disabled={c === "in_app" || (c === "sms" && !smsOn) || (c === "teams" && !teamsOn)} onChange={(e) => set(i, { channels: e.target.checked ? [...x.channels, c] : x.channels.filter((y: string) => y !== c) })} /></Td>
            ))}
            <Td><Select aria-label={`Minimum priority for ${LABELS[x.event_type] || x.event_type}`} value={x.min_priority} onChange={(e) => set(i, { min_priority: e.target.value })} options={[["NORMAL", "Normal"], ["HIGH", "High"], ["URGENT", "Urgent"]]} className="!h-9 !w-32 !text-[14px]" /></Td>
            <Td><input type="checkbox" aria-label="digest" checked={!!x.digest} onChange={(e) => set(i, { digest: e.target.checked })} /></Td>
          </tr>
        ))}
      </Table>
    </>
  );
}
