"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "./ui";

type Tab = { href: string; label: string };

const AREAS: { match: (path: string) => boolean; label: string; tabs: Tab[] }[] = [
  {
    match: (path) => path.startsWith("/institution/feed") || path.startsWith("/institution/my-day") ||
      path.startsWith("/institution/previews") || path.startsWith("/institution/reports") || path.startsWith("/institution/opportunities/"),
    label: "Opportunities",
    tabs: [
      { href: "/institution/feed", label: "All opportunities" },
      { href: "/institution/my-day", label: "My work" },
      { href: "/institution/previews", label: "Previews" },
      { href: "/institution/reports", label: "Outcomes" },
    ],
  },
  {
    match: (path) => path.startsWith("/institution/products") || path.startsWith("/institution/appetite") ||
      path.startsWith("/institution/sandbox") || path.startsWith("/institution/radius") || path.startsWith("/institution/demand") ||
      path.startsWith("/institution/product-opportunity") || path.startsWith("/institution/insights"),
    label: "Products & appetite",
    tabs: [
      { href: "/institution/products", label: "Products" },
      { href: "/institution/appetite", label: "Appetite" },
      { href: "/institution/radius", label: "Market fit" },
      { href: "/institution/demand", label: "Demand" },
      { href: "/institution/product-opportunity", label: "Gaps" },
      { href: "/institution/insights", label: "Recommendations" },
      { href: "/institution/sandbox", label: "Test changes" },
    ],
  },
  {
    match: (path) => path.startsWith("/institution/team") || path.startsWith("/institution/users") || path.startsWith("/institution/routing"),
    label: "Team & routing",
    tabs: [
      { href: "/institution/team", label: "Workload" },
      { href: "/institution/users", label: "People & access" },
      { href: "/institution/routing", label: "Routing & SLAs" },
    ],
  },
  {
    match: (path) => path.startsWith("/institution/settings") || path.startsWith("/institution/onboarding") ||
      path.startsWith("/institution/notifications") || path.startsWith("/institution/audit") || path.startsWith("/institution/billing"),
    label: "Settings",
    tabs: [
      { href: "/institution/settings", label: "Organisation" },
      { href: "/institution/onboarding", label: "Activation" },
      { href: "/institution/notifications", label: "Notifications" },
      { href: "/institution/audit", label: "Compliance" },
      { href: "/institution/billing", label: "Billing" },
    ],
  },
];

/** Keeps specialised functions discoverable without making each one a primary workspace destination. */
export function InstitutionWorkspaceTabs() {
  const pathname = usePathname() || "/institution";
  const area = AREAS.find((item) => item.match(pathname));
  if (!area) return null;

  return (
    <nav aria-label={`${area.label} sections`} className="mb-6 overflow-x-auto border-b border-line">
      <div className="flex min-w-max gap-1">
        {area.tabs.map((tab) => {
          const active = pathname === tab.href || (tab.href === "/institution/feed" && pathname.startsWith("/institution/opportunities/"));
          return <Link key={tab.href} href={tab.href} aria-current={active ? "page" : undefined}
            className={cx("border-b-2 px-3 py-2 text-[13px] font-medium transition-colors", active ? "border-blue-600 text-blue-800" : "border-transparent text-muted hover:border-blue-200 hover:text-ink")}>
            {tab.label}
          </Link>;
        })}
      </div>
    </nav>
  );
}
