"use client";

import { useApi } from "@/lib/hooks";
import { PublicShell } from "@/components/PublicShell";
import { Card, Loading, PageHeader } from "@/components/ui";

export default function ConsentText() {
  const t = useApi<any>("/consent-templates/current?institution=the%20institution%20you%20choose");
  return (
    <PublicShell>
      <div className="mx-auto w-full max-w-3xl px-4 py-8">
        <PageHeader title="Consent & privacy" subtitle="The exact consent text WEZA shows before any information is shared. Every consent records this version." />
        {t.loading || !t.data ? <Loading /> : (
          <Card title={`Version ${t.data.version}`}>
            <p className="whitespace-pre-line text-[15px]">{t.data.text}</p>
            <ul className="mt-4 list-disc pl-5 text-[14px] text-muted">{t.data.categories.map((c: any) => <li key={c.code}>{c.label}</li>)}</ul>
          </Card>
        )}
      </div>
    </PublicShell>
  );
}
