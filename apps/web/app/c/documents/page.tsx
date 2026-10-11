"use client";

import { FileUp } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ApiError, tokens } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { dateTime } from "@/lib/format";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Button, Card, EmptyState, Loading, PageHeader, Select, StateBadge } from "@/components/ui";

export default function DocumentsPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  useEffect(() => setAuthed(!!tokens.customer()), []);
  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        {authed === false ? <EmptyState title="Verify your phone first" action={<Button href="/start">Start</Button>} /> : authed && <Inner />}
      </div>
    </PublicShell>
  );
}

function Inner() {
  const docs = useApi<any>("/me/documents");
  const [type, setType] = useState("business_registration");
  const [msg, setMsg] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function upload(f: File) {
    setBusy(true);
    const fd = new FormData();
    fd.append("file", f);
    fd.append("doc_type", type);
    try {
      const r = await api("/me/documents", { form: fd, auth: "customer" });
      setMsg(r.state === "STORED" ? { tone: "success", text: `${r.label} uploaded and stored securely.` } : { tone: "danger", text: r.reason });
      docs.reload();
    } catch (e) {
      setMsg({ tone: "danger", text: (e as ApiError).message });
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="My documents" subtitle="Documents are security-checked, encrypted, and only shared with an institution you consent to." />
      <Card title="Upload a document">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1 text-[13px]">Document type{docs.data && <Select value={type} onChange={(e) => setType(e.target.value)} options={Object.entries(docs.data.types).filter(([k]) => k !== "product_document") as [string, string][]} />}</label>
          <label className={`inline-flex h-10 cursor-pointer items-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white ${busy ? "opacity-50" : ""}`}>
            <FileUp className="h-4 w-4" /> {busy ? "Uploading…" : "Choose file"}
            <input type="file" className="hidden" accept="application/pdf,image/jpeg,image/png" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </label>
        </div>
        <p className="mt-2 text-[12px] text-muted">PDF, JPG or PNG, up to 10 MB.</p>
        {msg && <Banner tone={msg.tone} className="mt-3">{msg.text}</Banner>}
      </Card>
      <div className="mt-4 space-y-2">
        {docs.loading ? <Loading rows={2} /> : (docs.data?.documents || []).map((d: any) => (
          <div key={d.id} className="flex items-center justify-between gap-3 rounded-lg border border-line bg-surface px-4 py-3">
            <div><div className="font-medium">{d.label}</div><div className="text-[12px] text-muted">{d.filename} · {(d.size / 1024).toFixed(0)} KB · {dateTime(d.uploaded_at)}{d.reason && ` · ${d.reason}`}</div></div>
            <StateBadge state={d.state === "STORED" ? "ACTIVE" : "REJECTED"} label={d.state === "STORED" ? "Stored securely" : "Rejected"} />
          </div>
        ))}
      </div>
    </>
  );
}
