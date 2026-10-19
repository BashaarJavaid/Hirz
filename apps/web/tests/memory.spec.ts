import { test, expect } from "@playwright/test";
import { accessibility } from "./accessibility";

// Presentation-only fixtures; real subject/session isolation is tested in Postgres.
for (const width of [390, 1280]) {
  test(`Preference consent at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    const proposals = [73, 74].map((value, index) => ({
      id: `synthetic-private-${index}`, candidate: { key: "temperature_target_f", value },
      created_at: "2026-10-19T18:00:00Z", audit_seq: index + 1,
    }));
    let pending = proposals.slice(), refuse = true;
    const requests: Record<string, unknown>[] = [];
    await page.route("**/api/auth/session", route => route.fulfill({ json: { authenticated: true, csrf: "synthetic-csrf", member: { display_name: "Synthetic member", role: "adult" } } }));
    await page.route("**/api/household", route => route.fulfill({ json: { graph: { members: [], assets: [] }, credentials: [] } }));
    await page.route("**/api/contacts", route => route.fulfill({ json: { links: [] } }));
    await page.route("**/api/memory/proposals?*", route => route.fulfill({ json: pending }));
    await page.route("**/api/memory/review", async route => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      expect(Object.keys(body).sort()).toEqual(["accept", "proposal_id", "request_id"]);
      expect(typeof body.request_id).toBe("string");
      expect(route.request().headers()["x-hirz-csrf"]).toBe("synthetic-csrf");
      requests.push(body);
      if (refuse) return route.fulfill({ json: { decision: { decision: "deny" }, record: null } });
      pending = pending.filter(p => p.id !== body.proposal_id);
      return route.fulfill({ json: { decision: { decision: "execute" }, record: { status: body.accept ? "accepted" : "rejected" } } });
    });
    await page.goto((process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:5173") + "/household");
    await expect(page.getByRole("heading", { name: "Prefer 73°F?" })).toBeVisible();
    await expect(page.getByText("synthetic-private", { exact: false })).toHaveCount(0);
    await accessibility(page);
    await page.getByRole("button", { name: "Remember 73°F", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("This suggestion could not be updated");
    await expect(page.getByRole("heading", { name: "Prefer 73°F?" })).toBeVisible();
    refuse = false;
    await page.getByRole("button", { name: "Remember 73°F", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("Your temperature preference was saved.");
    await expect(page.getByRole("heading", { name: "Prefer 73°F?" })).toHaveCount(0);
    await page.getByRole("button", { name: "Don’t remember", exact: true }).click();
    await expect(page.getByRole("status")).toHaveText("The suggestion was dismissed.");
    await expect(page.getByText("No suggestions to review on this page.")).toBeVisible();
    expect(requests.map(r => r.accept)).toEqual([true, true, false]);
    expect(new Set(requests.map(r => r.request_id)).size).toBe(3);
    await page.getByRole("button", { name: "Refresh suggestions" }).click();
    await expect(page.getByText("No suggestions to review on this page.")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test("Preference review pages use the last audit cursor", async ({ page }) => {
  const cursors: number[] = [];
  await page.route("**/api/auth/session", route => route.fulfill({ json: { authenticated: true, member: { display_name: "Synthetic member", role: "adult" } } }));
  await page.route("**/api/household", route => route.fulfill({ json: { graph: { members: [], assets: [] }, credentials: [] } }));
  await page.route("**/api/contacts", route => route.fulfill({ json: { links: [] } }));
  await page.route("**/api/memory/proposals?*", route => {
    const after = Number(new URL(route.request().url()).searchParams.get("after"));
    cursors.push(after);
    return route.fulfill({ json: after ? [] : Array.from({ length: 50 }, (_, index) => ({
      id: `synthetic-${index}`, candidate: { key: "temperature_target_f", value: 73 },
      created_at: "2026-10-19T18:00:00Z", audit_seq: 100 + index,
    })) });
  });
  await page.goto((process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:5173") + "/household");
  await page.getByRole("button", { name: "More suggestions" }).click();
  await expect(page.getByText("No suggestions to review on this page.")).toBeVisible();
  await page.getByRole("button", { name: "Back to first suggestions" }).click();
  await expect(page.getByRole("button", { name: "More suggestions" })).toBeVisible();
  expect(cursors).toEqual([0, 149, 0]);
});
