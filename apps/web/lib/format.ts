const trim = (s: string) => (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s);

export function money(v: number | null | undefined, currency = "UGX"): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (a >= 1e9) return `${sign}${currency} ${trim((a / 1e9).toFixed(a >= 1e10 ? 1 : 2))}B`;
  if (a >= 1e6) return `${sign}${currency} ${trim((a / 1e6).toFixed(a >= 1e8 ? 0 : 1))}M`;
  if (a >= 1e3) return `${sign}${currency} ${Math.round(a / 1e3)}K`;
  return `${sign}${currency} ${a.toLocaleString()}`;
}

export function moneyFull(v: number | null | undefined, currency = "UGX"): string {
  if (v === null || v === undefined) return "—";
  return `${currency} ${Math.round(v).toLocaleString("en-UG")}`;
}

export function dateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function date(iso?: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function ago(iso?: string | null): string {
  if (!iso) return "—";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function minutesLabel(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  const neg = m < 0;
  const a = Math.abs(m);
  const t = a >= 1440 ? `${Math.floor(a / 1440)}d ${Math.floor((a % 1440) / 60)}h` : a >= 60 ? `${Math.floor(a / 60)}h ${a % 60}m` : `${a}m`;
  return neg ? `${t} overdue` : `in ${t}`;
}

export const label = (s?: string | null) =>
  !s ? "—" : s.replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());

export const STATE_LABEL: Record<string, string> = {
  QUALIFIED: "Qualified",
  ROUTED: "Routed",
  RECEIVED: "Received",
  ASSIGNED: "Assigned",
  CONTACTED: "Contacted",
  INFORMATION_REQUESTED: "More information requested",
  PROCEEDING: "Proceeding",
  SUBMITTED_TO_INSTITUTION: "Submitted internally",
  REPORTED_APPROVED: "Reported approved",
  REPORTED_DECLINED: "Reported declined",
  REPORTED_DISBURSED: "Reported disbursed",
  REMATCH_ELIGIBLE: "Rematch eligible",
  WITHDRAWN: "Withdrawn",
  EXPIRED: "Expired",
  CLOSED: "Closed",
  ROUTING_FAILED: "Routing failed",
};
