"use client";

import { ArrowRight, Building2, MessageCircle, ShieldCheck, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PublicShell } from "@/components/PublicShell";
import { Button, inputCls } from "@/components/ui";

function Landing() {
  const router = useRouter();
  const params = useSearchParams();
  const [text, setText] = useState("");
  const [stats, setStats] = useState<any>(null);
  useEffect(() => {
    api("/public/stats").then(setStats).catch(() => undefined);
  }, []);
  const qs = () => {
    const p = new URLSearchParams();
    ["src", "cmp", "ptn", "ref"].forEach((k) => params.get(k) && p.set(k, params.get(k)!));
    if (text.trim()) p.set("q", text.trim());
    return p.toString();
  };
  return (
    <PublicShell>
      <section className="border-b border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 md:grid-cols-[1.2fr_1fr] md:py-20">
          <div>
            <p className="mb-3 text-[13px] font-semibold uppercase tracking-[0.14em] text-gold-700">Uganda's financing marketplace</p>
            <h1 className="font-serif text-4xl leading-[1.1] text-ink sm:text-5xl">Tell WEZA what financing you need.</h1>
            <p className="mt-4 max-w-xl text-[17px] text-muted">
              Describe your need in your own words. WEZA asks only the questions that matter, shows you participating institutions that fit — and shares your request only with the one you choose.
            </p>
            <form onSubmit={(e) => { e.preventDefault(); router.push(`/start?${qs()}`); }} className="mt-7 flex max-w-xl flex-col gap-2 sm:flex-row">
              <input value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. I need UGX 30 million to expand my pharmacy" className={`${inputCls} h-12 text-[15px]`} aria-label="Describe your financing need" />
              <Button type="submit" size="lg">Start <ArrowRight className="h-4 w-4" /></Button>
            </form>
            <div className="mt-3 flex items-center gap-3 text-[14px]">
              <Button href={`/whatsapp-sim?${qs()}`} variant="ghost" size="sm"><MessageCircle className="h-4 w-4" /> Continue on WhatsApp</Button>
            </div>
          </div>
          <div className="rounded-2xl border border-line bg-canvas p-6">
            <div className="text-[13px] font-semibold text-muted">How it works</div>
            <ol className="mt-4 space-y-4">
              {[
                ["Tell us your need", "In plain words — no banking jargon."],
                ["Verify your phone", "A one-time code keeps your request secure."],
                ["See suitable options", "With clear reasons why each one fits."],
                ["Choose and consent", "Your details go only to the institution you pick."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="num flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[13px] font-semibold text-white">{i + 1}</span>
                  <div><div className="font-medium text-ink">{t}</div><div className="text-[14px] text-muted">{d}</div></div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>
      <section className="mx-auto grid max-w-6xl gap-4 px-4 py-12 md:grid-cols-3">
        {[
          [ShieldCheck, "You stay in control", "Nothing is shared without your explicit, institution-specific consent. Withdraw it any time."],
          [Sparkles, "Explained, not hidden", "Every option shows why it matched. A match is never a loan approval — the institution decides."],
          [Building2, "Real participating institutions", stats?.institutions?.length ? `${stats.institutions.map((i: any) => i.name).join(", ")} — and growing.` : "Banks, SACCOs, microfinance and fintech lenders."],
        ].map(([Icon, t, d]: any) => (
          <div key={t} className="rounded-xl border border-line bg-surface p-5">
            <Icon className="h-5 w-5 text-blue-600" />
            <div className="mt-3 font-semibold text-ink">{t}</div>
            <p className="mt-1 text-[14px] text-muted">{d}</p>
          </div>
        ))}
      </section>
    </PublicShell>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Landing />
    </Suspense>
  );
}
