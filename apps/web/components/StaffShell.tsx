"use client";

import {
  Box, ChevronDown, House, Target,
  Bell, BookOpen, Building2, ClipboardCheck, Cpu, FileSearch, Gauge, Inbox, Landmark, LayoutDashboard, LifeBuoy,
  LogOut, Menu, MessageSquareText, Network, Package, Scale, Settings, ShieldAlert, Sliders, Users, Wrench, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, staffLogout, tokens } from "@/lib/api";
import { ago } from "@/lib/format";
import { areaEntry, areaFor, NAV_AREAS, type NavArea } from "@/lib/institutionNav";
import { Logo } from "./Logo";
import { Badge, Button, Card, cx, Loading, SkinProvider } from "./ui";

export type Me = {
  id: string; email: string; full_name: string; kind: "INSTITUTION" | "WEZA"; roles: string[]; permissions: string[];
  role_labels: Record<string, string>; institution: { id: string; name: string; status: string } | null;
  mfa_enrolled: boolean; unread_notifications: number;
};

const MeCtx = createContext<{ me: Me; can: (p: string) => boolean; refresh: () => void } | null>(null);
export const useMe = () => useContext(MeCtx)!;

type Item = { href: string; label: string; icon: any; perm?: string; section?: NavArea["key"] };
// The institution sidebar has one entry per workspace section. Its target, label and visibility come from
// lib/institutionNav, the same source the section tabs use; the page a section opens on depends on the role.
const SECTION_ICONS: Record<NavArea["key"], any> = {
  command: House, opportunities: Target, products: Box, team: Users, settings: Settings,
};
const INST_GROUPS: [string, NavArea["key"][]][] = [
  ["Work", ["command", "opportunities"]],
  ["Configure", ["products", "team"]],
  ["Workspace", ["settings"]],
];
const INST_NAV: [string, Item[]][] = INST_GROUPS.map(([group, keys]) => [group, keys.map((key) => {
  const a = NAV_AREAS.find((x) => x.key === key)!;
  return { href: a.tabs[0].href, label: a.label, icon: SECTION_ICONS[key], section: key };
})]);
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
  const here = areaFor(pathname)?.key;
  const active = (i: Item) => (i.section ? i.section === here : i.href === "/admin" ? pathname === i.href : pathname.startsWith(i.href));
  // A section leads to the first page of it this person may open, and is hidden when there is none.
  const target = (i: Item) => (i.section ? areaEntry(NAV_AREAS.find((a) => a.key === i.section)!, can) : i.href);

  if (area === "institution")
    return (
      <MeCtx.Provider value={{ me, can: (p) => can(p), refresh: load }}>
        <SkinProvider value="crisp">
          <InstitutionFrame me={me} items={nav.flatMap(([, items]) => items).filter((i) => !!target(i))}
            target={target} active={active} section={areaFor(pathname)?.label || "Workspace"}
            open={open} setOpen={setOpen} bell={bell} setBell={setBell} reload={load}>
            {children}
          </InstitutionFrame>
        </SkinProvider>
      </MeCtx.Provider>
    );

  const sidebar = (
    <nav className="flex h-full flex-col gap-5 overflow-y-auto px-3 py-4 scroll-thin">
      {nav.map(([group, items]) => {
        const visible = items.filter((i) => (i.section ? !!target(i) : can(i.perm)));
        if (!visible.length) return null;
        return (
          <div key={group}>
            <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wider text-muted">{group}</div>
            {visible.map((i) => (
              <Link key={i.href} href={target(i) ?? i.href} aria-current={active(i) ? "page" : undefined} className={cx("flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[14px]", active(i) ? "bg-blue-50 font-medium text-blue-800" : "text-ink hover:bg-canvas")}>
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

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

/** The institution workspace frame (2026-10 mockups): a full-width top bar — wordmark, the section you are in,
 * today's date, notifications and your account — over a narrow icon rail with one icon per section. */
function InstitutionFrame({ me, items, target, active, section, open, setOpen, bell, setBell, reload, children }: {
  me: Me; items: Item[]; target: (i: Item) => string | undefined; active: (i: Item) => boolean; section: string;
  open: boolean; setOpen: (v: boolean) => void; bell: boolean; setBell: (v: boolean) => void; reload: () => void;
  children: React.ReactNode;
}) {
  const [menu, setMenu] = useState(false);
  const today = new Date().toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric", year: "numeric" });
  const live = !me.institution || me.institution.status === "ACTIVE";
  useEffect(() => {
    if (!menu) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setMenu(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menu]);

  return (
    <div data-skin="institution" className="min-h-screen bg-canvas text-ink">
      <header className="fixed inset-x-0 top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-surface px-4 sm:px-6">
        <button className="-ml-1 rounded-lg p-2 text-muted hover:bg-canvas lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
        <Link href="/institution" className="text-[22px] font-extrabold tracking-[-0.01em] text-blue-600" aria-label="WEZA home">WEZA</Link>
        <span aria-hidden className="hidden h-6 w-px bg-line sm:block" />
        <span className="hidden min-w-0 truncate text-[17px] font-medium text-ink sm:block">{section}</span>
        {!live && (
          <Link href="/institution/onboarding" className="hidden sm:inline-flex">
            <Badge tone="warning" dot>Not live yet</Badge>
          </Link>
        )}
        <div className="ml-auto flex items-center gap-1 sm:gap-3">
          <span className="hidden text-[15px] text-ink md:block">{today}</span>
          <button className="relative rounded-lg p-2 text-muted hover:bg-canvas hover:text-ink" onClick={() => setBell(!bell)} aria-label="Notifications">
            <Bell className="h-5 w-5" />
            {me.unread_notifications > 0 && <span className="num absolute right-1 top-1 min-w-4 rounded-full bg-danger px-1 text-center text-[10px] font-bold leading-4 text-white">{me.unread_notifications > 99 ? "99+" : me.unread_notifications}</span>}
          </button>
          <div className="relative">
            <button onClick={() => setMenu(!menu)} className="flex items-center gap-1.5 rounded-full p-0.5 hover:bg-canvas" aria-haspopup="menu" aria-expanded={menu} aria-label="Account">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#1e3a8a] text-[14px] font-semibold text-white">{initials(me.full_name)}</span>
              <ChevronDown className="mr-1 hidden h-4 w-4 text-muted sm:block" />
            </button>
            {menu && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setMenu(false)} />
                <div role="menu" className="absolute right-0 top-12 z-50 w-72 overflow-hidden rounded-2xl border border-line bg-surface shadow-lg">
                  <div className="border-b border-line px-4 py-3.5">
                    <div className="truncate text-[15px] font-semibold text-ink">{me.full_name}</div>
                    <div className="truncate text-[13px] text-muted">{me.email}</div>
                    <div className="mt-1 truncate text-[13px] text-muted">{me.roles.map((r) => me.role_labels[r]).join(", ")}</div>
                    {me.institution && <div className="mt-2 flex items-center gap-2 text-[13px] text-ink">{me.institution.name}{!live && <Badge tone="warning">{me.institution.status.toLowerCase().replace(/_/g, " ")}</Badge>}</div>}
                  </div>
                  <Link role="menuitem" href="/institution/settings" onClick={() => setMenu(false)} className="flex items-center gap-2.5 px-4 py-2.5 text-[14px] text-ink hover:bg-canvas"><Settings className="h-4 w-4 text-muted" />Settings</Link>
                  <button role="menuitem" onClick={staffLogout} className="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-[14px] text-ink hover:bg-canvas"><LogOut className="h-4 w-4 text-muted" />Sign out</button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      <nav aria-label="Workspace" className="fixed bottom-0 left-0 top-16 z-20 hidden w-[76px] flex-col items-center gap-2 border-r border-line bg-surface py-5 lg:flex">
        {items.map((i) => {
          const on = active(i);
          return (
            <Link key={i.label} href={target(i) ?? i.href} aria-label={i.label} aria-current={on ? "page" : undefined}
              className={cx("group relative flex h-12 w-12 items-center justify-center rounded-xl transition-colors",
                on ? "bg-blue-50 text-blue-600" : "text-[#475569] hover:bg-canvas hover:text-ink dark:text-muted")}>
              <i.icon className="h-[22px] w-[22px]" strokeWidth={1.75} />
              <span role="tooltip" className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 -translate-y-1/2 whitespace-nowrap rounded-md bg-navy px-2.5 py-1 text-[12px] font-medium text-surface opacity-0 shadow-sm transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">{i.label}</span>
            </Link>
          );
        })}
      </nav>

      {open && (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-72 border-r border-line bg-surface" onClick={(e) => e.stopPropagation()}>
            <div className="flex h-16 items-center justify-between border-b border-line px-5">
              <span className="text-[22px] font-extrabold text-blue-600">WEZA</span>
              <button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded-lg p-1.5 text-muted hover:bg-canvas"><X className="h-5 w-5" /></button>
            </div>
            <nav aria-label="Workspace" className="space-y-1 p-3">
              {items.map((i) => (
                <Link key={i.label} href={target(i) ?? i.href} aria-current={active(i) ? "page" : undefined}
                  className={cx("flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium", active(i) ? "bg-blue-50 text-blue-600" : "text-ink hover:bg-canvas")}>
                  <i.icon className="h-5 w-5" strokeWidth={1.75} />{i.label}
                </Link>
              ))}
            </nav>
          </aside>
        </div>
      )}

      {bell && <NotificationPanel area="institution" top="top-16" onClose={() => { setBell(false); reload(); }} />}
      <main className="pt-16 lg:pl-[76px]">
        <div className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-8 sm:py-8">{children}</div>
      </main>
    </div>
  );
}

function NotificationPanel({ area, onClose, top = "top-14" }: { area: string; onClose: () => void; top?: string }) {
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => {
    api(area === "institution" ? "/inst/notifications" : "/admin/notifications").then((r) => setItems(r.notifications)).catch(() => setItems([]));
  }, [area]);
  async function readAll() {
    if (area === "institution") await api("/inst/notifications/read-all", { method: "POST" }).catch(() => undefined);
    onClose();
  }
  return (
    <div className={cx("fixed right-2 z-40 w-[min(420px,calc(100vw-1rem))] rounded-xl border border-line bg-surface shadow-xl", top)}>
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
