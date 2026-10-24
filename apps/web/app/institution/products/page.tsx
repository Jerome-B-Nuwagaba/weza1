"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, StateBadge, Table, Td } from "@/components/ui";

export default function Products() {
  const { can } = useMe();
  const p = useApi<any>("/inst/products");
  return (
    <>
      <PageHeader title="Products & appetite" subtitle="Products define what you offer. Appetite defines the customers you want WEZA to match."
        actions={can("product.create") && <Button href="/institution/products/new">New product</Button>} />
      <Card className="mb-5" title="Configure matching" subtitle="An active product needs an active appetite before it can receive customer opportunities."
        action={can("appetite.read") ? <Button variant="secondary" href="/institution/appetite">Manage appetite</Button> : undefined}>
        <p className="text-[13px] text-muted">Set amount range, customer type, sector, geography and minimum business age in Appetite.</p>
      </Card>
      {p.loading ? <Loading /> : p.error ? <ErrorState error={p.error} onRetry={p.reload} /> : p.data.products.length === 0 ? (
        <EmptyState title="No products yet" action={can("product.create") && <Button href="/institution/products/new">Create your first product</Button>}>Create a credit product, then define its matching appetite.</EmptyState>
      ) : (
        <Table head={["Product", "Family", "Amount", "Tenor", "Rules", "Version", "Status"]}>
          {p.data.products.map((x: any) => (
            <tr key={x.id} className="hover:bg-canvas">
              <Td><Link href={`/institution/products/${x.id}`} className="font-medium text-blue-800 hover:underline">{x.name}</Link></Td>
              <Td>{p.data.families[x.family] || x.family}</Td>
              <Td className="num">{money(x.terms.min_amount)} – {money(x.terms.max_amount)}</Td>
              <Td className="num">{x.terms.min_tenor_months}–{x.terms.max_tenor_months} mo</Td>
              <Td className="num">{x.rules}</Td>
              <Td className="num">v{x.active_version ?? x.latest_version}{x.latest_version !== x.active_version && x.active_version && <Badge tone="warning" className="ml-1">v{x.latest_version} {x.latest_status.toLowerCase().replace("_", " ")}</Badge>}</Td>
              <Td><StateBadge state={x.status} />{x.pending_approval && <Badge tone="warning" className="ml-1">awaiting approval</Badge>}</Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
