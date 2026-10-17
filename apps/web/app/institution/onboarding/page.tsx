"use client";

import { CheckCircle2, Circle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { useMe } from "@/components/StaffShell";
import { Banner, Button, Card, ErrorState, Loading, PageHeader, StateBadge } from "@/components/ui";

export default function Onboarding() {
  const { can, refresh } = useMe();
  const w = useApi<any>("/inst/workspace");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (w.loading) return <Loading />;
  if (w.error) return <ErrorState error={w.error} />;
  const o = w.data.onboarding;
  async function activate() {
    setBusy(true);
    setErr(null);
    try {
      await api("/inst/activate", { method: "POST" });
      await w.reload();
      refresh();
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="max-w-3xl">
      <PageHeader title="Activation" subtitle="Join → verify → users → products → appetite → routing → notifications → activate. No core-system integration at any step." actions={<StateBadge state={o.status} />} />
      {o.status === "ACTIVE" && <Banner tone="success" title="You're live on WEZA" className="mb-4">Qualified opportunities matching your active appetite are routed to your teams.</Banner>}
      {["SUBMITTED", "UNDER_VERIFICATION"].includes(o.status) && <Banner tone="gold" title="Awaiting WEZA verification" className="mb-4">WEZA Operations reviews your licence and representative. You can configure products and appetite meanwhile.</Banner>}
      <Card>
        <ol className="divide-y divide-line">
          {o.items.map((i: any) => (
            <li key={i.key} className="flex items-center justify-between gap-3 py-3">
              <span className="flex items-start gap-3 text-[14.5px]">
                {i.done ? <CheckCircle2 className="h-5 w-5 text-success" /> : <Circle className="h-5 w-5 text-muted" />}
                <span>
                  <span className={i.done ? "text-ink" : "font-medium text-ink"}>{i.label}</span>
                  {!i.done && i.who && <span className="mt-0.5 block text-[12.5px] text-muted">{i.who}</span>}
                </span>
              </span>
              {!i.done && <Link href={i.link} className="text-[13px] font-medium text-blue-800 hover:underline">Set up</Link>}
            </li>
          ))}
        </ol>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
        {o.status !== "ACTIVE" && can("institution.activate") && (
          <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-4">
            <span className="text-[13px] text-muted">{o.ready ? "All checks pass." : `Next: ${o.next?.label}`}</span>
            <Button variant="gold" size="lg" disabled={!o.ready} pending={busy} onClick={activate}>ACTIVATE ON WEZA</Button>
          </div>
        )}
      </Card>
    </div>
  );
}
