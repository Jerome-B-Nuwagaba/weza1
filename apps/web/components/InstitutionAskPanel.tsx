"use client";

import Link from "next/link";
import { ArrowRight, Search, ShieldCheck, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useMe } from "./StaffShell";
import { Badge, Banner, cx } from "./ui";

type Answer = { answer: string; mode: string; tool_calls?: { tool: string; result?: any }[] };
type Turn = { q: string; a?: Answer; err?: string };
type Go = { href: string; label: string; perm?: string };

/** Where each assistant tool's answer continues in the workspace. The answer never replaces those pages; it points
 * to them. Links a role may not open are not offered. */
function linksFor(calls: Answer["tool_calls"]): Go[] {
  const out: Go[] = [];
  for (const c of calls || []) {
    const r = c.result || {};
    if (r.error) continue;
    if (c.tool === "search_opportunities") {
      (r.opportunities || []).slice(0, 3).forEach((o: any) => o.id && out.push({ href: `/institution/opportunities/${o.id}`, label: `Open ${o.reference}` }));
      out.push({ href: "/institution/feed", label: "All opportunities" });
    }
    if (c.tool === "explain_match" && r.id) out.push({ href: `/institution/opportunities/${r.id}`, label: `Open ${r.reference}` });
    if (c.tool === "get_team_queue") {
      out.push({ href: "/institution/team", label: "Team workload", perm: "team.manage" });
      if (r.unassigned) out.push({ href: "/institution/feed?view=unassigned", label: "Unassigned opportunities" });
    }
    if (c.tool === "get_product_status" || c.tool === "get_product_performance") out.push({ href: "/institution/products", label: "Products", perm: "product.read" });
    if (c.tool === "get_product_status" && r.active_mandates?.length) out.push({ href: "/institution/appetite", label: "Mandates", perm: "appetite.read" });
    if (c.tool === "get_demand_summary") out.push({ href: "/institution/demand", label: "Demand", perm: "analytics.read" });
    if (c.tool === "get_near_match_analysis") out.push({ href: "/institution/radius", label: "Market fit", perm: "analytics.read" });
    if (c.tool === "simulate_appetite") out.push({ href: "/institution/sandbox", label: "Test changes", perm: "sandbox.run" });
  }
  return out.filter((g, i) => out.findIndex((x) => x.href === g.href) === i);
}

const failure = (e: unknown) => {
  const err = e as ApiError;
  if (err.status === 403) return "That information isn't available to your role.";
  if (err.status === 429) return "You're asking faster than Ask Weza can answer. Please wait a moment and try again.";
  if (!err.status || err.status >= 500) return "Ask Weza is unavailable right now. Your workspace pages still work — please try again shortly.";
  return err.message || "Ask Weza couldn't answer that.";
};

/** Ask Weza, the Command Centre's main input. Institution-scoped and read-only: it answers from data the person
 * may already see, explains matches and links to where the work happens. It never approves credit, edits
 * mandates or products, or runs a CRB check — those stay in their own workflows with their own confirmations. */
