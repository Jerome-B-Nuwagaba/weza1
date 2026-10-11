"use client";

import { ArrowLeft, CheckCheck, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Banner, Button, cx, Input } from "@/components/ui";

/** WhatsApp channel simulator (blueprint C-03). Posts to the same channel gateway the real Meta webhook uses,
 * so journeys here behave exactly like WhatsApp in production. Test environments only. */
export default function WhatsAppSim() {
  const [phone, setPhone] = useState("");
  const [connected, setConnected] = useState(false);
  const [msgs, setMsgs] = useState<any[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const p = localStorage.getItem("weza.sim.phone");
    if (p) setPhone(p);
  }, []);
  useEffect(() => bottom.current?.scrollIntoView({ block: "end" }), [msgs.length]);
  useEffect(() => {
    if (!connected) return;
    const t = setInterval(() => refresh(), 5000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, phone]);

  async function refresh() {
    try {
      const r = await api(`/channels/simulator/inbox?phone=${encodeURIComponent(phone)}`);
      setMsgs(r.messages);
    } catch (e) {
      setErr((e as ApiError).message);
    }
  }
  async function send(payload: Record<string, unknown>) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api("/channels/simulator/messages", { body: { phone, ...payload } });
      setMsgs(r.messages);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }
  const lastOut = [...msgs].reverse().find((m) => m.direction === "OUT" && m.channel === "whatsapp");

  return (
    <div className="flex min-h-screen flex-col items-center bg-[#0b141a] px-2 py-4 sm:py-8">
      <div className="mb-3 w-full max-w-md text-[13px] text-[#8696a0]">
        <Link href="/" className="inline-flex items-center gap-1 hover:text-white"><ArrowLeft className="h-4 w-4" /> WEZA</Link> · WhatsApp simulator (test channel — uses the real WEZA webhook pipeline)
      </div>
      <div className="flex w-full max-w-md flex-1 flex-col overflow-hidden rounded-2xl border border-[#2a3942] bg-[#0b141a] shadow-2xl" style={{ maxHeight: "86vh" }}>
        <div className="flex items-center gap-3 bg-[#202c33] px-4 py-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#2E8BC9] text-sm font-bold text-white">W</div>
          <div><div className="text-[15px] font-medium text-[#e9edef]">WEZA</div><div className="text-[12px] text-[#8696a0]">Business account</div></div>
        </div>
        {!connected ? (
          <form className="flex flex-1 flex-col justify-center gap-3 p-6" onSubmit={(e) => { e.preventDefault(); localStorage.setItem("weza.sim.phone", phone); setConnected(true); refresh(); }}>
            <label className="text-[14px] text-[#e9edef]">Your test mobile number</label>
            <Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0772 123 456" inputMode="tel" />
            <p className="text-[12px] text-[#8696a0]">Use any Ugandan-format number. Messages WEZA "sends" to it — including SMS codes — appear in this window.</p>
            <Button type="submit" disabled={phone.replace(/\D/g, "").length < 9}>Open chat</Button>
          </form>
        ) : (
          <>
            <div className="scroll-thin flex-1 space-y-2 overflow-y-auto px-3 py-4" style={{ background: "#0b141a" }}>
              {msgs.length === 0 && <p className="py-10 text-center text-[13px] text-[#8696a0]">Say hello — e.g. "I need 10 million for stock for my shop".</p>}
              {msgs.map((m, i) => (
                <div key={i} className={cx("flex", m.direction === "IN" ? "justify-end" : "justify-start")}>
                  <div className={cx("max-w-[85%] whitespace-pre-line rounded-lg px-3 py-2 text-[14px]", m.direction === "IN" ? "bg-[#005c4b] text-[#e9edef]" : m.channel === "sms" ? "border border-dashed border-[#8696a0] bg-transparent text-[#e9edef]" : "bg-[#202c33] text-[#e9edef]")}>
                    {m.channel === "sms" && <div className="mb-1 text-[11px] uppercase tracking-wide text-[#8696a0]">SMS</div>}
                    {fmt(m.text)}
                    <div className="mt-1 flex items-center justify-end gap-1 text-[10px] text-[#8696a0]">{new Date(m.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}{m.direction === "IN" && <CheckCheck className="h-3 w-3 text-[#53bdeb]" />}</div>
                  </div>
                </div>
              ))}
              <div ref={bottom} />
            </div>
            {lastOut?.quick_replies?.length > 0 && lastOut.quick_replies.length <= 3 && (
              <div className="flex flex-wrap gap-2 bg-[#0b141a] px-3 pb-2">
                {lastOut.quick_replies.map((q: any, i: number) => (
                  <button key={i} disabled={busy} onClick={() => send({ action: q.action, value: q.value, label: q.label })} className="flex-1 rounded-lg bg-[#202c33] px-3 py-2 text-[13px] font-medium text-[#53bdeb] hover:bg-[#2a3942]">{q.label}</button>
                ))}
              </div>
            )}
            {err && <div className="px-3 pb-2"><Banner tone="danger">{err}</Banner></div>}
            <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) { send({ text: text.trim() }); setText(""); } }} className="flex gap-2 bg-[#202c33] px-3 py-2">
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message" className="h-10 flex-1 rounded-lg bg-[#2a3942] px-3 text-[14px] text-[#e9edef] placeholder:text-[#8696a0] focus:outline-none" aria-label="Message" />
              <button type="submit" disabled={busy || !text.trim()} className="flex h-10 w-10 items-center justify-center rounded-full bg-[#00a884] text-white disabled:opacity-50" aria-label="Send"><Send className="h-4 w-4" /></button>
            </form>
          </>
        )}
      </div>
      {connected && <button onClick={() => { setConnected(false); setMsgs([]); }} className="mt-3 text-[12px] text-[#8696a0] underline">Use a different number</button>}
    </div>
  );
}

function fmt(t: string) {
  // WhatsApp-style *bold* and _italic_
  const parts = (t || "").split(/(\*[^*]+\*|_[^_]+_)/g);
  return parts.map((p, i) => (p.startsWith("*") && p.endsWith("*") ? <b key={i}>{p.slice(1, -1)}</b> : p.startsWith("_") && p.endsWith("_") ? <i key={i}>{p.slice(1, -1)}</i> : p));
}
