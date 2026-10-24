"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { areaFor, tabIsActive, visibleTabs } from "@/lib/institutionNav";
import { useMe } from "./StaffShell";
import { cx } from "./ui";

/** The tabs of the section being shown. They keep specialised pages discoverable without making each one a
 * sidebar destination, and offer a person only the pages their role may open. Must render inside StaffShell. */
export function InstitutionWorkspaceTabs() {
  const pathname = usePathname() || "/institution";
  const { can } = useMe();
  const area = areaFor(pathname);
  if (!area) return null;
  const tabs = visibleTabs(area, can);
  if (tabs.length < 2) return null;

  return (
    <nav aria-label={`${area.label} sections`} className="mb-6 overflow-x-auto border-b border-line scroll-thin">
      <ul className="flex min-w-max gap-1">
        {tabs.map((tab) => {
          const active = tabIsActive(area, tab, pathname);
          return (
            <li key={tab.href}>
              <Link href={tab.href} aria-current={active ? "page" : undefined}
                className={cx("block whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-blue-600",
                  active ? "border-blue-600 text-blue-800" : "border-transparent text-muted hover:border-blue-200 hover:text-ink")}>
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
