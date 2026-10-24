"use client";

import Link from "next/link";
import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import type { ApiError } from "@/lib/api";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

/** "crisp" is the institution workspace look (the 2026-10 mockups); "default" keeps the staff/admin look.
 * StaffShell provides it, so a page never chooses its own skin. */
export type Skin = "default" | "crisp";
const SkinCtx = createContext<Skin>("default");
export const SkinProvider = SkinCtx.Provider;
export const useSkin = () => useContext(SkinCtx);

/** Content a section places directly under every page title — the institution workspace's section tabs. */
const HeaderSlotCtx = createContext<ReactNode>(null);
export const HeaderSlot = HeaderSlotCtx.Provider;

type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "gold";

export function Button({
  children, variant = "primary", size = "md", pending, className, href, ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md" | "lg"; pending?: boolean; href?: string }) {
  const crisp = useSkin() === "crisp";
  const cls = cx(
    "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap",
    crisp
      ? size === "sm" ? "h-9 px-3.5 text-[13px]" : size === "lg" ? "h-12 px-6 text-base" : "h-11 px-5 text-[15px]"
      : size === "sm" ? "h-8 px-3 text-[13px]" : size === "lg" ? "h-12 px-6 text-base" : "h-10 px-4 text-sm",
    variant === "primary" && (crisp ? "bg-evergreen text-white hover:bg-evergreen-hover active:bg-evergreen-press dark:text-[#06120f]"
      : "bg-blue-600 text-white hover:bg-blue-700 dark:text-[#07111a]"),
    variant === "secondary" && (crisp ? "border border-line bg-surface text-evergreen hover:bg-soft active:bg-blue-50"
      : "border border-line bg-surface text-ink hover:bg-blue-50"),
    variant === "ghost" && "text-blue-800 hover:bg-blue-50",
    variant === "danger" && "bg-danger text-white hover:opacity-90",
    variant === "gold" && "bg-gold-500 text-[#1d1704] hover:opacity-90",
    className,
  );
  if (href)
    return (
      <Link href={href} className={cls} onClick={rest.onClick as any}>
        {children}
      </Link>
    );
  return (
    <button className={cls} disabled={pending || rest.disabled} {...rest}>
      {pending && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ children, className, title, action, subtitle }: { children: ReactNode; className?: string; title?: ReactNode; action?: ReactNode; subtitle?: ReactNode }) {
  if (useSkin() === "crisp")
    return (
      <section className={cx("rounded-xl border border-line bg-surface", className)}>
        {(title || action) && (
          <header className="flex items-start justify-between gap-3 px-6 pb-1 pt-5">
            <div className="min-w-0">
              {title && <h2 className="text-[20px] font-bold leading-7 tracking-[-0.01em] text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-[14px] leading-5 text-muted">{subtitle}</p>}
            </div>
            {action}
          </header>
        )}
        <div className={title || action ? "px-6 pb-6 pt-4" : "p-6"}>{children}</div>
      </section>
    );
  return (
    <section className={cx("rounded-xl border border-line bg-surface", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div>
            {title && <h2 className="text-[15px] font-semibold text-ink">{title}</h2>}
            {subtitle && <p className="text-[13px] text-muted">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  const crisp = useSkin() === "crisp";
  const slot = useContext(HeaderSlotCtx);
  if (crisp)
    return (
      <>
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          {eyebrow && <div className="mb-1.5 text-[13px] font-semibold text-blue-600">{eyebrow}</div>}
          <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-ink sm:text-[32px]">{title}</h1>
          {subtitle && <p className="mt-1.5 max-w-3xl text-[15px] text-muted sm:text-[16px]">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-3 sm:shrink-0">{actions}</div>}
      </div>
      {slot}
      </>
    );
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <div className="mb-1 text-[12px] font-semibold uppercase tracking-wider text-blue-800">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-[14px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

const TONES: Record<string, string> = {
  neutral: "bg-blue-50 text-blue-800 border-blue-100",
  gold: "bg-gold-100 text-gold-700 border-gold-500/30",
  success: "bg-success-bg text-success border-success/20",
  warning: "bg-warning-bg text-warning border-warning/20",
  danger: "bg-danger-bg text-danger border-danger/20",
  muted: "bg-canvas text-muted border-line",
};

// [background, label colour, dot colour] — status is never colour alone (brief §4): the label always says it.
const CRISP_TONES: Record<string, [string, string, string]> = {
  neutral: ["bg-info-bg", "text-info", "bg-info-dot"],
  gold: ["bg-warning-bg", "text-warning", "bg-warning-dot"],
  success: ["bg-success-bg", "text-success", "bg-success-dot"],
  warning: ["bg-warning-bg", "text-warning", "bg-warning-dot"],
  danger: ["bg-danger-bg", "text-danger", "bg-danger-dot"],
  muted: ["bg-soft", "text-muted", "bg-muted"],
};

export function Badge({ children, tone = "neutral", className, dot }: { children: ReactNode; tone?: keyof typeof TONES | string; className?: string; dot?: boolean }) {
  if (useSkin() === "crisp") {
    const [bg, fg, dotColour] = CRISP_TONES[tone] || CRISP_TONES.neutral;
    return (
      <span className={cx("inline-flex h-7 items-center gap-2 whitespace-nowrap rounded-md px-2.5 text-[13px] font-medium", bg, dot ? "text-ink" : fg, className)}>
        {dot && <span aria-hidden className={cx("h-2 w-2 shrink-0 rounded-full", dotColour)} />}
        {children}
      </span>
    );
  }
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[12px] font-medium", TONES[tone] || TONES.neutral, className)}>
      {children}
    </span>
  );
}

export function stateTone(state?: string | null): string {
  if (!state) return "muted";
  if (["REPORTED_DISBURSED", "REPORTED_APPROVED", "ACTIVE", "APPROVED", "READY", "READY_NOW", "DONE", "FRESH", "GRANTED", "MET", "ON_TRACK", "CLOSED_OK"].includes(state)) return "success";
  if (["REPORTED_DECLINED", "ROUTING_FAILED", "SUSPENDED", "REJECTED", "BREACHED", "ESCALATED", "DEAD", "BLOCKED", "EXPIRED", "STALE", "WITHDRAWN", "FULL", "HIGH_RISK"].includes(state)) return "danger";
  if (["PENDING_APPROVAL", "SIMULATED", "UNDER_VERIFICATION", "SUBMITTED", "APPROACHING", "ATTENTION_REQUIRED", "LIMITED", "PAUSED", "ALMOST_READY", "REVIEW", "OPEN", "DRAFT", "DISPUTED"].includes(state)) return "warning";
  return "neutral";
}

export function StateBadge({ state, label }: { state?: string | null; label?: string }) {
  return <Badge tone={stateTone(state)} dot>{label || (state ? state.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase()) : "—")}</Badge>;
}

export function Stat({ label, value, sub, tone, href }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "gold" | "default"; href?: string }) {
  if (useSkin() === "crisp") {
    const tile = (
      <div className={cx("h-full rounded-xl border bg-surface p-5 transition-colors", tone === "gold" ? "border-gold-500/40" : "border-line", href && "hover:border-blue-400")}>
        <div className="text-[14px] font-medium text-muted">{label}</div>
        <div className={cx("num mt-1.5 text-[28px] font-bold leading-none tracking-[-0.02em]", tone === "gold" ? "text-gold-700" : "text-ink")}>{value ?? "—"}</div>
        {sub && <div className="mt-2 text-[13px] text-muted">{sub}</div>}
      </div>
    );
    return href ? <Link href={href}>{tile}</Link> : tile;
  }
  const body = (
    <div className={cx("h-full rounded-xl border bg-surface p-4", tone === "gold" ? "border-gold-500/40" : "border-line", href && "hover:border-blue-400")}>
      <div className="text-[12px] font-medium text-muted">{label}</div>
      <div className={cx("num mt-1 text-2xl font-semibold tracking-tight", tone === "gold" ? "text-gold-700" : "text-ink")}>{value ?? "—"}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

export function ScoreRing({ score, size = 44 }: { score: number; size?: number }) {
  const r = (size - 6) / 2;
  const c = 2 * Math.PI * r;
  const crisp = useSkin() === "crisp";
  const gold = score >= 90 && !crisp;
  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }} title={`Match ${Math.round(score)} — fit with current criteria, not an approval`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--border)" strokeWidth={4} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={gold ? "var(--gold-500)" : "var(--blue-600)"} strokeWidth={4} fill="none" strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(100, score) / 100)} strokeLinecap="round" />
      </svg>
      <span className={cx("num absolute text-[13px] font-semibold", gold ? "text-gold-700" : "text-ink")}>{Math.round(score)}</span>
    </div>
  );
}

export function Bar({ value, max = 1, tone = "blue" }: { value: number; max?: number; tone?: "blue" | "gold" }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-blue-50">
      <div className={cx("h-full rounded-full", tone === "gold" ? "bg-gold-500" : "bg-blue-600")} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Horizontal bar list — every chart has its numbers visible (blueprint accessibility rule). */
export function BarList({ data, format = (v: number) => v.toLocaleString(), empty = "No data yet." }: { data: Record<string, number> | [string, number][]; format?: (v: number) => string; empty?: string }) {
  const rows = Array.isArray(data) ? data : Object.entries(data || {});
  if (!rows.length) return <p className="text-[13px] text-muted">{empty}</p>;
  const max = Math.max(...rows.map(([, v]) => v));
  return (
    <ul className="space-y-2.5">
      {rows.map(([k, v]) => (
        <li key={k}>
          <div className="mb-1 flex justify-between gap-2 text-[13px]">
            <span className="truncate text-ink">{k}</span>
            <span className="num text-muted">{format(v)}</span>
          </div>
          <Bar value={v} max={max} />
        </li>
      ))}
    </ul>
  );
}

export function Sparkbars({ values, height = 56 }: { values: number[]; height?: number }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex items-end gap-1" style={{ height }} role="img" aria-label={`Trend: ${values.join(", ")}`}>
      {values.map((v, i) => (
        <div key={i} className="flex-1 rounded-t bg-blue-400/70" style={{ height: `${Math.max(4, (v / max) * 100)}%` }} title={String(v)} />
      ))}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton h-4", className)} />;
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={i === 0 ? "h-6 w-1/3" : "h-14 w-full"} />
      ))}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  const e = error as ApiError;
  if (e.status === 403)
    return <Banner tone="warning" title="You don't have access to this">Ask your administrator if you need it.</Banner>;
  return (
    <Banner tone="danger" title="Something went wrong">
      <span>{e.message}</span>
      {e.correlationId && <span className="block text-[12px] opacity-75">Reference: {e.correlationId}</span>}
      {onRetry && (
        <button onClick={onRetry} className="mt-2 text-[13px] font-medium underline">
          Try again
        </button>
      )}
    </Banner>
  );
}

export function Banner({ tone = "info", title, children, className }: { tone?: "info" | "warning" | "danger" | "success" | "gold"; title?: ReactNode; children?: ReactNode; className?: string }) {
  const crisp = useSkin() === "crisp";
  const Icon = tone === "success" ? CheckCircle2 : tone === "info" || tone === "gold" ? Info : AlertTriangle;
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cx(
        "flex gap-3 border text-[14px]",
        crisp ? "rounded-xl px-5 py-4" : "rounded-xl px-4 py-3",
        tone === "info" && "border-blue-100 bg-blue-50 text-blue-800",
        tone === "gold" && "border-gold-500/30 bg-gold-100 text-gold-700",
        tone === "warning" && "border-warning/25 bg-warning-bg text-warning",
        tone === "danger" && "border-danger/25 bg-danger-bg text-danger",
        tone === "success" && "border-success/25 bg-success-bg text-success",
        className,
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div>
        {title && <div className="font-semibold">{title}</div>}
        {children && <div className="text-[13.5px] opacity-90">{children}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  const crisp = useSkin() === "crisp";
  return (
    <div className={cx("border border-dashed border-line bg-surface px-6 text-center", crisp ? "rounded-xl py-12" : "rounded-xl py-10")}>
      <div className="text-[15px] font-semibold text-ink">{title}</div>
      {children && <div className="mx-auto mt-1 max-w-lg text-[14px] text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Field({ label, hint, error, children, required }: { label: string; hint?: ReactNode; error?: string; children: ReactNode; required?: boolean }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[13px] font-medium text-ink">
        {label}
        {required && <span className="text-danger"> *</span>}
      </span>
      {children}
      {hint && !error && <span className="mt-1 block text-[12px] text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-[12px] text-danger">{error}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-muted/70 focus:border-blue-400 focus:outline-none";

export function Input(p: React.InputHTMLAttributes<HTMLInputElement>) {
  const crisp = useSkin() === "crisp";
  return <input {...p} className={cx(inputCls, crisp ? "h-11 text-[15px]" : "h-10", p.className)} />;
}

export function Textarea(p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...p} className={cx(inputCls, p.className)} />;
}

export function Select({ options, ...p }: React.SelectHTMLAttributes<HTMLSelectElement> & { options: ([string, string] | string)[] }) {
  const crisp = useSkin() === "crisp";
  return (
    <select {...p} className={cx(inputCls, crisp ? "h-11 pr-8 text-[15px]" : "h-10", p.className)}>
      {options.map((o) => {
        const [v, l] = Array.isArray(o) ? o : [o, o];
        return (
          <option key={v} value={v}>
            {l}
          </option>
        );
      })}
    </select>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const crisp = useSkin() === "crisp";
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 p-0 sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" className={cx("max-h-[92vh] w-full overflow-auto rounded-t-2xl bg-surface shadow-xl sm:rounded-2xl", crisp && "border border-line", wide ? "sm:max-w-3xl" : "sm:max-w-lg")} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <h3 className="text-[16px] font-semibold">{title}</h3>
          <button aria-label="Close" onClick={onClose} className="rounded p-1 text-muted hover:bg-blue-50">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: [string, string][]; value: string; onChange: (v: string) => void }) {
  if (useSkin() === "crisp")
    return (
      <div className="mb-5 flex gap-2 overflow-x-auto pb-0.5 scroll-thin" role="tablist">
        {tabs.map(([v, l]) => (
          <button key={v} role="tab" aria-selected={value === v} onClick={() => onChange(v)} className={cx("h-10 whitespace-nowrap rounded-lg border px-4 text-[15px] font-medium transition-colors", value === v ? "border-evergreen bg-surface text-evergreen" : "border-transparent text-muted hover:bg-soft hover:text-ink")}>
            {l}
          </button>
        ))}
      </div>
    );
  return (
    <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line" role="tablist">
      {tabs.map(([v, l]) => (
        <button key={v} role="tab" aria-selected={value === v} onClick={() => onChange(v)} className={cx("whitespace-nowrap border-b-2 px-3 py-2 text-[14px] font-medium", value === v ? "border-blue-600 text-blue-800" : "border-transparent text-muted hover:text-ink")}>
          {l}
        </button>
      ))}
    </div>
  );
}

export function Table({ head, children, empty, bare }: { head: ReactNode[]; children: ReactNode; empty?: boolean; bare?: boolean }) {
  if (useSkin() === "crisp")
    return (
      <div className={cx("scroll-thin overflow-x-auto bg-surface", !bare && "rounded-xl border border-line")}>
        <table className="w-full min-w-[640px] text-left text-[14px]">
          <thead className="border-b border-line bg-soft text-[12px] uppercase tracking-[0.06em] text-muted">
            <tr>
              {head.map((h, i) => (
                <th key={i} className="whitespace-nowrap px-5 py-3.5 font-semibold">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line [&>tr]:transition-colors [&>tr:hover]:bg-soft/60">{children}</tbody>
        </table>
        {empty && <div className="px-5 py-10 text-center text-[14px] text-muted">Nothing to show.</div>}
      </div>
    );
  return (
    <div className="scroll-thin overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full min-w-[640px] text-left text-[13.5px]">
        <thead className="border-b border-line bg-canvas text-[12px] uppercase tracking-wide text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-4 py-2.5 font-semibold">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
      {empty && <div className="px-4 py-8 text-center text-[14px] text-muted">Nothing to show.</div>}
    </div>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  const crisp = useSkin() === "crisp";
  return <td className={cx(crisp ? "px-5 py-4 align-middle" : "px-4 py-3 align-top", className)}>{children}</td>;
}

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [message, onDone]);
  if (!message) return null;
  return (
    <div className="fixed bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-navy px-4 py-2.5 text-[14px] text-surface shadow-lg" role="status">
      {message}
    </div>
  );
}

export function useToast() {
  const [msg, setMsg] = useState<string | null>(null);
  return { toast: setMsg, node: <Toast message={msg} onDone={() => setMsg(null)} /> };
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {items.map(([k, v], i) => (
        <div key={i} className="flex justify-between gap-3 border-b border-line/60 py-1.5 text-[14px]">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right font-medium text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ReasonChips({ matched = [], near = [], missing = [] }: { matched?: string[]; near?: string[]; missing?: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {matched.map((m) => (
        <Badge key={"m" + m} tone="success">✓ {m}</Badge>
      ))}
      {near.map((m) => (
        <Badge key={"n" + m} tone="warning">~ {m}</Badge>
      ))}
      {missing.map((m) => (
        <Badge key={"x" + m} tone="danger">! {m}</Badge>
      ))}
    </div>
  );
}
