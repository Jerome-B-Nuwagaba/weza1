"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Conversation } from "@/components/chat/Conversation";
import { PublicShell } from "@/components/PublicShell";

function Start() {
  const p = useSearchParams();
  const attribution: Record<string, string> = {};
  ["src", "cmp", "ptn", "ref"].forEach((k) => p.get(k) && (attribution[k] = p.get(k)!));
  const q = p.get("q");
  return (
    <PublicShell compact>
      <Conversation attribution={attribution} seed={q} />
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
