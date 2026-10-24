"use client";

import {
  BarChart3, Box, ChevronDown, ChevronLeft, ChevronRight, House, Landmark as Bank,
  Bell, BookOpen, Building2, ClipboardCheck, Cpu, FileSearch, Gauge, Inbox, Landmark, LayoutDashboard, LifeBuoy,
  LogOut, Menu, MessageSquareText, Network, Package, Scale, Settings, ShieldAlert, Sliders, Users, Wrench, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, staffLogout, tokens } from "@/lib/api";
import { ago } from "@/lib/format";
import { ADMIN_SECTIONS, landing, sectionOf, visibleTabs } from "./institutionSections";
import { areaEntry, areaFor, NAV_AREAS, type NavArea } from "@/lib/institutionNav";
import { SectionTabs } from "./SectionTabs";
import { Badge, Button, Card, cx, HeaderSlot, Loading, SkinProvider } from "./ui";

export type Me = {
  id: string; email: string; full_name: string; kind: "INSTITUTION" | "WEZA"; roles: string[]; permissions: string[];
  role_labels: Record<string, string>; institution: { id: string; name: string; status: string } | null;
  mfa_enrolled: boolean; unread_notifications: number;
};

const MeCtx = createContext<{ me: Me; can: (p: string) => boolean; refresh: () => void } | null>(null);
export const useMe = () => useContext(MeCtx)!;

type Item = { href: string; label: string; icon: any; perm?: string; section?: NavArea["key"]; current?: boolean };
// The institution sidebar has one entry per workspace section. Its target, label and visibility come from
// lib/institutionNav, the same source the section tabs use; the page a section opens on depends on the role.
const SECTION_ICONS: Record<NavArea["key"], any> = {
  command: House, opportunities: BarChart3, products: Box, team: Users, settings: Settings,
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
  // Institution and WEZA admin menus are built from the section maps in institutionSections.ts: each entry leads to the
  // first page the user may open, and the pages of the section are its tabs. (The WEZA staff onboarding area keeps its own.)
  const sections = area === "admin" ? ADMIN_SECTIONS : null;
  const sectionHere = sections ? sectionOf(sections, pathname) : undefined;
  const sectionNav: [string, Item[]][] = [];
  for (const sec of sections || []) {
    if (sec.tabs.length && !visibleTabs(sec, can).length) continue;
    const href = landing(sec, can);
    if (!href) continue;
    let group = sectionNav.find(([g]) => g === sec.group);
    if (!group) sectionNav.push((group = [sec.group, []]));
    group[1].push({ href, label: sec.label, icon: sec.icon, current: sectionHere?.key === sec.key });
  }
  const nav = area === "staff" ? STAFF_NAV : area === "institution" ? INST_NAV : sectionNav;
  const home = area === "admin" ? "/admin" : area === "staff" ? "/staff/institutions" : "/institution";
  const here = areaFor(pathname)?.key;
  const active = (i: Item) => i.current ?? (i.section ? i.section === here : i.href === "/admin" ? pathname === i.href : pathname.startsWith(i.href));
  // A section leads to the first page of it this person may open, and is hidden when there is none.
  const target = (i: Item) => (i.section ? areaEntry(NAV_AREAS.find((a) => a.key === i.section)!, can) : can(i.perm) ? i.href : undefined);
  // Every area wears the workspace frame and skin; only the menu, the title and the account links differ.
  const title = area === "institution"
    ? areaFor(pathname)?.label || "Workspace"
    : sectionOf(ADMIN_SECTIONS, pathname)?.label || (area === "staff" ? "WEZA Staff" : "Network Operations");
  const settingsHref = area === "institution" ? "/institution/settings" : area === "admin" && can("admin.config") ? "/admin/config" : undefined;

  return (
    <MeCtx.Provider value={{ me, can: (p) => can(p), refresh: load }}>
      <SkinProvider value="crisp">
        <WorkspaceFrame area={area} me={me} home={home} settingsHref={settingsHref}
          items={nav.flatMap(([, items]) => items).filter((i) => !!target(i))}
          target={target} active={active} section={title}
          open={open} setOpen={setOpen} bell={bell} setBell={setBell} reload={load}>
          {sections ? <HeaderSlot value={<SectionTabs sections={sections} pathname={pathname} can={can} />}>{children}</HeaderSlot> : children}
        </WorkspaceFrame>
      </SkinProvider>
    </MeCtx.Provider>
  );
}

const initials = (name: string) =>
  name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

/** The W monogram from the supplied brand artwork, exported at the exact size it is shown (1x/2x/3x), so every
 * screen maps it pixel for pixel — no browser rescaling, no soft edges on low-end devices. */
