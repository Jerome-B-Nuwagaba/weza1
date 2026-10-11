"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api, ApiError, tokens } from "@/lib/api";
import { Logo } from "@/components/Logo";
import { Banner, Button, Field, Input } from "@/components/ui";

const DEMO = [
  ["WEZA admin", "admin@weza.demo"],
  ["WEZA operations", "ops@weza.demo"],
  ["Lakeside — Executive", "exec@lakeside.demo"],
  ["Lakeside — Credit/Risk", "credit@lakeside.demo"],
  ["Lakeside — Business", "business@lakeside.demo"],
  ["Lakeside — Manager", "manager@lakeside.demo"],
  ["Lakeside — Officer", "officer@lakeside.demo"],
  ["Lakeside — Admin", "admin@lakeside.demo"],
  ["Pearl SACCO — Manager", "manager@pearl.demo"],
  ["Kijani — Officer", "officer@kijani.demo"],
  ["Nile Fintech (pending)", "admin@nile.demo"],
];

function Login() {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mfa, setMfa] = useState<{ token: string; enrol?: { secret: string; otpauth_uri: string } } | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  useEffect(() => {
    api("/public/config").then((c) => setDemoMode(!!c.demo_mode)).catch(() => undefined);
  }, []);

  function finish(r: any) {
    tokens.setStaff(r.access_token);
    const next = params.get("next");
    router.push(next && next.startsWith("/") ? next : r.user.kind === "WEZA" ? "/admin" : "/institution");
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mfa) {
        const r = mfa.enrol
          ? await api("/auth/mfa/enrol-pending/confirm", { body: { mfa_token: mfa.token, code } })
          : await api("/auth/mfa/verify", { body: { mfa_token: mfa.token, code } });
        return finish(r);
      }
      const r = await api("/auth/login", { body: { email, password } });
      if (r.mfa_required) setMfa({ token: r.mfa_token });
      else if (r.mfa_enrolment_required) {
        const enrol = await api("/auth/mfa/enrol-pending", { body: { mfa_token: r.mfa_token } });
        setMfa({ token: r.mfa_token, enrol });
      } else finish(r);
    } catch (err) {
      setError((err as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Logo /></div>
        <form onSubmit={submit} className="rounded-2xl border border-line bg-surface p-6 shadow-sm">
          <h1 className="text-xl font-semibold">{mfa ? "Two-step verification" : "Staff sign in"}</h1>
          <p className="mb-5 text-[14px] text-muted">{mfa ? (mfa.enrol ? "Scan the secret into your authenticator app, then enter the 6-digit code." : "Enter the 6-digit code from your authenticator app.") : "Institution and WEZA staff."}</p>
          {mfa ? (
            <div className="space-y-4">
              {mfa.enrol && <Banner tone="info" title="Authenticator secret"><code className="break-all">{mfa.enrol.secret}</code></Banner>}
              <Field label="Code"><Input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} maxLength={6} autoFocus /></Field>
            </div>
          ) : (
            <div className="space-y-4">
              <Field label="Email"><Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
              <Field label="Password"><Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
            </div>
          )}
          {error && <p className="mt-3 text-[13px] text-danger" role="alert">{error}</p>}
          <Button type="submit" className="mt-5 w-full" pending={busy}>{mfa ? "Verify" : "Sign in"}</Button>
          {!mfa && <p className="mt-4 text-center text-[13px] text-muted">New institution? <a href="/institution/join" className="text-blue-800 underline">Join WEZA</a></p>}
        </form>
        {!mfa && demoMode && (
          <div className="mt-4 rounded-xl border border-gold-500/30 bg-gold-100 p-4 text-[13px] text-gold-700">
            <button className="font-semibold underline" onClick={() => setDemo(!demo)}>Test accounts (demo data)</button>
            {demo && (
              <>
                <p className="mt-1">All use password <code className="font-semibold">WezaDemo!2026</code>. Click to fill.</p>
                <div className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                  {DEMO.map(([l, e]) => (
                    <button key={e} type="button" onClick={() => { setEmail(e); setPassword("WezaDemo!2026"); }} className="rounded px-2 py-1 text-left hover:bg-gold-500/10">{l}</button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
