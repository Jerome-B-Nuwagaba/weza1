"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Badge, Button, EmptyState, ErrorState, Loading, PageHeader, StateBadge, Table, Td } from "@/components/ui";

export default function Products() {
  const { can } = useMe();
  const p = useApi<any>("/inst/products");
  return (
    <>
      <PageHeader title="Product Studio" subtitle="What your institution can offer through WEZA. Every change is a new version; activation needs a second approver."
        actions={can("product.create") && <><Button variant="secondary" href="/institution/products/extract">Extract from document</Button><Button href="/institution/products/new">New product</Button></>} />
      {p.loading ? <Loading /> : p.error ? <ErrorState error={p.error} onRetry={p.reload} /> : p.data.products.length === 0 ? (
        <EmptyState title="No products yet" action={can("product.create") && <Button href="/institution/products/new">Create your first product</Button>}>Configure manually or let WEZA propose a draft from your approved product document.</EmptyState>
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
