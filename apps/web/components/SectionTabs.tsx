import Link from "next/link";
import { cx } from "./ui";
import { type Section, sectionOf, visibleTabs } from "./institutionSections";

/** The tabs of the section the current page belongs to, styled like the institution workspace tabs (they sit under
 * the page title through HeaderSlot). Hidden when the user can open only one page of it. */
export function SectionTabs({ sections, pathname, can }: { sections: Section[]; pathname: string; can: (p: string) => boolean }) {
  const section = sectionOf(sections, pathname);
  if (!section) return null;
  const tabs = visibleTabs(section, can);
  if (tabs.length < 2) return null;
  // A home tab ("/admin") is current only on itself, not on every page beneath it.
  const isActive = (href: string) => pathname === href || (href !== "/admin" && pathname.startsWith(href + "/"));
  return (
    <nav aria-label={`${section.label} sections`} className="-mx-1 mb-5 overflow-x-auto px-1 pb-1 scroll-thin">
      <ul className="flex min-w-max gap-2">
        {tabs.map((t) => (
          <li key={t.href}>
            <Link href={t.href} aria-current={isActive(t.href) ? "page" : undefined}
              className={cx("flex h-11 items-center whitespace-nowrap rounded-lg border px-5 text-[15px] font-medium transition-colors",
                isActive(t.href) ? "border-evergreen bg-surface font-semibold text-evergreen" : "border-transparent text-[#3c4744] hover:bg-soft hover:text-ink dark:text-muted")}>
              {t.label}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
