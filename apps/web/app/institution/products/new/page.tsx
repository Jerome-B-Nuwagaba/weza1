"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { EMPTY, ProductDraft, ProductEditor } from "@/components/ProductEditor";
import { PageHeader } from "@/components/ui";

export default function NewProduct() {
  const router = useRouter();
  const [initial, setInitial] = useState<ProductDraft>(EMPTY);
  const [saving, setSaving] = useState(false);
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
      const r = await api("/inst/products", { body: d });
      router.push(`/institution/products/${r.product_id}`);
    } catch (e) {
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
