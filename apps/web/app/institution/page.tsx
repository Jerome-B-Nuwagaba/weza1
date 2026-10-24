"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money } from "@/lib/format";
import { useMe } from "@/components/StaffShell";
import { InstitutionAskPanel } from "@/components/InstitutionAskPanel";
import { FIELD_META } from "@/components/RuleBuilder";
import { Banner, Button, Card, EmptyState, ErrorState, Loading, PageHeader, StateBadge, Table, Td } from "@/components/ui";

const CUSTOMER_TYPE: Record<string, string> = {
  SME: "Business (SME)", SALARIED: "Salaried", AGRICULTURE: "Farmer",
};

const customerType = (v?: string | null) => (v ? CUSTOMER_TYPE[v] || v.replace(/_/g, " ").toLowerCase() : null);

/** The Command Centre: what the institution can offer, what it is looking for, what just arrived and what
 * needs action. No dashboards, no charts — four lists an institution admin can act on. */
export default function CommandCentre() {
  const { me, can } = useMe();
  const cc = useApi<any>("/inst/command-centre");
  if (me.institution && me.institution.status !== "ACTIVE")
    return (
      <div className="space-y-4">
        <Banner tone="gold" title="Your workspace isn't live yet">Complete the activation checklist to start receiving qualified opportunities.</Banner>
        <Button href="/institution/onboarding">Open activation checklist</Button>
      </div>
    );
  if (cc.loading) return <Loading rows={6} />;
  if (cc.error) return <ErrorState error={cc.error} onRetry={cc.reload} />;
  const d = cc.data;
  const products: any[] = d.active_products || [];
  const mandates: any[] = d.active_mandates || [];
  const fresh: any[] = d.new_opportunities || [];
  const attention: any[] = d.attention || [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Command Centre"
        subtitle={d.briefing}
        actions={<>
          {can("product.create") && <Button variant="secondary" href="/institution/products">Products</Button>}
          {can("appetite.edit") && <Button href="/institution/appetite">Mandates</Button>}
        </>}
      />

      {d.no_lead && (
        <Banner tone="info" title="No opportunities in your queue right now">
          {d.no_lead.text} <Link href={d.no_lead.link} className="font-medium underline">Explore</Link>
        </Banner>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Active products" subtitle="What your institution can offer customers today."
          action={<Link href="/institution/products" className="text-[13px] font-medium text-blue-800 hover:underline">All products</Link>}>
          {products.length === 0 ? (
            <EmptyState title="No active products">
              {can("product.create") ? "Create a product so customers can be matched to it." : "Your administrator manages products."}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {products.map((p) => (
                <li key={p.id} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link href={`/institution/products/${p.id}`} className="font-medium text-blue-800 hover:underline">{p.name}</Link>
                    <div className="text-[13px] text-muted">
                      {customerType(p.customer_type) || p.family.replace(/_/g, " ").toLowerCase()} · {money(p.min_amount)} – {money(p.max_amount)} · {p.min_tenor_months}–{p.max_tenor_months} mo
                    </div>
                  </div>
                  <StateBadge state={p.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Active mandates" subtitle="The customers WEZA should be finding for you."
          action={<Link href="/institution/appetite" className="text-[13px] font-medium text-blue-800 hover:underline">All mandates</Link>}>
          {mandates.length === 0 ? (
            <EmptyState title="No active mandates">
              {can("appetite.edit") ? "Define a mandate so WEZA knows who you want to serve." : "Your administrator manages mandates."}
            </EmptyState>
          ) : (
            <ul className="divide-y divide-line">
              {mandates.map((m) => (
                <li key={m.id} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <Link href={`/institution/appetite/${m.id}`} className="font-medium text-blue-800 hover:underline">{m.name}</Link>
                    <div className="text-[13px] text-muted">
                      {m.products.length ? m.products.map((x: any) => x.name).join(", ") : "No products linked"}
                      {m.criteria?.length ? ` · ${m.criteria.map((c: any) => FIELD_META[c.field]?.label || c.field).slice(0, 3).join(", ")}` : ""}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <StateBadge state={m.status} />
                    {m.capacity_state && m.capacity_state !== "ACTIVE" && <StateBadge state={m.capacity_state} label={`Capacity ${m.capacity_state.toLowerCase()}`} />}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="New opportunities" subtitle="Matched to your mandates in the last 24 hours."
        action={<Link href="/institution/feed" className="text-[13px] font-medium text-blue-800 hover:underline">Open feed</Link>}>
        {fresh.length === 0 ? (
          <p className="text-[14px] text-muted">No new opportunities in the last 24 hours.</p>
        ) : (
          <Table head={["Reference", "Amount", "Match", "Customer", "Purpose", "Status"]}>
            {fresh.map((o) => (
              <tr key={o.id} className="hover:bg-canvas">
                <Td><Link href={`/institution/opportunities/${o.id}`} className="font-medium text-blue-800 hover:underline">{o.reference}</Link></Td>
                <Td className="num">{money(o.amount)}</Td>
                <Td className="num">{o.match_score}%</Td>
                <Td>{customerType(o.customer_type) || "—"}</Td>
                <Td>{o.purpose_category ? o.purpose_category.replace(/_/g, " ").toLowerCase() : "—"}</Td>
                <Td><StateBadge state={o.state} /></Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <Card title="Needs attention" subtitle="Unassigned work, missed service targets and holds.">
        {attention.length === 0 ? <p className="text-[14px] text-muted">Nothing urgent. Nicely done.</p> : (
          <ul className="divide-y divide-line">
            {attention.map((a: any, i: number) => (
              <li key={i} className="flex items-center justify-between gap-3 py-2.5">
                <span className="flex items-center gap-2 text-[14px]">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${a.severity === "high" ? "bg-danger" : a.severity === "medium" ? "bg-warning" : "bg-blue-400"}`} />
                  {a.text}
                </span>
                <Button size="sm" variant="secondary" href={a.id ? `/institution/opportunities/${a.id}` : a.link}>{a.action}</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <InstitutionAskPanel />
      </div>
    </div>
  );
}
