import { test, expect } from "@playwright/test";

test("Check-ins publishes advice and bounds enrichment polling", async ({ page }) => {
  let polls = 0, complete = false;
  await page.clock.install();
  await page.route("**/api/auth/session", route => route.fulfill({ json: { authenticated: true, member: { display_name: "Synthetic member", role: "owner" } } }));
  await page.route("**/api/checkins", route => {
    polls++;
    return route.fulfill({ json: { received: [], cases: [{ speakable: { headline: "I found no listed warning signs. A trusted-contact check is still available.", details: [complete ? "Additional warning checks completed; possible warning signs are advisory." : "Additional warning checks are in progress."] }, data: { case: { case_id: "synthetic", claim: { text: "Synthetic reported request" }, signals: complete ? [{ signal: "urgency_language" }] : [], extraction: { status: complete ? "complete" : "pending", keyword_signals: [] } } } }] } });
  });
  await page.goto((process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:5173") + "/checkins");
  await expect(page.getByText("Additional warning checks are in progress.")).toBeVisible();
  await page.clock.runFor(31000);
  await page.waitForTimeout(200);
  const stopped = polls;
  await page.clock.runFor(5000);
  expect(polls).toBe(stopped);
  complete = true;
  await page.getByRole("button", { name: "Refresh inbox" }).click();
  await expect(page.getByText("Possible pressure to act quickly")).toBeVisible();
  await page.waitForTimeout(200);
  const settled = polls;
  await page.clock.runFor(5000);
  expect(polls).toBe(settled);
});