export function InstitutionAskPanel({ suggestions = [] }: { suggestions?: string[] }) {
  const { can } = useMe();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(value: string) {
    const q = value.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((current) => [...current, { q }]);
    try {
      const answer = await api<Answer>("/inst/ask", { body: { question: q } });
      setTurns((current) => current.map((t, i) => i === current.length - 1 ? { ...t, a: answer } : t));
    } catch (error) {
      setTurns((current) => current.map((t, i) => i === current.length - 1 ? { ...t, err: failure(error) } : t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Ask Weza assistant" className="w-full">
      <form onSubmit={(event) => { event.preventDefault(); void ask(question); }}
        className="flex h-16 items-center gap-3 rounded-2xl border border-line bg-surface pl-4 pr-2 shadow-[0_1px_2px_rgba(6,59,50,0.06)] sm:h-[72px] sm:gap-4 sm:pl-6 focus-within:border-evergreen focus-within:ring-[3px] focus-within:ring-blue-100">
        <Search className="h-6 w-6 shrink-0 text-muted" strokeWidth={1.75} aria-hidden />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Ask Weza" maxLength={500}
          placeholder="Ask Weza anything or tell me what to do…"
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] text-ink sm:text-[18px] placeholder:text-[#6b7874] focus:!border-0 focus:!shadow-none focus:outline-none" />
        <button type="submit" disabled={busy || !question.trim()} aria-label="Send question"
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-leaf text-white transition-colors hover:bg-leaf-press focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-evergreen active:bg-olive disabled:opacity-50 sm:h-14 sm:w-[60px]">
          <ArrowRight className="h-6 w-6" strokeWidth={2} />
        </button>
      </form>
      <p className="mt-2.5 flex items-center justify-center gap-1.5 text-center text-[13px] text-muted">
        <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
        Answers use only your institution's data and your role's access. Ask Weza reads and explains; it never approves or changes anything.
      </p>

      {suggestions.length > 0 && turns.length === 0 && (
        <ul aria-label="Suggested questions" className="mt-5 flex flex-wrap justify-center gap-2">
          {suggestions.map((s) => (
            <li key={s}>
              <button type="button" onClick={() => void ask(s)} disabled={busy}
                className="inline-flex min-h-10 items-center gap-2 rounded-full border border-line bg-surface px-4 py-2 text-left text-[14px] text-ink transition-colors hover:border-evergreen hover:bg-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-evergreen disabled:opacity-50">
                <Sparkles className="h-4 w-4 shrink-0 text-olive" aria-hidden />{s}
              </button>
            </li>
          ))}
        </ul>
      )}

      {turns.length > 0 && (
        <div className="mt-5 rounded-2xl border border-line bg-surface p-5 text-left">
          <div className="max-h-[30rem] space-y-5 overflow-y-auto scroll-thin" aria-live="polite" aria-busy={busy}>
            {turns.map((t, index) => {
              const links = t.a ? linksFor(t.a.tool_calls).filter((g) => !g.perm || can(g.perm)) : [];
              return (
                <div key={`${t.q}-${index}`} className="space-y-2">
                  <div className="ml-auto w-fit max-w-[85%] rounded-xl rounded-tr-sm bg-evergreen px-4 py-2.5 text-[15px] text-white">{t.q}</div>
                  {t.err ? <Banner tone="danger">{t.err}</Banner> : t.a ? (
                    <div className="max-w-[92%] rounded-xl rounded-tl-sm border border-line bg-soft px-4 py-3">
                      <p className="whitespace-pre-line text-[15px] leading-6 text-ink">{t.a.answer}</p>
                      {links.length > 0 && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {links.map((g) => (
                            <Link key={g.href} href={g.href} className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-[14px] font-medium text-evergreen hover:border-evergreen">
                              {g.label}<ArrowRight className="h-4 w-4" aria-hidden />
                            </Link>
                          ))}
                        </div>
                      )}
                      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5 text-[12px] text-muted">
                        <Wrench className="h-3.5 w-3.5" aria-hidden />
                        {(t.a.tool_calls || []).map((tool, i) => <Badge key={i} tone="muted">{tool.tool}</Badge>)}
                        <span>· {t.a.mode === "ai" ? "AI-assisted" : "Structured"} · read-only</span>
                      </div>
                    </div>
                  ) : <div className="skeleton h-16 w-[90%]" aria-label="Ask Weza is answering" />}
                </div>
              );
            })}
          </div>
          <div className="mt-4 flex justify-end border-t border-line pt-3">
            <button type="button" onClick={() => setTurns([])} disabled={busy} className={cx("text-[14px] font-medium text-evergreen hover:underline disabled:opacity-50")}>Clear conversation</button>
          </div>
        </div>
      )}
    </section>
  );
}
