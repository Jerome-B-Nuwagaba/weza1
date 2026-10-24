"use client";

import { AskPanel } from "@/components/AskPanel";
import { PageHeader } from "@/components/ui";

export default function Ask() {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Ask WEZA" subtitle="Questions about your opportunities, demand and appetite — answered from approved WEZA tools within your permissions. Read-only: nothing is changed." />
      <AskPanel />
    </div>
  );
}
