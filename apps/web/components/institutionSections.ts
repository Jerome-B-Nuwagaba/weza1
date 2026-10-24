import { BarChart3, Building2, ClipboardCheck, Gauge, Inbox, Landmark, LayoutDashboard, Package, ScrollText, Settings, Users, Wrench } from "lucide-react";

/** The institution workspace as six destinations (21 Oct review: "only the necessary pages"). Every existing page keeps
 * its address and stays reachable as a tab of the section that owns it, so nothing is lost and old links still work.
 * `perm` may be one permission or a list (any of); the server still decides what each page returns. */
export type Perm = string | string[];
export type Tab = { href: string; label: string; perm?: Perm };
export type Section = { key: string; label: string; icon: any; group: string; paths: string[]; tabs: Tab[] };

export const SECTIONS: Section[] = [
  { key: "home", label: "Command Centre", icon: LayoutDashboard, group: "Work", paths: ["/institution"], tabs: [] },
  {
    key: "opportunities", label: "Opportunities", icon: Inbox, group: "Work",
    paths: ["/institution/feed", "/institution/my-day", "/institution/previews", "/institution/opportunities"],
    tabs: [
      { href: "/institution/feed", label: "Routed", perm: "opportunity.read_meta" },
      { href: "/institution/my-day", label: "My day", perm: "opportunity.update_status" },
      { href: "/institution/previews", label: "Anonymous previews", perm: "preview.read" },
    ],
  },
  {
    key: "team", label: "Team", icon: Users, group: "Work", paths: ["/institution/team", "/institution/users", "/institution/routing"],
    tabs: [
      { href: "/institution/team", label: "Workload", perm: "team.manage" },
      { href: "/institution/users", label: "People & roles", perm: ["users.manage", "team.manage"] },
      { href: "/institution/routing", label: "Routing & targets", perm: ["routing.manage", "team.manage"] },
    ],
  },
  {
    key: "supply", label: "Supply", icon: Package, group: "Configure",
    paths: ["/institution/products", "/institution/appetite", "/institution/sandbox"],
    tabs: [
      { href: "/institution/products", label: "Products", perm: "product.read" },
      { href: "/institution/appetite", label: "Appetite & mandates", perm: "appetite.read" },
      { href: "/institution/sandbox", label: "Sandbox", perm: "sandbox.run" },
    ],
  },
  {
    key: "intelligence", label: "Intelligence", icon: BarChart3, group: "Intelligence",
    paths: ["/institution/reports", "/institution/demand", "/institution/radius", "/institution/product-opportunity", "/institution/insights", "/institution/ask"],
    tabs: [
      { href: "/institution/reports", label: "Outcomes & reports", perm: "analytics.read" },
      { href: "/institution/demand", label: "Demand", perm: "analytics.read" },
      { href: "/institution/radius", label: "Near appetite", perm: "analytics.read" },
      { href: "/institution/product-opportunity", label: "Product gaps", perm: "analytics.read" },
      { href: "/institution/insights", label: "Insights", perm: "analytics.read" },
      { href: "/institution/ask", label: "Ask WEZA" },
    ],
  },
  {
    key: "settings", label: "Settings", icon: Settings, group: "Workspace",
    paths: ["/institution/settings", "/institution/onboarding", "/institution/notifications", "/institution/billing", "/institution/audit"],
    tabs: [
      { href: "/institution/settings", label: "Institution & account" },
      { href: "/institution/onboarding", label: "Activation" },
      { href: "/institution/notifications", label: "Notification preferences" },
      { href: "/institution/billing", label: "Billing & disputes", perm: "billing.view" },
      { href: "/institution/audit", label: "Consent & access", perm: "consent.audit" },
    ],
  },
];

/** WEZA staff workspace: seven destinations instead of sixteen menu entries. The engineering pages sit behind
 * `admin.engineering`; every business page (commercial, billing, audit, disputes) stays open to the roles that use it. */
export const ADMIN_SECTIONS: Section[] = [
  {
    key: "overview", label: "Overview", icon: Gauge, group: "Daily work", paths: ["/admin", "/admin/market"],
    tabs: [{ href: "/admin", label: "Priority briefing" }, { href: "/admin/market", label: "Market state" }],
  },
  {
    key: "institutions", label: "Institutions", icon: Building2, group: "Daily work", paths: ["/admin/institutions", "/staff/institutions"],
    tabs: [{ href: "/admin/institutions", label: "All institutions" }, { href: "/staff/institutions", label: "Onboarding", perm: "admin.institution_onboard" }],
  },
  {
    key: "opportunities", label: "Opportunities", icon: Inbox, group: "Daily work", paths: ["/admin/opportunities", "/admin/customers", "/admin/graph"],
    tabs: [
      { href: "/admin/opportunities", label: "Monitor" },
      { href: "/admin/customers", label: "Customer support", perm: "admin.vault_lookup" },
      { href: "/admin/graph", label: "Record inspector", perm: "admin.engineering" },
    ],
  },
  {
    key: "operations", label: "Operations", icon: ClipboardCheck, group: "Daily work",
    paths: ["/admin/review", "/admin/integrity", "/admin/deliveries", "/admin/loops"],
    tabs: [
      { href: "/admin/review", label: "Human review" },
      { href: "/admin/integrity", label: "Integrity" },
      { href: "/admin/deliveries", label: "Events & delivery", perm: "admin.engineering" },
      { href: "/admin/loops", label: "Workflows & AI health", perm: "admin.engineering" },
    ],
  },
  {
    key: "commercial", label: "Commercial", icon: Landmark, group: "Business", paths: ["/admin/commercial", "/admin/disputes"],
    tabs: [{ href: "/admin/commercial", label: "Statements & contracts" }, { href: "/admin/disputes", label: "Disputes" }],
  },
  { key: "audit", label: "Audit", icon: ScrollText, group: "Business", paths: ["/admin/audit"], tabs: [] },
  {
    key: "settings", label: "Settings", icon: Wrench, group: "Platform", paths: ["/admin/config", "/admin/whatsapp"],
    tabs: [
      { href: "/admin/config", label: "Controls & configuration" },
      { href: "/admin/whatsapp", label: "WhatsApp connection", perm: "admin.config" },
    ],
  },
];

export const allowed = (can: (p: string) => boolean, perm?: Perm) =>
  !perm || (Array.isArray(perm) ? perm.some((p) => can(p)) : can(perm));

/** The tabs this user may open, in order. */
export const visibleTabs = (s: Section, can: (p: string) => boolean) => s.tabs.filter((t) => allowed(can, t.perm));

/** Where the menu entry for a section leads: the first tab the user may open (the section's own page for Home). */
export const landing = (s: Section, can: (p: string) => boolean) => (s.tabs.length ? visibleTabs(s, can)[0]?.href : s.paths[0]);

const ROOTS = ["/institution", "/admin"];  // the home pages match only themselves, not everything beneath them

export const sectionOf = (sections: Section[], pathname: string): Section | undefined =>
  sections.find((s) => s.paths.some((p) => pathname === p || (!ROOTS.includes(p) && pathname.startsWith(p + "/"))));
