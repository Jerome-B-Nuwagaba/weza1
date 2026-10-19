"use client";

import { MessageCircle } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { api, tokens } from "@/lib/api";
import { customerDestination } from "@/lib/customer-auth";
import { whatsappHref } from "@/lib/whatsapp";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Button } from "@/components/ui";

/** QR codes, campaign and partner links land here and are handed straight to WhatsApp, carrying the campaign reference
 * and any need text (?q=). The conversation itself happens only on WhatsApp. */
function Start() {
  const p = useSearchParams();
  const magicToken = useRef(p.get("token"));
  const started = useRef(false);
  const [state, setState] = useState<{ href?: string; missing?: boolean; error?: string }>({});
  useEffect(() => {
    // Strict Mode replays effects; consume a single-use link only once per mounted page.
    if (started.current) return;
    started.current = true;
    if (magicToken.current) {
      const destination = customerDestination(p.get("next"));
      const token = magicToken.current;
      // Remove the credential before any further navigation or same-origin referrer can expose it.
      window.history.replaceState(null, "", "/start");
      api(`/me/auth/magic-verify?token=${encodeURIComponent(token)}`, { auth: "none" })
        .then(() => { tokens.setCustomer(null); window.location.replace(destination); })
        .catch(() => setState({ error: "This sign-in link has expired or has already been used. Verify your phone to continue." }));
      return;
    }
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
        <h1 className="mt-4 font-serif text-2xl text-ink">{magicToken.current ? "Opening your WEZA account" : "Continue on WhatsApp"}</h1>
        {magicToken.current ? (
          state.error ? <><Banner tone="gold" className="mt-4">{state.error}</Banner><Button className="mt-5" href="/c/login">Verify phone</Button></> : <p className="mt-2 text-muted">Verifying your secure sign-in link…</p>
        ) : state.missing ? (
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
