"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ChevronLeft, ChevronRight, MoreHorizontal, Search, X } from "lucide-react";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { downloadFile } from "@/lib/download";
import { moneyFull, STATE_LABEL } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { useApi } from "@/lib/hooks";
import { Badge, Button, cx, EmptyState, ErrorState, inputCls, Loading, PageHeader, Select, StateBadge, useToast } from "@/components/ui";

const PAGE = 25;
const KIND: Record<string, string> = { SME: "Business", SALARIED: "Salaried", AGRICULTURE: "Farmer" };

const describe = (o: any) =>
  [KIND[o.customer_type] || "Customer", o.sector?.replace(/_/g, " "), o.district].filter(Boolean).join(" · ");

/** The Opportunities list (the Opportunities mockup, in the WEZA brand): search and filters in one card, a table
 * of qualified opportunities with match score, product, owner and status, and bulk assignment for the roles that
 * may assign. Customers are described, never named, in the list. */
function Feed() {
  const { can } = useMe();
  const { toast, node } = useToast();
  const params = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState(params.get("view") === "closed" ? "closed" : params.get("view") === "all" ? "all" : "open");
  const [queue, setQueue] = useState(params.get("view") === "unassigned" ? "unassigned" : "all");
  const [mine, setMine] = useState(params.get("view") === "mine");
  const [sort, setSort] = useState("priority");
  const [minMatch, setMinMatch] = useState(params.get("min_match") || "");
  const [freshness, setFreshness] = useState(params.get("freshness") || "");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [assignee, setAssignee] = useState("");
  const [assigning, setAssigning] = useState(false);
  const canAssign = can("opportunity.assign");

  const view = mine ? "mine" : queue === "unassigned" ? "unassigned" : status;
  const qs = new URLSearchParams({ view, sort, limit: "200", ...(minMatch ? { min_match: minMatch } : {}), ...(freshness ? { freshness } : {}), ...(q ? { q } : {}) });
  const feed = useApi<any>(`/inst/opportunities?${qs}`, [qs.toString()]);
  const items: any[] = useMemo(() => feed.data?.items || [], [feed.data]);
  const pages = Math.max(1, Math.ceil(items.length / PAGE));
  const shown = items.slice(page * PAGE, page * PAGE + PAGE);
  useEffect(() => { setPage(0); setSelected(new Set()); }, [qs.toString()]); // eslint-disable-line react-hooks/exhaustive-deps

  const setView = (next: { status?: string; queue?: string; mine?: boolean }) => {
    const s = next.status ?? status, qu = next.queue ?? queue, m = next.mine ?? mine;
    setStatus(s); setQueue(qu); setMine(m);
    router.replace(`/institution/feed?view=${m ? "mine" : qu === "unassigned" ? "unassigned" : s}`);
  };

  async function exportCsv() {
    try {
      await downloadFile("/inst/reports/export", "weza-opportunities.csv");
    } catch (e) {
      toast((e as ApiError).message || "Export failed. Please try again.");
    }
  }

  async function assignSelected() {
    if (!assignee || !selected.size) return;
    setAssigning(true);
    let done = 0;
    const failed: string[] = [];
    for (const id of selected) {
      try {
        await api(`/inst/opportunities/${id}/assign`, { body: { user_id: assignee } });
        done += 1;
      } catch (e) {
        failed.push((e as ApiError).message);
      }
    }
    setAssigning(false);
    setSelected(new Set());
    toast(failed.length ? `Assigned ${done}; ${failed.length} could not be assigned — ${failed[0]}` : `Assigned ${done} opportunit${done === 1 ? "y" : "ies"}.`);
    feed.reload();
  }

  const allOnPage = shown.length > 0 && shown.every((o) => selected.has(o.id));
  const toggleAll = () => setSelected((cur) => {
    const next = new Set(cur);
    shown.forEach((o) => (allOnPage ? next.delete(o.id) : next.add(o.id)));
    return next;
  });
  const toggle = (id: string) => setSelected((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const sortHead = (key: string, label: string) => (
    <button type="button" onClick={() => setSort(sort === key ? "priority" : key)} aria-pressed={sort === key}
      className={cx("inline-flex items-center gap-1 font-semibold uppercase tracking-[0.06em] hover:text-ink", sort === key && "text-ink")}>
      {label}{sort === key && <ArrowDown className="h-3.5 w-3.5" aria-hidden />}
    </button>
  );

  return (
    <>
      {node}
      <PageHeader title="Opportunities" subtitle="Review qualified opportunities routed to your institution."
        actions={can("analytics.read") ? <>
          <Button variant="secondary" href="/institution/reports">Outcomes</Button>
          <Button variant="secondary" href="/institution/demand">Analytics</Button>
          <Button variant="secondary" onClick={exportCsv}>Export</Button>
        </> : undefined} />

      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-line bg-surface p-3 lg:flex-row lg:items-center">
        <label className="relative block min-w-0 flex-1">
          <span className="sr-only">Search by reference</span>
          <Search className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-muted" strokeWidth={1.75} aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by reference…"
            className={cx(inputCls, "h-12 pl-12 text-[15px]")} />
        </label>
        <div className="grid grid-cols-2 gap-3 sm:flex">
          <Select aria-label="Status" value={status} onChange={(e) => setView({ status: e.target.value })} className="h-12 sm:w-48"
            options={[["open", "Open"], ["closed", "Closed"], ["all", "All statuses"]]} />
          <Select aria-label="Queue" value={queue} onChange={(e) => setView({ queue: e.target.value })} className="h-12 sm:w-48"
            options={[["all", "All queues"], ["unassigned", "Unassigned"]]} />
          {can("team.manage") && (
            <Button variant="secondary" aria-pressed={mine} onClick={() => setView({ mine: !mine })}
              className={cx("col-span-2 h-12 sm:col-span-1 sm:w-36", mine && "!border-evergreen !bg-blue-50")}>My work</Button>
          )}
        </div>
      </div>

      {(minMatch || freshness) && (
        <div className="mb-4 flex flex-wrap gap-2">
          {minMatch && <button onClick={() => setMinMatch("")} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] hover:bg-soft">Match {minMatch}+ <X className="h-3.5 w-3.5" aria-label="Remove filter" /></button>}
          {freshness && <button onClick={() => setFreshness("")} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[13px] hover:bg-soft">{freshness === "STALE" ? "Stale" : "Needs attention"} <X className="h-3.5 w-3.5" aria-label="Remove filter" /></button>}
        </div>
      )}

      {canAssign && selected.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-evergreen/30 bg-blue-50 px-4 py-3" role="region" aria-label="Bulk actions">
          <span className="text-[15px] font-medium">{selected.size} selected</span>
          <Select aria-label="Assign to" value={assignee} onChange={(e) => setAssignee(e.target.value)} className="h-10 w-56"
            options={[["", "Assign to…"], ...((feed.data?.members || []) as any[]).map((m) => [m.id, m.name] as [string, string])]} />
          <Button size="sm" pending={assigning} disabled={!assignee} onClick={assignSelected}>Assign</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      )}

      {feed.loading && !feed.data ? <Loading /> : feed.error ? <ErrorState error={feed.error} onRetry={feed.reload} /> : items.length === 0 ? (
        <EmptyState title="No opportunities here" action={<Button href="/institution/radius" variant="secondary">See demand near your appetite</Button>}>
          When customers who fit your active appetite consent to share with you, they appear here.
        </EmptyState>
      ) : (
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
          <div className="overflow-x-auto scroll-thin">
            <table className="w-full min-w-[980px] text-left text-[15px]">
              <thead className="border-b border-line bg-soft text-[12px] uppercase tracking-[0.06em] text-muted">
                <tr>
                  {canAssign && <th className="w-14 px-5 py-4"><input type="checkbox" checked={allOnPage} onChange={toggleAll} aria-label="Select all on this page" className="h-[18px] w-[18px] rounded" /></th>}
                  <th className="whitespace-nowrap px-4 py-4 font-semibold">Reference</th>
                  <th className="whitespace-nowrap px-4 py-4">{sortHead("amount", "Amount")}</th>
                  <th className="whitespace-nowrap px-4 py-4">{sortHead("match", "Match score")}</th>
                  <th className="whitespace-nowrap px-4 py-4 font-semibold">Product</th>
                  <th className="whitespace-nowrap px-4 py-4 font-semibold">Assigned to</th>
                  <th className="whitespace-nowrap px-4 py-4 font-semibold">Status</th>
                  <th className="w-16 px-5 py-4"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {shown.map((o) => (
                  <tr key={o.id} className={cx("transition-colors hover:bg-soft/60", selected.has(o.id) && "bg-blue-50/70")}>
                    {canAssign && <td className="px-4 py-4"><input type="checkbox" checked={selected.has(o.id)} onChange={() => toggle(o.id)} aria-label={`Select ${o.reference}`} className="h-[18px] w-[18px] rounded" /></td>}
                    <td className="px-4 py-4">
                      <Link href={`/institution/opportunities/${o.id}`} className="num block font-semibold text-ink hover:text-evergreen hover:underline">{o.reference}</Link>
                      <span className="block max-w-[11rem] truncate text-[14px] capitalize text-muted" title={describe(o)}>{describe(o)}</span>
                    </td>
                    <td className="num whitespace-nowrap px-4 py-4 font-medium text-ink">{moneyFull(o.amount)}</td>
                    <td className="px-4 py-4"><Badge tone={o.match_score >= 85 ? "success" : "warning"} className="num min-w-14 justify-center">{o.match_score}%</Badge></td>
                    <td className="px-4 py-4">
                      <span className="block max-w-[10rem] truncate text-ink">{o.product || "—"}</span>
                      <span className="block max-w-[10rem] truncate text-[14px] text-muted">{o.need || "—"}</span>
                    </td>
                    <td className="px-4 py-4 text-ink"><span className="block max-w-[9rem] truncate">{o.owner || <span className="text-muted">Unassigned</span>}</span></td>
                    <td className="px-4 py-4"><StateBadge state={o.state} label={STATE_LABEL[o.state]} /></td>
                    <td className="px-4 py-4 text-right">
                      <Link href={`/institution/opportunities/${o.id}`} aria-label={`Open ${o.reference}`}
                        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line text-ink hover:bg-soft">
                        <MoreHorizontal className="h-5 w-5" strokeWidth={2} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-4">
            <span className="text-[15px] text-muted">
              Showing {page * PAGE + 1}–{page * PAGE + shown.length} of {feed.data.total} opportunit{feed.data.total === 1 ? "y" : "ies"}
              {feed.data.total > items.length && ` (first ${items.length} loaded — narrow the filters to see the rest)`}
            </span>
            <nav aria-label="Pagination" className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} aria-label="Previous page"
                className="flex h-11 w-11 items-center justify-center rounded-lg border border-line text-ink hover:bg-soft disabled:opacity-40"><ChevronLeft className="h-5 w-5" /></button>
              {Array.from({ length: pages }).slice(0, 7).map((_, i) => (
                <button key={i} onClick={() => setPage(i)} aria-current={i === page ? "page" : undefined}
                  className={cx("num flex h-11 min-w-11 items-center justify-center rounded-lg px-3 text-[15px] font-semibold", i === page ? "bg-evergreen text-white" : "border border-line text-ink hover:bg-soft")}>{i + 1}</button>
              ))}
              <button onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1} aria-label="Next page"
                className="flex h-11 w-11 items-center justify-center rounded-lg border border-line text-ink hover:bg-soft disabled:opacity-40"><ChevronRight className="h-5 w-5" /></button>
            </nav>
          </div>
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
