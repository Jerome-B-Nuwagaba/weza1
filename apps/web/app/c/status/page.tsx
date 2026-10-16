"use client";

import { FileUp } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, tokens } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { date, dateTime, money } from "@/lib/format";
import { TermsLine } from "@/components/opportunity";
import { PublicShell } from "@/components/PublicShell";
import { Badge, Banner, Button, Card, EmptyState, ErrorState, Loading, PageHeader, StateBadge, Tabs, Textarea } from "@/components/ui";

export default function StatusPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => setAuthed(!!tokens.customer()), []);
  if (authed === false)
    return (
      <PublicShell>
        <div className="mx-auto w-full max-w-xl px-4 py-16">
          <EmptyState title="Verify your phone to see your requests" action={<Button href="/start">Start or continue a request</Button>}>
            Your requests are linked to your verified phone number.
          </EmptyState>
        </div>
      </PublicShell>
    );
  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-4xl px-4 py-8">{authed && <Inner />}</div>
    </PublicShell>
  );
}

function Inner() {
  const [tab, setTab] = useState("requests");
  const needs = useApi<any>("/me/needs");
  const consents = useApi<any>(tab === "consents" ? "/me/consents" : null, [tab]);
  const notes = useApi<any>(tab === "updates" ? "/me/notifications" : null, [tab]);
  const [msg, setMsg] = useState<string | null>(null);

  async function withdraw(oppId: string) {
    if (!confirm("Withdraw this request? The institution will be told you no longer wish to proceed, and WEZA will stop sharing your details.")) return;
    try {
      await api(`/me/opportunities/${oppId}/withdraw`, { method: "POST" });
      setMsg("Request withdrawn.");
      needs.reload();
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  }
  async function waiting(needId: string, action: string) {
    await api(`/me/needs/${needId}/waiting-room`, { body: { action } }).catch((e) => setMsg(e.message));
    needs.reload();
  }
  async function withdrawConsent(id: string) {
    if (!confirm("Withdraw consent? WEZA will stop future sharing. Information the institution already received stays with them under their own obligations.")) return;
    await api(`/me/consents/${id}/withdraw`, { method: "POST" }).catch((e) => setMsg(e.message));
    consents.reload();
  }

  return (
    <>
      <PageHeader title="My requests" subtitle="Status updates come from the institutions you chose — WEZA never invents bank decisions." actions={<><Button href="/c/profile" variant="secondary">My profile</Button><Button href="/start">New request</Button></>} />
      {msg && <Banner tone="info" className="mb-4">{msg}</Banner>}
      <Tabs tabs={[["requests", "Requests"], ["updates", "Updates"], ["consents", "Consents"]]} value={tab} onChange={setTab} />
      {tab === "requests" && (needs.loading ? <Loading /> : needs.error ? <ErrorState error={needs.error} onRetry={needs.reload} /> : needs.data?.needs.length === 0 ? (
        <EmptyState title="No requests yet" action={<Button href="/start">Start a request</Button>} />
      ) : (
        <div className="space-y-4">
          {needs.data.needs.map((n: any) => (
            <Card key={n.id} title={<span>{money(n.amount)} · {n.purpose || "Financing request"}</span>} subtitle={`Started ${date(n.created_at)}`} action={<StateBadge state={n.readiness || n.status} label={statusLabel(n)} />}>
              {n.waiting && n.waiting.status !== "LEFT" && n.waiting.status !== "EXPIRED" && (
                <Banner tone="gold" title="In the Waiting Room" className="mb-3">
                  We'll message you when a suitable institution becomes available (until {date(n.waiting.expires_at)}).
                  <div className="mt-2 flex gap-2"><Button size="sm" variant="secondary" onClick={() => waiting(n.id, "reconfirm")}>Keep looking</Button><Button size="sm" variant="ghost" onClick={() => waiting(n.id, "leave")}>Stop looking</Button></div>
                </Banner>
              )}
              {n.opportunities.length === 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2 text-[14px] text-muted">
                  Not yet shared with any institution.
                  {n.journey && n.journey.status !== "COMPLETED" && <Button size="sm" href="/start" onClick={() => { tokens.setJourney(n.journey.id, n.journey.token); tokens.setLastJourney(n.journey.id); }}>Continue</Button>}
                </div>
              ) : (
                <div className="space-y-4">
                  {n.opportunities.map((o: any) => (
                    <div key={o.id} className="rounded-lg border border-line p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div><span className="font-semibold">{o.institution}</span> <span className="text-muted">· {o.product} · {o.reference}</span></div>
                        <StateBadge state={o.state} label={o.status_label} />
                      </div>
                      <ol className="mt-3 space-y-1.5 border-l-2 border-line pl-4">
                        {o.timeline.map((t: any, i: number) => (
                          <li key={i} className="text-[13px]"><span className="text-ink">{t.label}</span> <span className="text-muted">· {dateTime(t.at)}</span></li>
                        ))}
                      </ol>
                      {(o.info_requests || []).filter((r: any) => r.status === "OPEN" || r.status === "FULFILLED").map((r: any) => (
                        <InfoRequestItem key={r.id} r={r} institution={o.institution} onDone={(text: string) => { setMsg(text); needs.reload(); }} />
                      ))}
                      {o.outcomes.map((x: any, i: number) => (
                        <div key={i} className="mt-2">
                          <p className="text-[13px] text-muted">{x.label}{x.disbursed_amount ? ` · ${money(x.disbursed_amount)}` : x.approved_amount ? ` · ${money(x.approved_amount)}` : ""} — <i>reported by {x.reported_by}</i></p>
                          {x.terms && <TermsLine terms={x.terms} />}
                        </div>
                      ))}
                      {o.can_withdraw && <Button size="sm" variant="ghost" className="mt-2" onClick={() => withdraw(o.id)}>Withdraw request</Button>}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      ))}
      {tab === "updates" && (notes.loading ? <Loading /> : (
        <div className="space-y-2">
          {(notes.data?.notifications || []).length === 0 && <EmptyState title="No updates yet" />}
          {(notes.data?.notifications || []).map((n: any) => (
            <div key={n.id} className="rounded-lg border border-line bg-surface p-4">
              <div className="flex justify-between gap-2"><span className="font-medium">{n.title}</span><span className="text-[12px] text-muted">{dateTime(n.at)}</span></div>
              <p className="text-[14px] text-muted">{n.body}</p>
              {n.link && <Link href={n.link} className="text-[13px] text-blue-800 underline">Open</Link>}
            </div>
          ))}
        </div>
      ))}
      {tab === "consents" && (consents.loading ? <Loading /> : (
        <div className="space-y-3">
          <Banner tone="info">{consents.data?.note}</Banner>
          {(consents.data?.consents || []).map((c: any) => (
            <div key={c.id} className="rounded-lg border border-line bg-surface p-4">
              <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold">{c.institution}</span><StateBadge state={c.status} /></div>
              <p className="mt-1 text-[13px] text-muted">Granted {dateTime(c.granted_at)} · consent version {c.version}{c.withdrawn_at && ` · withdrawn ${dateTime(c.withdrawn_at)}`}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">{c.categories.map((x: string) => <Badge key={x} tone="muted">{x}</Badge>)}</div>
              {c.status === "GRANTED" && <Button size="sm" variant="ghost" className="mt-2" onClick={() => withdrawConsent(c.id)}>Withdraw consent</Button>}
            </div>
          ))}
        </div>
      ))}
    </>
  );
}

function InfoRequestItem({ r, institution, onDone }: { r: any; institution: string; onDone: (msg: string) => void }) {
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const docs = useApi<any>(r.status === "OPEN" && r.kind === "DOCUMENT" ? "/me/documents" : null);
  const ready = (docs.data?.documents || []).filter((d: any) => d.state === "STORED" && d.doc_type === r.doc_type);

  async function respond(body: any) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/me/info-requests/${r.id}/respond`, { body, auth: "customer" });
      onDone(`Sent to ${institution}.`);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  async function uploadAndSend(f: File) {
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", f);
    fd.append("doc_type", r.doc_type);
    try {
      const d = await api("/me/documents", { form: fd, auth: "customer" });
      if (d.state !== "STORED") throw new Error(d.reason || "That file could not be stored.");
      await respond({ document_id: d.id });
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  }

  if (r.status === "FULFILLED")
    return <p className="mt-3 text-[13px] text-muted">You answered {institution}'s request for {r.kind === "DOCUMENT" ? r.doc_label?.toLowerCase() : "information"} · {dateTime(r.resolved_at)}</p>;

  return (
    <div className="mt-3 rounded-lg border border-gold-500/30 bg-gold-100/40 p-3">
      <div className="text-[14px] font-medium">{institution} asks: {r.kind === "DOCUMENT" ? r.doc_label : "a question"}</div>
      <p className="mt-0.5 text-[14px]">{r.message}</p>
      {r.due_at && <p className="text-[12px] text-muted">Please reply by {dateTime(r.due_at)}</p>}
      {r.fact_label && <p className="text-[12px] text-muted">Your answer will also update your profile ({r.fact_label}).</p>}
      {r.kind === "QUESTION" ? (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <Textarea rows={2} maxLength={2000} value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="Your answer" className="flex-1" />
          <Button size="sm" pending={busy} disabled={!answer.trim()} onClick={() => respond({ response_text: answer })}>Send</Button>
        </div>
      ) : (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {ready.map((d: any) => <Button key={d.id} size="sm" variant="secondary" pending={busy} onClick={() => respond({ document_id: d.id })}>Send {d.filename}</Button>)}
          <label className={`inline-flex h-8 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-3 text-[13px] font-medium text-white ${busy ? "opacity-50" : ""}`}>
            <FileUp className="h-4 w-4" /> Upload new
            <input type="file" className="hidden" accept="application/pdf,image/jpeg,image/png" disabled={busy} onChange={(e) => e.target.files?.[0] && uploadAndSend(e.target.files[0])} />
          </label>
        </div>
      )}
      <p className="mt-2 text-[12px] text-muted">Answering is your choice. WEZA and institutions will never ask for your PIN, password or one-time codes.</p>
      {err && <Banner tone="danger" className="mt-2">{err}</Banner>}
    </div>
  );
}

function statusLabel(n: any) {
  if (n.status === "SUBMITTED" || n.status === "TRACKING") return "Shared";
  if (n.status === "WAITING") return "Waiting Room";
  if (n.readiness === "READY_NOW") return "Options available";
  if (n.readiness === "ALMOST_READY") return "Almost ready";
  if (n.readiness === "NO_CURRENT_MATCH") return "No current match";
  return n.status.replace(/_/g, " ").toLowerCase();
}
