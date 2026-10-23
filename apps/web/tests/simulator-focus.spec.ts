import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
// Focus view against a dev server with mocked simulator routes; no backend, no household data.
const origin = process.env.HIRZ_FOCUS_ORIGIN;
const shots = process.env.HIRZ_FOCUS_SHOTS;
const events = process.env.HIRZ_FOCUS_EVENTS;
const card = process.env.HIRZ_FOCUS_CARD;
const session = { csrf: "c", account: "malik", accounts: { malik: "Malik · Quinn home" }, model: "scripted", models: { scripted: "Scripted host" }, linked: true, generation: 0, prompt: null, busy: false };
const playback = { selected: "demo-evening", playing: false, speed: 1, scenarios: { "demo-evening": { at: "18:40", next: 3, total: 12, beat: null } } };

async function mock(page: Page) {
  const stream = events ? JSON.parse(await readFile(events, "utf8")) as unknown[] : [];
  await page.route("**/api/simulator/session", route => route.fulfill({ json: session }));
  await page.route("**/api/auth/session", route => route.fulfill({ json: {} }));
  await page.route("**/api/simulator/scenarios", route => route.fulfill({ json: playback }));
  await page.route("**/api/simulator/events", route => route.fulfill({ contentType: "text/event-stream", body: stream.map(e => `data: ${JSON.stringify(e)}\n\n`).join("") }));
  if (card) await page.route("**/api/simulator/cards/*", async route => route.fulfill({ contentType: "text/html", body: await readFile(card, "utf8") }));
}

test("focus mode hides playback and F toggles it back", async ({ page }) => {
  test.skip(!origin, "Start the web dev server and set HIRZ_FOCUS_ORIGIN");
  await mock(page);
  await page.goto(`${origin}/simulator?focus=1`);
  await expect(page.getByRole("region", { name: "Alexa" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Scenario playback" })).toBeHidden();
  await expect(page.getByText("Simulated devices and contact replies")).toBeVisible();
  await page.keyboard.press("f");
  await expect(page.getByRole("heading", { name: "Scenario playback" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Alexa" })).toHaveCount(0);
});

test("focus screenshots", async ({ page }) => {
  test.skip(!origin || !shots, "Set HIRZ_FOCUS_SHOTS for screenshots");
  await mock(page);
  for (const [name, width, height] of [["focus-1440", 1440, 900], ["focus-390", 390, 844]] as const) {
    await page.setViewportSize({ width, height });
    await page.goto(`${origin}/simulator?focus=1`);
    await expect(page.getByRole("status")).not.toHaveText("Hold Space or the mic to talk.");
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${shots}/${name}-dark.png` });
    if (width === 1440) {
      await page.keyboard.press("c");
      await page.getByLabel("Theme").selectOption("light");
      await page.keyboard.press("c");
      await page.waitForTimeout(1500);
      await page.screenshot({ path: `${shots}/${name}-light.png` });
    }
  }
});
