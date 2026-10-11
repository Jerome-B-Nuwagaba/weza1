"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { date } from "@/lib/format";
import { ErrorState, Loading, PageHeader, StateBadge, Table, Td } from "@/components/ui";

export default function Institutions() {
  const r = useApi<any>("/admin/institutions");
  if (r.loading) return <Loading />;
  if (r.error) return <ErrorState error={r.error} />;
  const pending = r.data.institutions.filter((i: any) => ["SUBMITTED", "UNDER_VERIFICATION"].includes(i.status));
  return (
    <>
      <PageHeader title="Institutions" subtitle={`${pending.length} application${pending.length === 1 ? "" : "s"} awaiting verification.`} />
      <Table head={["Institution", "Type", "Licence", "Status", "Applied", "Live since"]}>
        {r.data.institutions.map((i: any) => (
          <tr key={i.id} className={pending.includes(i) ? "bg-gold-100/40" : ""}>
            <Td><Link href={`/admin/institutions/${i.id}`} className="font-medium text-blue-800 hover:underline">{i.display_name}</Link><div className="text-[12px] text-muted">{i.legal_name}</div></Td>
            <Td>{i.type}</Td>
            <Td className="text-[13px]">{i.licence_no || "—"}<div className="text-[12px] text-muted">{i.regulator}</div></Td>
            <Td><StateBadge state={i.status} /></Td>
            <Td>{date(i.created_at)}</Td>
            <Td>{date(i.activated_at)}</Td>
          </tr>
        ))}
      </Table>
    </>
  );
}
