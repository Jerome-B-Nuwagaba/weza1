import Link from "next/link";

/** Placeholder wordmark until the Product Owner supplies the WEZA logo. */
export function Logo({ href = "/", small }: { href?: string; small?: boolean }) {
  return (
    <Link href={href} className="inline-flex items-center gap-2" aria-label="WEZA home">
      <svg width={small ? 22 : 26} height={small ? 22 : 26} viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="var(--blue-600)" />
        <path d="M7 10l4 12 5-9 5 9 4-12" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="25.5" cy="7" r="2.6" fill="var(--gold-500)" />
      </svg>
      <span className={small ? "text-[16px] font-bold tracking-[0.12em] text-ink" : "text-[19px] font-bold tracking-[0.14em] text-ink"}>WEZA</span>
    </Link>
  );
}
