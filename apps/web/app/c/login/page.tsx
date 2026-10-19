"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError, tokens } from "@/lib/api";
import { customerDestination } from "@/lib/customer-auth";
import { PublicShell } from "@/components/PublicShell";
import { Banner, Button, Card, Input, Loading, PageHeader } from "@/components/ui";

function PhoneLogin() {
  const params = useSearchParams();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<{ challenge_id: string; message: string; dev_code?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function requestCode() {
    setBusy(true);
    setError(null);
    try {
      setChallenge(await api("/me/auth/otp/request", { auth: "none", body: { phone } }));
      setCode("");
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true);
    setError(null);
    try {
      await api("/me/auth/otp/verify", { auth: "none", body: { phone, code, challenge_id: challenge!.challenge_id } });
      tokens.setCustomer(null);
      window.location.replace(customerDestination(params.get("next")));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-md px-4 py-12">
        <PageHeader title="Sign in via Phone OTP" subtitle="Use the phone number linked to your WEZA request." />
        <Card>
          <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); void (challenge ? verify() : requestCode()); }}>
            <label className="block text-sm">Phone number<Input type="tel" autoComplete="tel" placeholder="0772 123 456" value={phone} onChange={(event) => setPhone(event.target.value)} disabled={!!challenge || busy} required /></label>
            {challenge && <>
              <p className="text-sm text-muted">{challenge.message}</p>
              <label className="block text-sm">Verification code<Input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} required autoFocus /></label>
              {challenge.dev_code && <Banner tone="gold">Demo verification code: <strong>{challenge.dev_code}</strong></Banner>}
            </>}
            {error && <Banner tone="danger">{error}</Banner>}
            <Button type="submit" pending={busy} disabled={challenge ? code.length !== 6 : !phone.trim()} className="w-full">{challenge ? "Verify phone and sign in" : "Send verification code"}</Button>
            {challenge && <div className="flex justify-between gap-2">
              <Button type="button" variant="ghost" disabled={busy} onClick={requestCode}>Resend code</Button>
              <Button type="button" variant="ghost" disabled={busy} onClick={() => { setChallenge(null); setCode(""); setError(null); }}>Change number</Button>
            </div>}
          </form>
        </Card>
      </div>
    </PublicShell>
  );
}

export default function Page() {
  return <Suspense fallback={<Loading />}><PhoneLogin /></Suspense>;
}
