"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { money } from "@/lib/format";
import { Banner, Button, Card, Field, Input, KV, PageHeader, StateBadge, Table, Td } from "@/components/ui";

export default function CustomerSupport() {
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("");
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  async function lookup(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      setR(await api("/admin/customers/lookup", { body: { phone, reason } }));
    } catch (e2) {
      setErr((e2 as ApiError).message);
    }
  }
  return (
    <>
      <PageHeader title="Customer support" subtitle="Lookups go through the Identity Vault, require a reason, are audited, and show masked identifiers." />
      <Card>
        <form onSubmit={lookup} className="grid gap-3 md:grid-cols-[1fr_2fr_auto] md:items-end">
          <Field label="Phone number"><Input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0772 123 456" /></Field>
          <Field label="Reason for access (audited)"><Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Customer called about request status" /></Field>
          <Button type="submit" disabled={reason.length < 5 || phone.length < 9}>Look up</Button>
        </form>
        {err && <Banner tone="danger" className="mt-3">{err}</Banner>}
      </Card>
      {r && !r.found && <Banner tone="info" className="mt-4">No customer with that number.</Banner>}
      {r?.found && (
        <div className="mt-4 space-y-4">
          <Card title={r.customer.name || "Customer"}><KV items={[["Phone", r.customer.phone], ["Type", r.customer.type], ["Verification", r.customer.verification], ["Integrity", r.customer.integrity_state], ["Status", r.customer.status]]} /></Card>
          <Table head={["Need", "Amount", "Status", "Readiness"]}>
            {r.needs.map((n: any) => <tr key={n.id}><Td><Link href={`/admin/graph?q=${n.id}`} className="text-blue-800 hover:underline">{n.purpose || "—"}</Link></Td><Td className="num">{money(n.amount)}</Td><Td><StateBadge state={n.status} /></Td><Td><StateBadge state={n.readiness} /></Td></tr>)}
          </Table>
        </div>
      )}
    </>
  );
}
