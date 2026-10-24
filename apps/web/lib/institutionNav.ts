/** The institution workspace's navigation, defined once. The sidebar (StaffShell) and the section tabs
 * (InstitutionWorkspaceTabs) both read this, so they cannot drift apart: a page is reachable from exactly one
 * section, and a link is only offered to a role that holds the permission the page needs. */

export type NavTab = { href: string; label: string; perm?: string };
export type NavArea = {
  key: "command" | "opportunities" | "products" | "team" | "settings";
  label: string;
  tabs: NavTab[];
  /** Routes that belong to the section without being a tab (detail pages, and the like). */
  also?: string[];
};

export const NAV_AREAS: NavArea[] = [
  {
    key: "command", label: "Command Centre", also: ["/institution/ask"],
    tabs: [{ href: "/institution", label: "Command Centre", perm: "opportunity.read_meta" }],
  },
  {
    key: "opportunities", label: "Opportunities", also: ["/institution/opportunities"],
    tabs: [
      { href: "/institution/feed", label: "All opportunities", perm: "opportunity.read_meta" },
      { href: "/institution/priority", label: "Priority & attention", perm: "opportunity.read_meta" },
      { href: "/institution/my-day", label: "My work", perm: "opportunity.update_status" },
      { href: "/institution/previews", label: "Previews", perm: "preview.read" },
      { href: "/institution/reports", label: "Outcomes", perm: "analytics.read" },
    ],
  },
  {
    key: "products", label: "Products & Appetite",
    tabs: [
      { href: "/institution/products", label: "Products", perm: "product.read" },
      { href: "/institution/appetite", label: "Appetite", perm: "appetite.read" },
      { href: "/institution/radius", label: "Market fit", perm: "analytics.read" },
      { href: "/institution/demand", label: "Demand", perm: "analytics.read" },
      { href: "/institution/product-opportunity", label: "Gaps", perm: "analytics.read" },
      { href: "/institution/insights", label: "Recommendations", perm: "analytics.read" },
      { href: "/institution/sandbox", label: "Test changes", perm: "sandbox.run" },
    ],
  },
  {
    key: "team", label: "Team & Routing",
    tabs: [
      { href: "/institution/team", label: "Workload", perm: "team.manage" },
      { href: "/institution/users", label: "People & access" },
      { href: "/institution/routing", label: "Routing & SLAs" },
    ],
  },
  {
    key: "settings", label: "Settings",
    tabs: [
      { href: "/institution/settings", label: "Organisation" },
      { href: "/institution/onboarding", label: "Activation" },
      { href: "/institution/notifications", label: "Notifications" },
      { href: "/institution/audit", label: "Compliance", perm: "consent.audit" },
      { href: "/institution/billing", label: "Billing", perm: "billing.view" },
    ],
  },
];

/** True when `path` is `base` or sits beneath it. Segment-aware: "/institution/team" does not match "/institution/teams". */
export const isUnder = (path: string, base: string) => path === base || path.startsWith(`${base}/`);

/** The section a path belongs to, or undefined for pages outside the workspace sections (such as /institution/join). */
export function areaFor(pathname: string): NavArea | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  return NAV_AREAS.find((a) => a.tabs.some((t) => (t.href === "/institution" ? path === t.href : isUnder(path, t.href)))
    || a.also?.some((b) => isUnder(path, b)));
}

export const visibleTabs = (area: NavArea, can: (perm: string) => boolean) => area.tabs.filter((t) => !t.perm || can(t.perm));

/** Where the sidebar item for a section leads: the first page of it this person is allowed to open. */
export const areaEntry = (area: NavArea, can: (perm: string) => boolean) => visibleTabs(area, can)[0]?.href;

/** Whether `tab` is the page being shown. Detail pages (an opportunity, an appetite) keep their parent tab lit. */
export function tabIsActive(area: NavArea, tab: NavTab, pathname: string): boolean {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (tab.href === "/institution") return path === tab.href;
  if (isUnder(path, tab.href)) return true;
  return area.key === "opportunities" && tab.href === "/institution/feed" && isUnder(path, "/institution/opportunities");
}
