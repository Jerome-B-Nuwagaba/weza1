"use client";

import { ArrowUp, Wrench } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Banner, Button, inputCls, PageHeader } from "@/components/ui";

const SUGGESTIONS = ["Show my best SME opportunities today", "Where is demand coming from?", "What sits just outside our appetite?", "Simulate reducing minimum business age to 6 months", "How is my team's queue?", "How are our products performing?"];

export default function Ask() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<{ q: string; a?: any; err?: string }[]>([]);
  const [busy, setBusy] = useState(false);
  async function ask(question: string) {
    if (!question.trim()) return;
    setBusy(true);
    setQ("");
    setItems((x) => [...x, { q: question }]);
    try {
      const a = await api("/inst/ask", { body: { question } });
      setItems((x) => x.map((it, i) => (i === x.length - 1 ? { ...it, a } : it)));
    } catch (e) {
      setItems((x) => x.map((it, i) => (i === x.length - 1 ? { ...it, err: (e as ApiError).message } : it)));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Ask WEZA" subtitle="Questions about your opportunities, demand and appetite — answered from approved WEZA tools within your permissions. Read-only: nothing is changed." />
      {items.length === 0 && (
        <div className="mb-6 flex flex-wrap gap-2">{SUGGESTIONS.map((s) => <button key={s} onClick={() => ask(s)} className="rounded-full border border-line bg-surface px-3 py-1.5 text-[13px] text-muted hover:border-blue-400 hover:text-ink">{s}</button>)}</div>
      )}
      <div className="space-y-5">
        {items.map((it, i) => (
          <div key={i} className="space-y-2">
            <div className="flex justify-end"><div className="rounded-2xl rounded-tr-sm bg-blue-600 px-4 py-2 text-white dark:text-[#07111a]">{it.q}</div></div>
            {it.err ? <Banner tone="danger">{it.err}</Banner> : it.a ? (
              <div className="rounded-2xl rounded-tl-sm border border-line bg-surface p-4">
                <p className="whitespace-pre-line text-[14.5px]">{it.a.answer}</p>
                <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2 text-[12px] text-muted">
                  <Wrench className="h-3.5 w-3.5" /> Tools: {it.a.tool_calls.map((t: any, j: number) => <Badge key={j} tone="muted">{t.tool}</Badge>)} <span>· {it.a.mode === "ai" ? "AI-explained" : "Structured mode"}</span>
                </div>
              </div>
            ) : <div className="skeleton h-16 w-full" />}
          </div>
        ))}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); ask(q); }} className="sticky bottom-4 mt-6 flex gap-2 rounded-xl border border-line bg-surface p-2 shadow-sm">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about your marketplace…" className={`${inputCls} h-10 border-0`} aria-label="Question" />
        <Button type="submit" disabled={busy || !q.trim()} className="h-10 w-10 !px-0" aria-label="Ask"><ArrowUp className="h-4 w-4" /></Button>
      </form>
    </div>
  );
}
