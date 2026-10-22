import { StaffShell } from "@/components/StaffShell";

export default function StaffLayout({ children }: { children: React.ReactNode }) {
  return <StaffShell area="staff">{children}</StaffShell>;
}
