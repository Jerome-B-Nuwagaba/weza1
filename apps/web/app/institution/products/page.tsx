"use client";

import Link from "next/link";
import { Box, ChevronRight, Target } from "lucide-react";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, PageHeader, StateBadge, Table, Td } from "@/components/ui";

const CUSTOMER_TYPE: Record<string, string> = {
  SME: "Business (SME)", SALARIED: "Salaried", AGRICULTURE: "Farmer",
};

/** The active product and active mandate — moved here from the Command Centre. The product shown is the live one
 * with the most open opportunities; the mandate is the first live one. Hidden while loading or on error: the
 * product table below is the source of truth and carries its own states. */
function LiveNow() {
  const cc = useApi<any>("/inst/command-centre");
  const k = cc.data?.kpis;
  if (!k) return null;
  const regions: string[] = k.featured_mandate?.regions || [];
  const tile = (href: string, icon: any, label: string, name: string | undefined, sub: string) => {
    const Icon = icon;
    return (
      <Link href={href} className="group flex min-w-0 items-start gap-4 rounded-xl border border-line bg-surface p-5 transition-colors hover:border-[#b9cbc2]">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-leaf-tint text-olive"><Icon className="h-6 w-6" strokeWidth={1.75} aria-hidden /></span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start justify-between gap-2 text-[15px] font-medium text-muted">{label}<ChevronRight className="h-5 w-5 shrink-0 transition-transform group-hover:translate-x-0.5" strokeWidth={2} aria-hidden /></span>
          <span className="mt-1 line-clamp-2 block text-[19px] font-bold leading-7 text-ink">{name || "None active"}</span>
          <span className="mt-1 block text-[14px] text-muted">{sub}</span>
        </span>
      </Link>
    );
  };
  return (
    <section aria-label="Live on WEZA" className="mb-6 grid gap-4 md:grid-cols-2">
      {tile(k.featured_product ? `/institution/products/${k.featured_product.id}` : "/institution/products", Box, "Active product", k.featured_product?.name,
        !k.featured_product ? "No product is live yet" : `${k.active_products} of ${k.products_total} live · ${k.featured_product.open_opportunities} open opportunit${k.featured_product.open_opportunities === 1 ? "y" : "ies"}`)}
      {tile(k.featured_mandate ? `/institution/appetite/${k.featured_mandate.id}` : "/institution/appetite", Target, "Active mandate", k.featured_mandate?.name,
        !k.featured_mandate ? "No mandate is live yet" : `${k.active_mandates} of ${k.mandates_total} live · ${regions.length ? `across ${regions.join(", ").replace(/, ([^,]*)$/, " and $1")}` : "all regions"}`)}
    </section>
  );
}

export default function Products() {
  const { can } = useMe();
  const p = useApi<any>("/inst/products");
  return (
    <>
      <PageHeader title="Products & appetite" subtitle="Products define what you offer. Appetite defines the customers you want WEZA to match."
        actions={can("product.create") && <><Button variant="secondary" href="/institution/products/extract">Extract from document</Button><Button href="/institution/products/new">New product</Button></>} />
      <Card className="mb-5" title="Configure matching" subtitle="An active product needs an active appetite before it can receive customer opportunities."
        action={can("appetite.read") ? <Button variant="secondary" href="/institution/appetite">Manage appetite</Button> : undefined}>
        <p className="text-[13px] text-muted">Set amount range, customer type, sector, geography and minimum business age in Appetite.</p>
      </Card>
      <LiveNow />
      {p.loading ? <Loading /> : p.error ? <ErrorState error={p.error} onRetry={p.reload} /> : p.data.products.length === 0 ? (
        <EmptyState title="No products yet" action={can("product.create") && <Button href="/institution/products/new">Create your first product</Button>}>Create a credit product, then define its matching appetite.</EmptyState>
      ) : (
        <Table head={["Product", "Customer type", "Amount", "Tenor", "Status"]}>
          {p.data.products.map((x: any) => (
            <tr key={x.id} className="hover:bg-canvas">
              <Td>
                <Link href={`/institution/products/${x.id}`} className="font-medium text-blue-800 hover:underline">{x.name}</Link>
                <div className="text-[12px] text-muted">{p.data.families[x.family] || x.family}</div>
              </Td>
              <Td>{CUSTOMER_TYPE[x.terms.customer_type] || "—"}</Td>
              <Td className="num">{money(x.terms.min_amount)} – {money(x.terms.max_amount)}</Td>
              <Td className="num">{x.terms.min_tenor_months}–{x.terms.max_tenor_months} mo</Td>
              <Td>
                <StateBadge state={x.status} />
                {x.pending_approval && <Badge tone="warning" className="ml-1">awaiting approval</Badge>}
                {x.latest_version !== x.active_version && x.active_version && <Badge tone="muted" className="ml-1">v{x.latest_version} {x.latest_status.toLowerCase().replace("_", " ")}</Badge>}
              </Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
