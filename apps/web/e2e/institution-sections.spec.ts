import { expect, test } from "@playwright/test";
import { signIn } from "./helpers";

/** Smoke test: all 21 institution sections render for every institution role — no crash, no runtime/console
 * error, no "Application error" screen. Split by role × section group so each test has its own time budget. */
const GROUPS: Record<string, string[]> = {
  Work: ["/institution", "/institution/my-day", "/institution/feed", "/institution/priority", "/institution/previews", "/institution/team"],
  Supply: ["/institution/products", "/institution/appetite", "/institution/sandbox"],
  Intelligence: ["/institution/radius", "/institution/demand", "/institution/product-opportunity",
    "/institution/insights", "/institution/ask", "/institution/reports"],
  Workspace: ["/institution/onboarding", "/institution/users", "/institution/routing", "/institution/notifications",
    "/institution/billing", "/institution/audit", "/institution/settings"],
};

// Institution roles (INST_ADMIN, MANAGER, OFFICER, EXECUTIVE, CREDIT_RISK, BUSINESS) at a demo bank
const ROLES = ["admin@lakeside.demo", "manager@lakeside.demo", "officer@lakeside.demo", "exec@lakeside.demo",
  "credit@lakeside.demo", "business@lakeside.demo"];

for (const email of ROLES) {
  for (const [group, paths] of Object.entries(GROUPS)) {
    test(`${group} sections render for ${email}`, async ({ page }) => {
      test.setTimeout(120_000);
      const errors: string[] = [];
      page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
      page.on("console", (m) => {
        // A 403/404 on data a role may not see is expected; React/runtime errors are not.
        if (m.type() === "error" && !/Failed to load resource|status of 40[134]/.test(m.text())) errors.push(m.text());
      });
      await signIn(page, email);
      for (const path of paths) {
        const before = errors.length;
        await page.goto(path);
        await expect(page.locator("main h1, main h2, main [role=status], main [role=alert]").first(),
          `${path} showed no content`).toBeVisible({ timeout: 30_000 });
        await expect(page.locator("main [aria-busy=true]"), `${path} never finished loading`).toHaveCount(0,
          { timeout: 30_000 });
        await expect(page.getByText("Application error", { exact: false }), `${path} crashed`).toHaveCount(0);
        // "You don't have access to this" is a correct answer for some roles; a server error never is.
        await expect(page.getByText("Something went wrong"), `${path} hit a server error`).toHaveCount(0);
        expect(errors.slice(before), `${path} logged errors`).toEqual([]);
      }
    });
  }
}
