"use client";

import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { Badge, Banner, EmptyState, ErrorState, Loading, PageHeader, Table, Td } from "@/components/ui";

export default function ProductOpportunity() {
  const g = useApi<any>("/inst/intelligence/product-gaps");
  return (
    <>
      <PageHeader title="Product Opportunity" subtitle="Clusters of WEZA demand that current products don't serve well — where a product decision could unlock customers." />
      <Banner tone="info" className="mb-4">{g.data?.note || "Decision support only."} Use Product Studio and the Sandbox to test a hypothetical product.</Banner>
      {g.loading ? <Loading /> : g.error ? <ErrorState error={g.error} /> : g.data.gaps.length === 0 ? <EmptyState title="No significant unmet-demand clusters right now" /> : (
        <Table head={["Purpose", "Segment", "Demand", "Unmet", "Unmet value", "Coverage", "Median ticket", "Suggested family"]}>
          {g.data.gaps.map((x: any, i: number) => (
            <tr key={i}>
              <Td className="font-medium">{x.purpose}</Td>
              <Td>{x.segment}</Td>
              <Td className="num">{x.demand_count}</Td>
              <Td className="num">{x.unmet_count}</Td>
              <Td className="num font-semibold text-gold-700">{money(x.unmet_value)}</Td>
              <Td><Badge tone={x.coverage_ratio < 0.3 ? "danger" : x.coverage_ratio < 0.6 ? "warning" : "success"}>{Math.round(x.coverage_ratio * 100)}% served</Badge></Td>
              <Td className="num">{money(x.median_amount)}</Td>
              <Td>{x.suggested_family.replace(/_/g, " ").toLowerCase()} <span className="text-muted">({x.active_products_in_family} active)</span></Td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
