"use client";

import { MessageCircle } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { whatsappHref } from "@/lib/whatsapp";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Button } from "@/components/ui";

/** QR codes, campaign and partner links land here and are handed straight to WhatsApp, carrying the campaign reference
 * and any need text (?q=). The conversation itself happens only on WhatsApp. */
function Start() {
  const p = useSearchParams();
  const [state, setState] = useState<{ href?: string; missing?: boolean }>({});
  useEffect(() => {
    const attribution: Record<string, string> = {};
    ["src", "cmp", "ptn", "ref"].forEach((k) => p.get(k) && (attribution[k] = p.get(k)!));
    api("/public/config")
      .then((c: any) => {
        if (!c?.whatsapp_number) return setState({ missing: true });
        const href = whatsappHref(c.whatsapp_number, p.get("q") || "", attribution);
        setState({ href });
        window.location.replace(href);
      })
      .catch(() => setState({ missing: true }));
  }, [p]);
  return (
    <PublicShell compact>
      <div className="mx-auto w-full max-w-xl px-4 py-16 text-center">
        <MessageCircle className="mx-auto h-8 w-8 text-blue-700" />
        <h1 className="mt-4 font-serif text-2xl text-ink">Continue on WhatsApp</h1>
        {state.missing ? (
          <Banner tone="gold" className="mt-4">WEZA's WhatsApp number is not connected yet. Please try again later.</Banner>
        ) : (
          <>
            <p className="mt-2 text-muted">Opening WhatsApp, where WEZA will ask about the financing you need.</p>
            {state.href && <Button className="mt-5" href={state.href}>Open WhatsApp</Button>}
          </>
        )}
      </div>
    </PublicShell>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Start />
    </Suspense>
  );
}
