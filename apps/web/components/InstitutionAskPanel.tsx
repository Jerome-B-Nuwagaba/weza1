"use client";

import { ArrowUp, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Banner, cx } from "./ui";

/** Questions the read-only assistant can answer from its tools — never actions it cannot take. */
const SUGGESTIONS = [
  "Summarise today's opportunities",
  "Show my best SME opportunities",
  "What sits just outside our appetite?",
  "How is the team's queue?",
];

/** Ask Weza, as the Command Centre's centrepiece: one prompt, suggestion chips, and the answers below it.
 * Read-only: it answers from the data the person may already see and never changes anything. */
export function InstitutionAskPanel() {
  const [question, setQuestion] = useState("");
  const [items, setItems] = useState<{ q: string; a?: any; err?: string }[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(value: string) {
    const q = value.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    setItems((current) => [...current, { q }]);
    try {
      const answer = await api("/inst/ask", { body: { question: q } });
      setItems((current) => current.map((item, index) => index === current.length - 1 ? { ...item, a: answer } : item));
    } catch (error) {
      setItems((current) => current.map((item, index) => index === current.length - 1 ? { ...item, err: (error as ApiError).message } : item));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Ask Weza" className="mx-auto w-full max-w-[1020px]">
      <form onSubmit={(event) => { event.preventDefault(); void ask(question); }}
        className="flex h-16 items-center gap-3 rounded-full border border-line bg-surface pl-6 pr-2.5 shadow-sm transition-shadow focus-within:border-blue-400 focus-within:shadow-[0_0_0_4px_var(--blue-100)]">
        <Sparkles className="h-6 w-6 shrink-0 text-blue-600" strokeWidth={1.75} aria-hidden />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Ask Weza"
          placeholder="Ask Weza anything or tell it what to do…"
          className="h-full min-w-0 flex-1 bg-transparent text-[17px] text-ink placeholder:text-[#94a3b8] focus:!border-0 focus:!shadow-none focus:outline-none" />
        <button type="submit" disabled={busy || !question.trim()} aria-label="Send question"
          className={cx("flex h-11 w-11 shrink-0 items-center justify-center rounded-full transition-colors",
            question.trim() ? "bg-blue-600 text-white hover:bg-blue-700" : "bg-canvas text-muted")}>
          <ArrowUp className="h-5 w-5" />
        </button>
      </form>

      {items.length === 0 && (
        <div className="mt-5 flex flex-wrap justify-center gap-3">
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => ask(suggestion)}
              className="rounded-full border border-line bg-surface px-4 py-2 text-[14px] text-[#475569] shadow-xs transition-colors hover:border-blue-400 hover:text-blue-700 dark:text-muted">
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {items.length > 0 && (
        <div className="mt-5 max-h-[28rem] space-y-4 overflow-y-auto rounded-2xl border border-line bg-surface p-5 shadow-xs scroll-thin" aria-live="polite">
          {items.map((item, index) => (
            <div key={`${item.q}-${index}`} className="space-y-2">
              <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-tr-md bg-blue-600 px-4 py-2.5 text-[14px] text-white">{item.q}</div>
              {item.err ? <Banner tone="danger">{item.err}</Banner> : item.a ? (
                <div className="max-w-[90%] rounded-2xl rounded-tl-md border border-line bg-canvas px-4 py-3">
                  <p className="whitespace-pre-line text-[14px] leading-6 text-ink">{item.a.answer}</p>
                  <div className="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5 text-[12px] text-muted">
                    <Wrench className="h-3.5 w-3.5" aria-hidden />
                    {(item.a.tool_calls || []).map((tool: any, toolIndex: number) => <Badge key={toolIndex} tone="muted">{tool.tool}</Badge>)}
                    <span>· {item.a.mode === "ai" ? "AI-assisted" : "Structured"} · read-only</span>
                  </div>
                </div>
              ) : <div className="skeleton h-16 w-[90%]" />}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
