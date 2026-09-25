import { test, expect } from "@playwright/test";

test("unchanged reference host calls authenticated household tools through the relay", async ({ page, request }) => {
  test.skip(!process.env.HIRZ_CARD_LIVE, "Run through scripts.smoke_cards --browser-test");
  // Only discovery is configured; every MCP request reaches the real OAuth-protected server.
  await page.route("http://localhost:8080/api/servers", route => route.fulfill({ contentType: "application/json", body: '["http://127.0.0.1:8082/home/mcp"]' }));
  expect((await request.post("http://127.0.0.1:8082/home/mcp", { headers: { Origin: "http://attacker.example" }, data: {} })).status()).toBe(403);
  await page.goto("http://localhost:8080/?tool=get_household_context");
  await expect(page.getByRole("combobox", { name: "Tool", exact: true })).toHaveValue("get_household_context");
  await expect(page.getByRole("textbox", { name: "Input" })).toHaveValue(/scope/);
  await page.getByRole("textbox", { name: "Input" }).fill('{"scope":"environment"}');
  await page.getByRole("button", { name: "Call Tool", exact: true }).click();
  const frame = page.frameLocator("iframe").frameLocator("iframe");
  await expect(frame.getByRole("heading", { name: "Someone is at the front door" })).toBeVisible();
  await frame.getByRole("button", { name: "Request 10-minute unlock" }).click();
  await expect(frame.getByText(/phone approval.*unavailable/i)).toBeVisible();
  await expect(frame.getByText("Observed: locked")).toBeVisible();
  await expect(frame.getByRole("button", { name: "Approve", exact: true })).toHaveCount(0);
});
