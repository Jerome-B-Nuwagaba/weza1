"use client";

import {
  Activity, BarChart3, Bell, BookOpen, Briefcase, Building2, CalendarCheck, ClipboardCheck, Compass, Cpu, FileSearch,
  FlaskConical, Gauge, GitBranch, Inbox, Landmark, LayoutDashboard, LifeBuoy, LogOut, Map, Menu, MessageSquareText,
  Network, Package, Radar, Receipt, Scale, Settings, ShieldAlert, ShieldCheck, Sliders, Target, Users, Wrench, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, staffLogout, tokens } from "@/lib/api";
import { ago } from "@/lib/format";
import { Logo } from "./Logo";
import { Badge, Button, Card, cx, Loading } from "./ui";

export type Me = {
  id: string; email: string; full_name: string; kind: "INSTITUTION" | "WEZA"; roles: string[]; permissions: string[];
  role_labels: Record<string, string>; institution: { id: string; name: string; status: string } | null;
  mfa_enrolled: boolean; unread_notifications: number;
};

const MeCtx = createContext<{ me: Me; can: (p: string) => boolean; refresh: () => void } | null>(null);
export const useMe = () => useContext(MeCtx)!;

type Item = { href: string; label: string; icon: any; perm?: string };
const INST_NAV: [string, Item[]][] = [
  ["Work", [
    { href: "/institution", label: "Command Centre", icon: LayoutDashboard, perm: "opportunity.read_meta" },
    { href: "/institution/my-day", label: "My Day", icon: CalendarCheck, perm: "opportunity.update_status" },
    { href: "/institution/feed", label: "Opportunity Feed", icon: Inbox, perm: "opportunity.read_meta" },
    { href: "/institution/previews", label: "Previews", icon: Compass, perm: "preview.read" },
    { href: "/institution/team", label: "Team", icon: Users, perm: "team.manage" },
  ]],
  ["Supply", [
    { href: "/institution/products", label: "Products", icon: Package, perm: "product.read" },
    { href: "/institution/appetite", label: "Mandates", icon: Target, perm: "appetite.read" },
    { href: "/institution/sandbox", label: "Sandbox", icon: FlaskConical, perm: "sandbox.run" },
  ]],
  ["Intelligence", [
    { href: "/institution/radius", label: "Opportunity Radius", icon: Radar, perm: "analytics.read" },
    { href: "/institution/demand", label: "Demand Intelligence", icon: Map, perm: "analytics.read" },
    { href: "/institution/product-opportunity", label: "Product Opportunity", icon: Briefcase, perm: "analytics.read" },
    { href: "/institution/insights", label: "Insights", icon: Activity, perm: "analytics.read" },
    { href: "/institution/ask", label: "Ask WEZA", icon: MessageSquareText },
    { href: "/institution/reports", label: "Outcomes & reports", icon: BarChart3, perm: "analytics.read" },
  ]],
  ["Workspace", [
    { href: "/institution/onboarding", label: "Activation", icon: ClipboardCheck },
    { href: "/institution/users", label: "Users & roles", icon: Users },
    { href: "/institution/routing", label: "Routing & targets", icon: GitBranch },
    { href: "/institution/notifications", label: "Notifications", icon: Bell },
    { href: "/institution/billing", label: "Billing", icon: Receipt, perm: "billing.view" },
    { href: "/institution/audit", label: "Consent & access log", icon: ShieldCheck, perm: "consent.audit" },
    { href: "/institution/settings", label: "Settings", icon: Settings },
  ]],
];
const ADMIN_NAV: [string, Item[]][] = [
  ["Network", [
    { href: "/admin", label: "Control Centre", icon: Gauge },
    { href: "/admin/market", label: "Market State", icon: Network },
    { href: "/admin/institutions", label: "Institutions", icon: Building2 },
    { href: "/staff/institutions", label: "Institution onboarding", icon: ClipboardCheck, perm: "admin.institution_onboard" },
    { href: "/admin/opportunities", label: "Opportunities", icon: Inbox },
    { href: "/admin/customers", label: "Customer support", icon: LifeBuoy, perm: "admin.vault_lookup" },
  ]],
  ["Control", [
    { href: "/admin/review", label: "Human Control Centre", icon: ClipboardCheck },
    { href: "/admin/integrity", label: "Integrity", icon: ShieldAlert },
    { href: "/admin/disputes", label: "Disputes", icon: Scale },
    { href: "/admin/commercial", label: "Commercial", icon: Landmark },
  ]],
  ["Inspect", [
    { href: "/admin/graph", label: "Graph Inspector", icon: FileSearch },
    { href: "/admin/loops", label: "Loops & AI", icon: Cpu },
    { href: "/admin/audit", label: "Audit", icon: BookOpen },
    { href: "/admin/deliveries", label: "Events & delivery", icon: Wrench },
    { href: "/admin/config", label: "Configuration", icon: Sliders },
    { href: "/admin/whatsapp", label: "WhatsApp connection", icon: MessageSquareText, perm: "admin.config" },
  ]],
];
// The Weza Staff area (Goal 2): bringing an institution into the marketplace. It is its own area rather than a
// corner of the admin portal, because onboarding an institution is a different job from running the network.
const STAFF_NAV: [string, Item[]][] = [
  ["Onboarding", [
    { href: "/staff/institutions", label: "Institutions", icon: Building2, perm: "admin.institution_onboard" },
  ]],
  ["Network", [
    { href: "/admin", label: "Control Centre", icon: Gauge },
  ]],
];

