import { expect, test } from "@playwright/test";
import { assignTo, customerSharesWithLakeside, signIn } from "./helpers";

/**
 * The institution officer's workspace: a routed opportunity arrives in the officer's own queue, the officer reads
 * what was shared and why, records an internal note and moves the opportunity along the status ladder. The customer
 * sees the status, never the note.
 */
test("the officer works a routed opportunity from their queue to the next action", async ({ page, request }) => {
  const officer = "officer@lakeside.demo";
  const { reference, oppId, customer } = await customerSharesWithLakeside(request);
  await assignTo(request, oppId, officer);

  // ---- the queue: the opportunity is in this officer's own work
  await signIn(page, officer);
  await page.goto("/institution/my-day");
  await expect(page.getByText(reference).first()).toBeVisible();

  // ---- the detail: what was shared, why it matched, and the statuses the officer may record
  await page.goto(`/institution/opportunities/${oppId}`);
  await expect(page.getByRole("heading", { name: reference })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Next action" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Why this matched" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Consent" })).toBeVisible();
  await expect(page.getByText("Shared under the customer's consent")).toBeVisible();
  // The status ladder, starting at "New"
  for (const label of ["New", "Contacted", "More information requested", "In institution review"]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }

  // ---- an internal note: the institution's own record
  await page.getByLabel("Internal note (optional)").fill("Called the customer; statements to follow on Monday.");
  await page.getByRole("button", { name: "Save note only" }).click();
  await expect(page.getByText("Note saved")).toBeVisible();
  await expect(page.getByText("Called the customer; statements to follow on Monday.")).toBeVisible();

  // ---- a status the officer records
  await page.getByRole("button", { name: "More information requested" }).click();
  await expect(page.getByText("Marked more information requested")).toBeVisible();

  // ---- the customer sees the status trail, and never the internal note
  const needs = await (await request.get("/api/v1/me/needs", { headers: customer })).json();
  expect(JSON.stringify(needs)).not.toContain("statements to follow on Monday");
  const mine = needs.needs.flatMap((n: any) => n.opportunities).find((o: any) => o.reference === reference);
  expect(mine.state).toBe("INFORMATION_REQUESTED");
  expect(mine.timeline.map((t: any) => t.label)).toContain("The institution has asked you for more information");
});
