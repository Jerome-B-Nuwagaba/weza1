"use client";

import { ArrowUp, Wrench } from "lucide-react";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Badge, Banner, Button, Card, inputCls } from "./ui";

const SUGGESTIONS = [
  "What needs attention today?",
  "Show my best SME opportunities",
  "Why are we not receiving opportunities?",
  "How is the team's queue?",
];

/** The institution copilot belongs where managers begin their work: Command Centre. */
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
    <Card title="Ask Weza" subtitle="Read-only help based on the data you are allowed to see." className="h-fit">
      {items.length === 0 && <div className="mb-3 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((suggestion) => <button key={suggestion} type="button" onClick={() => ask(suggestion)}
          className="rounded-full border border-line bg-surface px-2.5 py-1 text-left text-[12px] text-muted hover:border-blue-400 hover:text-ink">{suggestion}</button>)}
      </div>}

      {items.length > 0 && <div className="mb-3 max-h-[26rem] space-y-3 overflow-y-auto pr-1 scroll-thin">
        {items.map((item, index) => <div key={`${item.q}-${index}`} className="space-y-1.5">
          <div className="ml-4 rounded-xl rounded-tr-sm bg-blue-600 px-3 py-2 text-[13px] text-white">{item.q}</div>
          {item.err ? <Banner tone="danger">{item.err}</Banner> : item.a ? <div className="rounded-xl rounded-tl-sm border border-line bg-canvas p-3">
            <p className="whitespace-pre-line text-[13px] leading-5">{item.a.answer}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-line pt-2 text-[11px] text-muted">
              <Wrench className="h-3 w-3" />
              {(item.a.tool_calls || []).map((tool: any, toolIndex: number) => <Badge key={toolIndex} tone="muted">{tool.tool}</Badge>)}
              <span>· {item.a.mode === "ai" ? "AI-assisted" : "Structured"}</span>
            </div>
          </div> : <div className="skeleton h-16 w-full" />}
        </div>)}
      </div>}

      <form onSubmit={(event) => { event.preventDefault(); void ask(question); }} className="flex gap-2 border-t border-line pt-3">
        <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about your workspace…"
          className={`${inputCls} h-9 min-w-0 flex-1`} aria-label="Ask Weza" />
        <Button type="submit" disabled={busy || !question.trim()} className="h-9 w-9 !px-0" aria-label="Send question"><ArrowUp className="h-4 w-4" /></Button>
      </form>
    </Card>
  );
}