export function StaffShell({ area, children }: { area: "institution" | "admin" | "staff"; children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [open, setOpen] = useState(false);
  const [bell, setBell] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const pathname = usePathname();

  const load = () => {
    setConnectionError(false);
    return api<Me>("/auth/me")
      .then((m) => {
        if (area !== "institution" && m.kind !== "WEZA") window.location.href = "/institution";
        else if (area === "institution" && m.kind === "WEZA") window.location.href = "/admin";
        else setMe(m);
      })
      .catch(() => setConnectionError(true));
  };

  const connect = async () => {
    setConnecting(true);
    setConnectionError(false);
    try {
    if (!tokens.staff()) {
      // Try the refresh cookie before sending to login.
      const result = await api("/auth/refresh", { body: {}, auth: "none" });
      tokens.setStaff(result.access_token);
    }
    await load();
    } catch (error) {
      if ((error as ApiError).status === 401) window.location.href = `/login?next=${encodeURIComponent(pathname)}`;
      else setConnectionError(true);
    } finally {
      setConnecting(false);
    }
  };

  useEffect(() => {
    void connect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => setOpen(false), [pathname]);

  if (connectionError) return (
    <div className="mx-auto max-w-xl p-8">
      <Card title="We couldn't connect to your workspace">
        <p className="mb-4 text-sm text-muted">Check your connection and try loading your workspace again.</p>
        <Button pending={connecting} onClick={connect}>Retry Connection</Button>
      </Card>
    </div>
  );
  if (!me) return <div className="mx-auto max-w-5xl p-8"><Loading /></div>;
  const can = (p?: string) => !p || me.permissions.includes(p);
  const nav = area === "admin" ? ADMIN_NAV : area === "staff" ? STAFF_NAV : INST_NAV;
  const home = area === "admin" ? "/admin" : area === "staff" ? "/staff/institutions" : "/institution";
  const active = (href: string) => (href === "/institution" || href === "/admin" ? pathname === href : pathname.startsWith(href));

  const sidebar = (
    <nav className="flex h-full flex-col gap-5 overflow-y-auto px-3 py-4 scroll-thin">
      {nav.map(([group, items]) => {
        const visible = items.filter((i) => can(i.perm));
        if (!visible.length) return null;
        return (
          <div key={group}>
            <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-muted">{group}</div>
            {visible.map((i) => (
              <Link key={i.href} href={i.href} className={cx("flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[14px]", active(i.href) ? "bg-blue-50 font-medium text-blue-800" : "text-ink hover:bg-canvas")}>
                <i.icon className="h-4 w-4 shrink-0 opacity-80" />
                {i.label}
              </Link>
            ))}
          </div>
        );
      })}
    </nav>
  );

  return (
    <MeCtx.Provider value={{ me, can: (p) => can(p), refresh: load }}>
      <div className="flex min-h-screen">
        <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-line bg-surface lg:block">
          <div className="flex h-14 items-center border-b border-line px-5"><Logo href={home} small /></div>
          {sidebar}
        </aside>
        {open && (
          <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setOpen(false)}>
            <aside className="h-full w-72 bg-surface" onClick={(e) => e.stopPropagation()}>
              <div className="flex h-14 items-center justify-between border-b border-line px-4"><Logo small /><button onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button></div>
              {sidebar}
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur">
            <button className="lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
            <div className="min-w-0 flex-1 truncate text-[14px]">
              {me.institution ? (
                <span className="font-medium text-ink">{me.institution.name} {me.institution.status !== "ACTIVE" && <Badge tone="warning" className="ml-1">{me.institution.status.toLowerCase().replace(/_/g, " ")}</Badge>}</span>
              ) : (
                <span className="font-medium text-ink">{area === "staff" ? "WEZA Staff" : "WEZA Network Operations"}</span>
              )}
            </div>
            <button className="relative rounded-lg p-2 hover:bg-blue-50" onClick={() => setBell(!bell)} aria-label="Notifications">
              <Bell className="h-5 w-5 text-muted" />
              {me.unread_notifications > 0 && <span className="num absolute right-1 top-1 rounded-full bg-gold-500 px-1 text-[10px] font-bold text-[#1d1704]">{me.unread_notifications > 99 ? "99+" : me.unread_notifications}</span>}
            </button>
            <div className="hidden text-right text-[12px] leading-tight sm:block">
              <div className="font-medium text-ink">{me.full_name}</div>
              <div className="text-muted">{me.roles.map((r) => me.role_labels[r]).join(", ")}</div>
            </div>
            <button onClick={staffLogout} className="rounded-lg p-2 hover:bg-blue-50" aria-label="Sign out" title="Sign out"><LogOut className="h-4 w-4 text-muted" /></button>
          </header>
          {bell && <NotificationPanel area={area} onClose={() => { setBell(false); load(); }} />}
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{children}</main>
        </div>
      </div>
    </MeCtx.Provider>
  );
}

function NotificationPanel({ area, onClose }: { area: string; onClose: () => void }) {
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => {
    api(area === "institution" ? "/inst/notifications" : "/admin/notifications").then((r) => setItems(r.notifications)).catch(() => setItems([]));
  }, [area]);
  async function readAll() {
    if (area === "institution") await api("/inst/notifications/read-all", { method: "POST" }).catch(() => undefined);
    onClose();
  }
  return (
    <div className="fixed right-2 top-14 z-40 w-[min(420px,calc(100vw-1rem))] rounded-xl border border-line bg-surface shadow-xl">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="font-semibold">Notifications</span>
        <div className="flex gap-3 text-[13px]"><button onClick={readAll} className="text-blue-800">Mark all read</button><button onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></button></div>
      </div>
      <div className="max-h-[60vh] overflow-y-auto scroll-thin">
        {items === null ? <div className="p-4"><Loading rows={2} /></div> : items.length === 0 ? <p className="p-6 text-center text-[14px] text-muted">You're all caught up.</p> : items.map((n) => (
          <Link key={n.id} href={n.link || "#"} onClick={async () => { if (area === "institution") await api(`/inst/notifications/${n.id}/ack`, { method: "POST" }).catch(() => undefined); onClose(); }} className={cx("block border-b border-line px-4 py-3 hover:bg-canvas", !n.read && "bg-blue-50/60")}>
            <div className="flex items-start justify-between gap-2">
              <span className="text-[14px] font-medium text-ink">{n.title}</span>
              {n.priority !== "NORMAL" && <Badge tone={n.priority === "URGENT" ? "danger" : "gold"}>{n.priority.toLowerCase()}</Badge>}
            </div>
            {n.body && <p className="text-[13px] text-muted">{n.body}</p>}
            <p className="text-[11px] text-muted">{ago(n.at)}{n.ack_required && !n.acked && " · acknowledgement required"}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
