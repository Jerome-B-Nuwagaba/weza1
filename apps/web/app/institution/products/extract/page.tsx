"use client";

import { FileUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Banner, Card, PageHeader } from "@/components/ui";

export default function Extract() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function upload(f: File) {
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await api("/inst/products/extract", { form: fd });
      const p = r.proposal;
      const draft = {
        name: p.name || "", family: p.family || "SME_WORKING_CAPITAL",
        terms: { min_amount: p.min_amount || 1000000, max_amount: p.max_amount || 50000000, min_tenor_months: p.min_tenor_months || 3, max_tenor_months: p.max_tenor_months || 24, pricing_display: p.pricing_display || "", collateral_required: !!p.collateral_required, digital_journey: true, typical_response_hours: 48, description: p.description || "" },
        rules: (p.rules || []).map((x: any) => ({ field: x.field, op: x.op, value: x.value, label: x.label })),
        requirements: (p.requirements || []).slice(0, 6).map((x: string) => ({ doc_type: "other", label: x, required: false })),
        provenance: { source: `${r.filename} · ${p.source === "ai" ? "AI extraction" : "rule-based extraction"}`, items: p.provenance },
      };
      sessionStorage.setItem("weza.extracted", JSON.stringify(draft));
      router.push("/institution/products/new");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeader title="Extract product from document" subtitle="Upload an approved product document (PDF or text). WEZA proposes a structured draft with provenance for you to review." />
      <Card>
        <label className={`flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-line px-6 py-14 text-center hover:border-blue-400 ${busy ? "opacity-60" : ""}`}>
          <FileUp className="h-8 w-8 text-blue-600" />
          <span className="font-medium">{busy ? "Reading document…" : "Choose a product document"}</span>
          <span className="text-[13px] text-muted">PDF or .txt, up to 10 MB. The file is security-checked before any processing.</span>
          <input type="file" className="hidden" accept="application/pdf,text/plain" disabled={busy} onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
        {err && <Banner tone="danger" className="mt-4">{err}</Banner>}
        <Banner tone="info" className="mt-4">AI extracts and proposes. Your institution reviews, approves and activates. Extracted rules always start as drafts.</Banner>
      </Card>
    </>
  );
}
