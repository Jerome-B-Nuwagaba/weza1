"use client";

import { usePathname } from "next/navigation";
import { StaffShell } from "@/components/StaffShell";
import { InstitutionWorkspaceTabs } from "@/components/InstitutionWorkspaceTabs";
import { HeaderSlot } from "@/components/ui";

export default function InstitutionLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (path.startsWith("/institution/join")) return <>{children}</>;
  // The section tabs sit under each page's title (PageHeader renders the slot), as in the workspace mockups.
  return <StaffShell area="institution"><HeaderSlot value={<InstitutionWorkspaceTabs />}>{children}</HeaderSlot></StaffShell>;
}
