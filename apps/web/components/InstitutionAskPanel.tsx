"use client";

import { ArrowRight, Search, Wrench } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Banner, cx } from "./ui";

/** Ask Weza, as drawn on the Command Centre: one prompt with a search glyph and a send button in the W's light
 * green. Read-only — it answers from data the person may already see and never changes anything. */
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
    <section aria-label="Ask Weza assistant">
      <form onSubmit={(event) => { event.preventDefault(); void ask(question); }}
        className="flex h-16 items-center gap-3 rounded-xl border border-line bg-surface pl-4 pr-2 sm:h-[72px] sm:gap-4 sm:pl-6 focus-within:border-evergreen focus-within:ring-[3px] focus-within:ring-blue-100">
        <Search className="h-6 w-6 shrink-0 text-muted" strokeWidth={1.75} aria-hidden />
        <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Ask Weza"
          placeholder="Ask Weza anything or tell me what to do..."
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] text-ink sm:text-[18px] placeholder:text-[#7a8783] focus:!border-0 focus:!shadow-none focus:outline-none" />
        <button type="submit" disabled={busy} aria-label="Send question"
          className={cx("flex h-12 w-12 shrink-0 items-center sm:h-14 sm:w-[60px] justify-center rounded-lg bg-leaf text-white transition-colors hover:bg-leaf-press active:bg-olive disabled:opacity-60")}>
          <ArrowRight className="h-6 w-6" strokeWidth={2} />
        </button>
      </form>

      {items.length > 0 && (
        <div className="mt-4 max-h-[28rem] space-y-4 overflow-y-auto rounded-xl border border-line bg-surface p-5 scroll-thin" aria-live="polite">
          {items.map((item, index) => (
            <div key={`${item.q}-${index}`} className="space-y-2">
              <div className="ml-auto w-fit max-w-[80%] rounded-xl rounded-tr-sm bg-evergreen px-4 py-2.5 text-[15px] text-white">{item.q}</div>
              {item.err ? <Banner tone="danger">{item.err}</Banner> : item.a ? (
                <div className="max-w-[90%] rounded-xl rounded-tl-sm border border-line bg-soft px-4 py-3">
                  <p className="whitespace-pre-line text-[15px] leading-6 text-ink">{item.a.answer}</p>
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
