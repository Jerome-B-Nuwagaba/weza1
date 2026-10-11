import { StaffShell } from "@/components/StaffShell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <StaffShell area="admin">{children}</StaffShell>;
}
