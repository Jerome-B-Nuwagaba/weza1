import Link from "next/link";
import { cx } from "./ui";
import { type Section, sectionOf, visibleTabs } from "./institutionSections";

/** The tabs of the section the current page belongs to. Hidden when the user can open only one page of it. */
export function SectionTabs({ sections, pathname, can }: { sections: Section[]; pathname: string; can: (p: string) => boolean }) {
  const section = sectionOf(sections, pathname);
  if (!section) return null;
  const tabs = visibleTabs(section, can);
  if (tabs.length < 2) return null;
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");
  return (
    <nav aria-label={`${section.label} sections`} className="mb-5 flex gap-1 overflow-x-auto border-b border-line scroll-thin">
      {tabs.map((t) => (
        <Link key={t.href} href={t.href} aria-current={isActive(t.href) ? "page" : undefined}
          className={cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-[14px]",
            isActive(t.href) ? "border-blue-600 font-medium text-blue-800" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
