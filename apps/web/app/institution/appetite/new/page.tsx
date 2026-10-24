"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { AppetiteDraft, AppetiteEditor, EMPTY_APPETITE } from "@/components/AppetiteEditor";
import { PageHeader } from "@/components/ui";

export default function NewAppetite() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  // One key per attempt: a double click or a retry after a lost reply cannot create a second record. When the server
  // answered with an error nothing was created, so the next attempt (possibly with edits) gets a fresh key.
  const key = useRef(crypto.randomUUID());
  const [error, setError] = useState<ApiError | null>(null);
  async function save(d: AppetiteDraft) {
    setSaving(true);
    setError(null);
    try {
      const r = await api("/inst/appetites", { body: d, idempotencyKey: key.current });
      router.push(`/institution/appetite/${r.appetite_id}`);
    } catch (e) {
      if (e instanceof ApiError) key.current = crypto.randomUUID();
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <PageHeader title="New appetite" subtitle="Draft → simulate → approve (by a second person) → active." />
      <AppetiteEditor initial={EMPTY_APPETITE} onSave={save} saving={saving} error={error} />
    </>
  );
}
