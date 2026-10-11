"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { OpportunityRow } from "@/components/opportunity";
import { Button, EmptyState, ErrorState, Input, Loading, PageHeader, Select, Tabs } from "@/components/ui";

function Feed() {
  const params = useSearchParams();
  const router = useRouter();
  const [view, setView] = useState(params.get("view") || "open");
  const [sort, setSort] = useState("priority");
  const [minMatch, setMinMatch] = useState(params.get("min_match") || "");
  const [freshness, setFreshness] = useState(params.get("freshness") || "");
  const [q, setQ] = useState("");
  const qs = new URLSearchParams({ view, sort, ...(minMatch ? { min_match: minMatch } : {}), ...(freshness ? { freshness } : {}), ...(q ? { q } : {}) });
  const feed = useApi<any>(`/inst/opportunities?${qs}`, [qs.toString()]);

  async function exportCsv() {
    const r: Response = await api("/inst/reports/export", { raw: true });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "weza-opportunities.csv";
    a.click();
  }

  return (
    <>
      <PageHeader title="Opportunity Feed" subtitle={feed.data ? `Ranked by: ${feed.data.ranking}.` : "Qualified, consented opportunities routed to your institution."} actions={<Button variant="secondary" onClick={exportCsv}>Export CSV</Button>} />
      <Tabs tabs={[["open", "Open"], ["mine", "Mine"], ["unassigned", "Unassigned"], ["closed", "Closed"], ["all", "All"]]} value={view} onChange={(v) => { setView(v); router.replace(`/institution/feed?view=${v}`); }} />
      <div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4">
        <Select value={sort} onChange={(e) => setSort(e.target.value)} options={[["priority", "Sort: priority"], ["match", "Sort: match"], ["amount", "Sort: amount"], ["age", "Sort: waiting longest"]]} aria-label="Sort" />
        <Select value={minMatch} onChange={(e) => setMinMatch(e.target.value)} options={[["", "Any match"], ["90", "Match 90+"], ["75", "Match 75+"]]} aria-label="Minimum match" />
        <Select value={freshness} onChange={(e) => setFreshness(e.target.value)} options={[["", "Any freshness"], ["FRESH", "Fresh"], ["ATTENTION_REQUIRED", "Needs attention"], ["STALE", "Stale"]]} aria-label="Freshness" />
        <Input placeholder="Search reference…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {feed.loading && !feed.data ? <Loading /> : feed.error ? <ErrorState error={feed.error} onRetry={feed.reload} /> : feed.data.items.length === 0 ? (
        <EmptyState title="No opportunities here" action={<Button href="/institution/radius" variant="secondary">See demand near your appetite</Button>}>
          When customers who fit your active appetite consent to share with you, they appear here.
        </EmptyState>
      ) : (
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          {feed.data.items.map((o: any) => <OpportunityRow key={o.id} o={o} />)}
          <div className="border-t border-line px-4 py-2 text-[12px] text-muted">{feed.data.total} opportunities</div>
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Feed />
    </Suspense>
  );
}
