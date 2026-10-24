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
    <nav aria-label={`${area.label} sections`} className="-mx-1 mb-5 overflow-x-auto px-1 pb-1 scroll-thin">
      <ul className="flex min-w-max gap-2">
        {tabs.map((tab) => {
          const active = tabIsActive(area, tab, pathname);
          return (
            <li key={tab.href}>
              <Link href={tab.href} aria-current={active ? "page" : undefined}
                className={cx("flex h-11 items-center whitespace-nowrap rounded-lg border px-5 text-[15px] font-medium transition-colors",
                  active ? "border-evergreen bg-surface font-semibold text-evergreen" : "border-transparent text-[#3c4744] hover:bg-soft hover:text-ink dark:text-muted")}>
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
