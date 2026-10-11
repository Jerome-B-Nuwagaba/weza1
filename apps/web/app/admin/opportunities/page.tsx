"use client";

import Link from "next/link";
import { useState } from "react";
import { useApi } from "@/lib/hooks";
import { money, STATE_LABEL } from "@/lib/format";
import { Badge, ErrorState, Input, Loading, PageHeader, Select, StateBadge, Table, Td } from "@/components/ui";

export default function AdminOpportunities() {
  const [state, setState] = useState("");
  const [fresh, setFresh] = useState("");
  const [q, setQ] = useState("");
  const qs = new URLSearchParams({ ...(state ? { state } : {}), ...(fresh ? { freshness: fresh } : {}), ...(q ? { q } : {}) }).toString();
  const r = useApi<any>(`/admin/opportunities?${qs}`, [qs]);
  return (
    <>
      <PageHeader title="Opportunity monitoring" subtitle="Network-wide flow. Customer identity is never shown here — use the audited support lookup when needed." />
      <div className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Select value={state} onChange={(e) => setState(e.target.value)} options={[["", "Any state"], ...Object.entries(STATE_LABEL)]} />
        <Select value={fresh} onChange={(e) => setFresh(e.target.value)} options={[["", "Any freshness"], ["FRESH", "Fresh"], ["ATTENTION_REQUIRED", "Needs attention"], ["STALE", "Stale"], ["EXPIRED", "Expired"]]} />
        <Input placeholder="Reference…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {r.loading && !r.data ? <Loading /> : r.error ? <ErrorState error={r.error} /> : (
        <Table head={["Reference", "Institution", "Amount", "Need", "Match", "State", "Owner", "Age"]}>
          {r.data.items.map((o: any) => (
            <tr key={o.id}>
              <Td><Link href={`/admin/graph?q=${o.reference}`} className="font-medium text-blue-800 hover:underline">{o.reference}</Link>{o.integrity_hold && <Badge tone="warning" className="ml-1">hold</Badge>}</Td>
              <Td>{o.institution}</Td>
              <Td className="num">{money(o.amount)}</Td>
              <Td className="text-[13px]">{o.need}</Td>
              <Td className="num">{o.match_score}</Td>
              <Td><StateBadge state={o.state} label={STATE_LABEL[o.state]} /></Td>
              <Td className="text-[13px]">{o.owner || "Unassigned"}</Td>
              <Td className="num">{o.age_hours < 48 ? `${o.age_hours}h` : `${Math.floor(o.age_hours / 24)}d`}</Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
