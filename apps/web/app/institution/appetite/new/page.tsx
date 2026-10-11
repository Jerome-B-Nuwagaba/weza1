"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { AppetiteDraft, AppetiteEditor, EMPTY_APPETITE } from "@/components/AppetiteEditor";
import { PageHeader } from "@/components/ui";

export default function NewAppetite() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function save(d: AppetiteDraft) {
    setSaving(true);
    setError(null);
    try {
      const r = await api("/inst/appetites", { body: d });
      router.push(`/institution/appetite/${r.appetite_id}`);
    } catch (e) {
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
