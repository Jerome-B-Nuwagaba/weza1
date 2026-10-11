"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { tokens } from "@/lib/api";
import { Logo } from "./Logo";

export function PublicShell({ children, compact }: { children: React.ReactNode; compact?: boolean }) {
  const [hasSession, setHasSession] = useState(false);
  useEffect(() => setHasSession(!!tokens.customer()), []);
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4">
          <Logo />
          <nav className="flex items-center gap-1 text-[14px]">
            {hasSession && <Link href="/c/status" className="rounded-lg px-3 py-1.5 text-ink hover:bg-blue-50">My requests</Link>}
            <Link href="/for-institutions" className="hidden rounded-lg px-3 py-1.5 text-muted hover:bg-blue-50 sm:inline">For institutions</Link>
            <Link href="/login" className="rounded-lg px-3 py-1.5 text-muted hover:bg-blue-50">Staff sign in</Link>
          </nav>
        </div>
      </header>
      <main className="flex flex-1 flex-col">{children}</main>
      {!compact && (
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-[13px] text-muted sm:flex-row sm:justify-between">
            <span>WEZA creates access. Financial institutions make the credit decision.</span>
            <span>WEZA does not hold or lend money. <Link href="/legal/consent" className="underline">Consent & privacy</Link></span>
          </div>
        </footer>
      )}
    </div>
  );
}
