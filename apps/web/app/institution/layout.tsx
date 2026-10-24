"use client";

import { usePathname } from "next/navigation";
import { StaffShell } from "@/components/StaffShell";
import { InstitutionWorkspaceTabs } from "@/components/InstitutionWorkspaceTabs";

export default function InstitutionLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (path.startsWith("/institution/join")) return <>{children}</>;
  return <StaffShell area="institution"><InstitutionWorkspaceTabs />{children}</StaffShell>;
}
