"use client";

import { usePathname } from "next/navigation";
import { Button, Card } from "./ui";

export function CustomerSessionExpired() {
  const pathname = usePathname();
  return (
    <Card title="Session Expired — Please Verify Phone">
      <p className="mb-4 text-sm text-muted">Verify the phone number linked to your request to securely open your profile, documents and updates.</p>
      <Button href={`/c/login?next=${encodeURIComponent(pathname)}`}>Verify phone</Button>
    </Card>
  );
}