function Monogram({ height }: { height: 28 | 32 }) {
  const width = height === 32 ? 65 : 57;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={`/brand/weza-monogram-${height}.png`} srcSet={`/brand/weza-monogram-${height}.png 1x, /brand/weza-monogram-${height}@2x.png 2x, /brand/weza-monogram-${height}@3x.png 3x`}
      width={width} height={height} alt="WEZA" draggable={false} className="block select-none" />
  );
}

const COLLAPSE_KEY = "weza.nav.collapsed";

/** The workspace frame shared by the institution, WEZA admin and WEZA staff areas — the "WEZA Command Centre
 * navigation update" and "Collapsed Command Centre with W icon rail" designs: a soft-surface sidebar with the W
 * monogram (expanded with labels, or collapsed to an icon rail; the chevron on the current item toggles it), and a
 * white top bar with the page title, the institution (institution users only), notifications and the signed-in person. */
function WorkspaceFrame({ area, me, home, settingsHref, items, target, active, section, open, setOpen, bell, setBell, reload, children }: {
  area: "institution" | "admin" | "staff"; me: Me; home: string; settingsHref?: string;
  items: Item[]; target: (i: Item) => string | undefined; active: (i: Item) => boolean; section: string;
  open: boolean; setOpen: (v: boolean) => void; bell: boolean; setBell: (v: boolean) => void; reload: () => void;
  children: React.ReactNode;
}) {
  const [menu, setMenu] = useState<null | "account" | "institution">(null);
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try { setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1"); } catch { /* storage unavailable */ }
  }, []);
  const toggle = () => setCollapsed((c) => {
    try { window.localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1"); } catch { /* storage unavailable */ }
    return !c;
  });
  useEffect(() => {
    if (!menu) return;
    const close = (e: KeyboardEvent) => e.key === "Escape" && setMenu(null);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menu]);
  const live = !me.institution || me.institution.status === "ACTIVE";
  const first = me.full_name.split(/\s+/)[0] || me.full_name;
  // Collapsed, the rail is wide enough for an icon plus the chevron beside Command Centre.
  const rail = collapsed ? "lg:w-[112px]" : "lg:w-[288px]";

  const navList = (labels: boolean) => (
    <ul className="space-y-2 px-3">
      {items.map((i) => {
        const on = active(i);
        const Icon = i.icon;
        return (
          <li key={i.label} className="relative flex items-center">
            <Link href={target(i) ?? i.href} aria-label={labels ? undefined : i.label} aria-current={on ? "page" : undefined}
              title={labels ? undefined : i.label}
              className={cx("flex h-12 items-center rounded-xl text-[16px] transition-colors",
                labels ? cx("w-full gap-4 px-4", i.section === "command" && "lg:pr-11") : "w-12 justify-center",
                on ? "bg-blue-50 font-semibold text-ink" : "font-medium text-[#3c4744] hover:bg-blue-50/60 hover:text-ink dark:text-muted")}>
              <Icon className={cx("h-[22px] w-[22px] shrink-0", on ? "text-evergreen" : "text-[#4a5552] dark:text-muted")}
                strokeWidth={2} fill={on && i.section === "command" ? "currentColor" : "none"} aria-hidden />
              {labels && <span className="min-w-0 flex-1 truncate">{i.label}</span>}
            </Link>
            {/* The collapse control always sits beside Command Centre, whichever section is open. */}
            {i.section === "command" && (
              <button type="button" onClick={toggle} aria-label={collapsed ? "Expand menu" : "Collapse menu"} aria-expanded={!collapsed}
                title={collapsed ? "Expand menu" : "Collapse menu"}
                className={cx("hidden h-8 w-8 items-center justify-center rounded-lg text-ink hover:bg-blue-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-evergreen lg:flex",
                  labels ? "absolute right-3" : "ml-1")}>
                {collapsed ? <ChevronRight className="h-5 w-5" strokeWidth={2} /> : <ChevronLeft className="h-5 w-5" strokeWidth={2} />}
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );

  return (
    <div data-skin="institution" className="min-h-screen bg-canvas text-ink">
      <aside aria-label="Workspace" className={cx("fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-line bg-soft lg:flex", rail)}>
        <div className={cx("flex h-20 shrink-0 items-center", collapsed ? "justify-center" : "px-8")}>
          <Link href={home} aria-label={area === "institution" ? "WEZA — Command Centre" : "WEZA — Home"}><Monogram height={32} /></Link>
        </div>
        <nav aria-label="Workspace sections" className="mt-3">{navList(!collapsed)}</nav>
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setOpen(false)}>
          <aside className="h-full w-72 border-r border-line bg-soft" onClick={(e) => e.stopPropagation()}>
            <div className="flex h-16 items-center justify-between px-6">
              <Monogram height={28} />
              <button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded-lg p-2 text-muted hover:bg-blue-50"><X className="h-5 w-5" /></button>
            </div>
            <nav aria-label="Workspace sections" className="mt-2">{navList(true)}</nav>
          </aside>
        </div>
      )}

      <div className={cx("transition-[padding] duration-150", collapsed ? "lg:pl-[112px]" : "lg:pl-[288px]")}>
        <header className="sticky top-0 z-20 border-b border-line bg-surface">
          <div className="flex h-16 items-center gap-3 px-4 sm:h-20 sm:px-8">
            <button className="-ml-1 rounded-lg p-2 text-muted hover:bg-soft lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
            <span className="lg:hidden"><Monogram height={28} /></span>
            <div className="hidden min-w-0 truncate text-[22px] font-semibold tracking-[-0.01em] text-ink sm:block sm:text-[26px]">{section}</div>
            <div className="ml-auto flex items-center gap-2 sm:gap-4">
              <span aria-hidden className="hidden h-10 w-px bg-line md:block" />
              {me.institution && (
                <div className="relative hidden md:block">
                  <button onClick={() => setMenu(menu === "institution" ? null : "institution")} aria-haspopup="menu" aria-expanded={menu === "institution"}
                    className="flex h-12 items-center gap-3 rounded-xl border border-line bg-surface px-4 text-[15px] font-medium text-ink hover:bg-soft">
                    <Bank className="h-5 w-5 text-ink" strokeWidth={1.75} aria-hidden />
                    <span className="max-w-[12rem] truncate">{me.institution.name}</span>
                    {!live && <Badge tone="warning" dot>Not live</Badge>}
                    <ChevronDown className="h-4 w-4 text-muted" strokeWidth={2} aria-hidden />
                  </button>
                  {menu === "institution" && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
                      <div role="menu" className="absolute right-0 top-14 z-50 w-72 overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
                        <div className="border-b border-line px-4 py-3.5">
                          <div className="truncate text-[15px] font-semibold">{me.institution.name}</div>
                          <div className="mt-1"><Badge tone={live ? "success" : "warning"} dot>{live ? "Live on WEZA" : me.institution.status.toLowerCase().replace(/_/g, " ")}</Badge></div>
                        </div>
                        <Link role="menuitem" href="/institution/settings" onClick={() => setMenu(null)} className="block px-4 py-3 text-[14px] hover:bg-soft">Organisation settings</Link>
                        {!live && <Link role="menuitem" href="/institution/onboarding" onClick={() => setMenu(null)} className="block px-4 py-3 text-[14px] hover:bg-soft">Activation checklist</Link>}
                      </div>
                    </>
                  )}
                </div>
              )}
              <button className="relative rounded-xl p-2.5 text-ink hover:bg-soft" onClick={() => setBell(!bell)}
                aria-label={me.unread_notifications > 0 ? `Notifications (${me.unread_notifications} unread)` : "Notifications"}>
                <Bell className="h-6 w-6" strokeWidth={1.75} />
                {me.unread_notifications > 0 && <span aria-hidden className="absolute right-2.5 top-2 h-2.5 w-2.5 rounded-full bg-danger-dot ring-2 ring-surface" />}
              </button>
              <div className="relative">
                <button onClick={() => setMenu(menu === "account" ? null : "account")} aria-haspopup="menu" aria-expanded={menu === "account"} aria-label="Account"
                  className="flex items-center gap-3 rounded-full py-1 pl-1 pr-2 hover:bg-soft">
                  <span className="flex h-11 w-11 items-center justify-center rounded-full bg-leaf-tint text-[15px] font-semibold text-evergreen">{initials(me.full_name)}</span>
                  <span className="hidden text-[15px] font-medium text-ink sm:block">{first}</span>
                  <ChevronDown className="hidden h-4 w-4 text-muted sm:block" strokeWidth={2} aria-hidden />
                </button>
                {menu === "account" && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
                    <div role="menu" className="absolute right-0 top-14 z-50 w-72 overflow-hidden rounded-xl border border-line bg-surface shadow-lg">
                      <div className="border-b border-line px-4 py-3.5">
                        <div className="truncate text-[15px] font-semibold">{me.full_name}</div>
                        <div className="truncate text-[13px] text-muted">{me.email}</div>
                        <div className="mt-1 truncate text-[13px] text-muted">{me.roles.map((x) => me.role_labels[x]).join(", ")}</div>
                      </div>
                      {settingsHref && <Link role="menuitem" href={settingsHref} onClick={() => setMenu(null)} className="flex items-center gap-2.5 px-4 py-3 text-[14px] hover:bg-soft"><Settings className="h-4 w-4 text-muted" />Settings</Link>}
                      <button role="menuitem" onClick={staffLogout} className="flex w-full items-center gap-2.5 px-4 py-3 text-left text-[14px] hover:bg-soft"><LogOut className="h-4 w-4 text-muted" />Sign out</button>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        </header>
        {bell && <NotificationPanel area={area} top="top-20" onClose={() => { setBell(false); reload(); }} />}
        <main className="w-full max-w-[1560px] px-4 py-6 sm:px-8 sm:py-8">{children}</main>
      </div>
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
