"use client";

import {
  Bell, Building2, Gauge, LogOut, Menu, Network, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, staffLogout, tokens } from "@/lib/api";
import { ago } from "@/lib/format";
import { ADMIN_SECTIONS, SECTIONS, landing, sectionOf, visibleTabs } from "./institutionSections";
import { Logo } from "./Logo";
import { SectionTabs } from "./SectionTabs";
import { Badge, Button, Card, cx, Loading } from "./ui";

export type Me = {
  id: string; email: string; full_name: string; kind: "INSTITUTION" | "WEZA"; roles: string[]; permissions: string[];
  role_labels: Record<string, string>; institution: { id: string; name: string; status: string } | null;
  mfa_enrolled: boolean; unread_notifications: number;
};

const MeCtx = createContext<{ me: Me; can: (p: string) => boolean; refresh: () => void } | null>(null);
export const useMe = () => useContext(MeCtx)!;

type Item = { href: string; label: string; icon: any; perm?: string; current?: boolean };
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
  const sections = area === "institution" ? SECTIONS : area === "admin" ? ADMIN_SECTIONS : null;
  const here = sections ? sectionOf(sections, pathname) : undefined;
  const sectionNav: [string, Item[]][] = [];
  for (const sec of sections || []) {
    if (sec.tabs.length && !visibleTabs(sec, can).length) continue;
    const href = landing(sec, can);
    if (!href) continue;
    let group = sectionNav.find(([g]) => g === sec.group);
    if (!group) sectionNav.push((group = [sec.group, []]));
    group[1].push({ href, label: sec.label, icon: sec.icon, current: here?.key === sec.key });
  }
  const nav = area === "staff" ? STAFF_NAV : sectionNav;
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
              <Link key={i.href} href={i.href} aria-current={(i.current ?? active(i.href)) ? "page" : undefined} className={cx("flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[14px]", (i.current ?? active(i.href)) ? "bg-blue-50 font-medium text-blue-800" : "text-ink hover:bg-canvas")}>
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
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">{sections && <SectionTabs sections={sections} pathname={pathname} can={can} />}{children}</main>
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
