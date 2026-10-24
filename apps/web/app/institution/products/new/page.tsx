"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { EMPTY, ProductDraft, ProductEditor } from "@/components/ProductEditor";
import { PageHeader } from "@/components/ui";

export default function NewProduct() {
  const router = useRouter();
  const [initial, setInitial] = useState<ProductDraft>(EMPTY);
  const [saving, setSaving] = useState(false);
  // One key per attempt: a double click or a retry after a lost reply cannot create a second record. When the server
  // answered with an error nothing was created, so the next attempt (possibly with edits) gets a fresh key.
  const key = useRef(crypto.randomUUID());
  const [error, setError] = useState<ApiError | null>(null);
  useEffect(() => {
    const raw = sessionStorage.getItem("weza.extracted");
    if (raw) {
      sessionStorage.removeItem("weza.extracted");
      setInitial(JSON.parse(raw));
    }
  }, []);
  async function save(d: ProductDraft) {
    setSaving(true);
    setError(null);
    try {
      const r = await api("/inst/products", { body: d, idempotencyKey: key.current });
      router.push(`/institution/products/${r.product_id}`);
    } catch (e) {
      if (e instanceof ApiError) key.current = crypto.randomUUID();
      setError(e as ApiError);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <PageHeader title="New product" subtitle="Saved as a draft. Submit it for approval when ready — a different authorised user must approve." />
      <ProductEditor initial={initial} onSave={save} saving={saving} error={error} />
    </>
  );
}
