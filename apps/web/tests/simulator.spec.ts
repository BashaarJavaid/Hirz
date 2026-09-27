import { accessibility } from "./accessibility";
import { test, expect } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
const origin = "https://hirz.example.test";
const backend = process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:8002";
const scenario = process.env.HIRZ_SIMULATOR_SCENARIO;
const artifacts = process.env.HIRZ_SIMULATOR_ARTIFACTS;
test.afterEach(async ({ page, context }) => { if (artifacts) await page.evaluate(async () => (await fetch("/api/simulator/transcript")).json()).then(events => writeFile(`${artifacts}/last-transcript.json`, JSON.stringify(events, null, 2), { mode: 0o600 })).catch(() => {}); if (artifacts) await page.screenshot({ path: `${artifacts}/last-browser.png`, fullPage: true }).catch(() => {}); await context.unrouteAll({ behavior: "ignoreErrors" }); });
test("simulator linking, real enrollment, cards, Dot, switching and both themes", async ({ page, context }) => {
  test.setTimeout(120000);
  page.setDefaultTimeout(15000);
  page.on("console", message => { if (message.type() === "error") console.log(message.text().split("?")[0]); });
  page.on("requestfailed", req => console.log("Failed", new URL(req.url()).pathname, req.failure()?.errorText));
  test.skip(!artifacts, "Start the disposable simulator launcher explicitly");
  const invitations = JSON.parse(await readFile(`${artifacts}/invitations.json`, "utf8"));
  await context.route(/^http:\/\/127\.0\.0\.1:\d+\/consent$/, async route => {
    const response = await route.fetch({ maxRedirects: 0 });
    expect(response.status()).toBe(302);
    // Stop the unrouteable redirect; navigate to this genuine Location below.
    await route.fulfill({ response, status: 200, contentType: "text/html", body: "Consent recorded" });
  });
  await context.route(`${origin}/**`, async route => {
    const req = route.request(), url = new URL(req.url());
    if (url.pathname.endsWith("/events")) {
      // Forward the genuine backlog through its heartbeat per reconnect;
      // route.fetch buffers bodies and cannot forward an unbounded stream.
      const controller = new AbortController();
      const result = await fetch(backend + url.pathname, { headers: req.headers(), signal: controller.signal });
      const reader = result.body!.getReader(), decoder = new TextDecoder();
      let body = "";
      while (!body.includes(": heartbeat\n\n")) {
        const chunk = await reader.read();
        if (chunk.done) break;
        body += decoder.decode(chunk.value, { stream: true });
      }
      controller.abort();
      await route.fulfill({ status: result.status, contentType: "text/event-stream", body });
      return;
    }
    const response = await route.fetch({ url: backend + url.pathname + url.search, maxRedirects: 0 });
    if (url.pathname === "/api/simulator/callback") {
      expect(response.headers().location).toBe("/simulator");
      await route.fulfill({ status: 200, contentType: "text/html", body: "Linked through the real callback" });
    } else await route.fulfill({ response });
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  await page.goto(origin + "/simulator", { waitUntil: "domcontentloaded" });
  console.log("Simulator page loaded");
  await expect(page.getByRole("heading", { name: "Household simulator" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Link Echo with consent" })).toBeVisible();
  await page.goto(origin + "/constitution", { waitUntil: "domcontentloaded" });
  console.log("Enrollment page loaded");
  await page.getByText("Set up a passkey or recover access").click();
  await page.getByLabel("Invitation or one-time recovery code").fill(invitations.invitations[scenario === "parents-scam-check" ? 1 : 0].token);
  await page.getByRole("button", { name: "Enroll a passkey" }).click();
  console.log("Enrollment submitted");
  await page.getByRole("button", { name: "I saved my recovery code" }).click();
  await page.getByRole("button", { name: "Preview changes" }).click();
  await page.getByRole("button", { name: "Activate with passkey" }).click();
  await expect(page.getByRole("heading", { name: `Version ${scenario === "parents-scam-check" ? 1 : 7} · active`, exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Open local simulator", exact: true }).click();
  await expect(page.getByRole("button", { name: "Next event", exact: true })).toBeVisible();
  console.log("Simulator page loaded");
  if (scenario === "parents-scam-check") await page.getByRole("combobox", { name: "Echo account", exact: true }).selectOption("mom");
  await page.getByRole("button", { name: "Link Echo with consent" }).click();
  await expect(page.getByRole("heading", { name: "Hirz simulated login" })).toBeVisible();
  await page.locator('select[name="member"]').selectOption(scenario === "parents-scam-check" ? "3" : "0");
  const consent = page.waitForResponse(r => new URL(r.url()).pathname === "/consent" && r.request().method() === "POST");
  await page.getByRole("button", { name: "Approve", exact: true }).click({ noWaitAfter: true });
  // A redirect from the real loopback issuer is not re-routed by Playwright.
  // Navigate to its genuine callback explicitly under the test HTTPS transport.
  const callback = (await consent).headers().location;
  await expect(page.getByText("Consent recorded", { exact: true })).toBeVisible();
  await page.goto(callback, { waitUntil: "domcontentloaded" });
  await page.goto(origin + "/simulator", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("button", { name: "Relink Echo" })).toBeVisible();
  async function fullscreen() {
    const card = page.frameLocator('iframe[title="Hirz MCP App card"]');
    await card.getByRole("button", { name: "Open details", exact: true }).click();
    await expect(page.locator(".sim-frame")).toHaveClass("sim-frame expanded");
    const viewport = page.viewportSize()!;
    await page.setViewportSize({ width: 1000, height: 600 });
    await expect.poll(async () => {
      const frame = await page.locator('iframe[title="Hirz MCP App card"]').boundingBox(), canvas = await card.getByRole("main").boundingBox();
      return frame !== null && canvas !== null && canvas.y + canvas.height <= frame.y + frame.height + 1 && canvas.x + canvas.width <= frame.x + frame.width + 1;
    }).toBe(true);
    await page.screenshot({ path: `${artifacts}/scenario-fullscreen.png`, fullPage: true });
    await card.getByRole("button", { name: "Close details", exact: true }).click();
    await expect(page.locator(".sim-frame")).toHaveClass("sim-frame");
    await page.setViewportSize(viewport);
  }
  if (scenario) {
    test.setTimeout(1200000);
    await page.getByRole("combobox", { name: "Host", exact: true }).selectOption(process.env.HIRZ_SIMULATOR_MODEL ?? "scripted");
    await page.getByRole("combobox", { name: "Display", exact: true }).selectOption(process.env.HIRZ_SIMULATOR_DISPLAY ?? "show");
    async function control(operation: string, extra = {}) {
      return page.evaluate(async ({ scenario, operation, extra }) => {
        const session = await (await fetch("/api/auth/session")).json();
        const r = await fetch("/api/simulator/scenarios", { method: "POST", headers: { "Content-Type": "application/json", "X-Hirz-CSRF": session.csrf }, body: JSON.stringify({ scenario, operation, ...extra }) });
        if (!r.ok) throw Error(`Scenario ${operation}: ${r.status}`); return r.json();
      }, { scenario, operation, extra });
    }
    async function utterance(text: string) {
      await page.evaluate(async text => {
        const s = await (await fetch("/api/simulator/session")).json();
        const r = await fetch("/api/simulator/command", { method: "POST", headers: { "Content-Type": "application/json", "X-Hirz-Simulator-CSRF": s.csrf }, body: JSON.stringify({ operation: "turn", text }) });
        if (!r.ok) throw Error(`Host turn: ${r.status}`);
      }, text);
      await expect.poll(async () => page.evaluate(async text => {
        const s = await (await fetch("/api/simulator/session")).json();
        if (s.prompt) {
          const playback = await (await fetch("/api/simulator/scenarios")).json();
          const start = new Date(playback.scenarios[playback.selected].at).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour12: false, hour: "2-digit", minute: "2-digit" });
          const content = Object.fromEntries(Object.entries(s.prompt.schema.properties as Record<string, { type: string; default?: unknown }>).filter(([k, v]) => s.prompt.schema.required.includes(k) || v.default !== undefined).map(([k, v]) => [k, k === "confirmed" ? true : k === "minutes" ? 10 : k === "window_start" ? start : k === "at" && text.includes("23:31") ? "23:31" : k === "at" && text.includes("kitchen at eleven") ? "23:00" : v.default]));
          if (s.prompt.schema.properties.reply && /let (them|her) in/i.test(text)) content.reply = "Yes, unlock the front door for 10 minutes.";
          if (s.prompt.schema.properties.reply && text.startsWith("Malik just called")) content.reply = "Yes, start the simulated check with Malik.";
          if (s.prompt.schema.properties.reply && text === "Do it.") content.reply = "Yes, approve the exact current plan I just reviewed.";
          if (s.prompt.schema.properties.reply && text.includes("Keep the guest room at 72")) content.reply = "Keep the guest room at 72 Fahrenheit starting now until 7 AM tomorrow morning. No temperature range.";
          if (s.prompt.schema.properties.reply && text.includes("kitchen at eleven")) content.reply = "Do not run the dishwasher before 11 PM tonight.";
          if (s.prompt.schema.properties.reply && text === "Good morning.") content.reply = "Please read the current household context and household plan for my morning summary.";
          const r = await fetch("/api/simulator/command", { method: "POST", headers: { "Content-Type": "application/json", "X-Hirz-Simulator-CSRF": s.csrf }, body: JSON.stringify({ operation: "answer", prompt_id: s.prompt.id, action: "accept", content }) });
          if (!r.ok) throw Error(`Prompt reply: ${r.status}`);
        }
        return s.busy;
      }, text), { timeout: 60000, intervals: [250, 500] }).toBe(false);
      const events = await page.evaluate(async () => (await fetch("/api/simulator/transcript")).json());
      const last = events.findLastIndex((e: { kind: string }) => e.kind === "user");
      const turn = events.slice(last);
      expect(turn.some((e: { kind: string }) => e.kind === "error")).toBe(false);
      const results = turn.filter((e: { kind: string }) => e.kind === "tool");
      expect(results.length).toBeGreaterThan(0);
      expect(results.every((e: { result: { isError?: boolean } }) => !e.result.isError)).toBe(true);
      if (process.env.HIRZ_SIMULATOR_DISPLAY === "dot") await expect(page.locator("iframe")).toHaveCount(0);
      return results;
    }
    async function echo(account: string) {
      await page.getByRole("combobox", { name: "Echo account", exact: true }).selectOption(account);
      const linked = await page.evaluate(async () => (await (await fetch("/api/simulator/session")).json()).linked);
      if (linked) return;
      await page.getByRole("button", { name: "Link Echo with consent" }).click();
      await page.locator('select[name="member"]').selectOption(account === "dad" ? "2" : "0");
      const consent = page.waitForResponse(r => new URL(r.url()).pathname === "/consent" && r.request().method() === "POST");
      await page.getByRole("button", { name: "Approve", exact: true }).click({ noWaitAfter: true });
      const callback = (await consent).headers().location;
      await expect(page.getByText("Consent recorded", { exact: true })).toBeVisible();
      await page.goto(callback, { waitUntil: "domcontentloaded" });
      await page.goto(origin + "/simulator", { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("button", { name: "Relink Echo" })).toBeVisible();
      await page.getByRole("combobox", { name: "Display", exact: true }).selectOption(process.env.HIRZ_SIMULATOR_DISPLAY ?? "show");
    }
    await control("select");
    const total = scenario === "parents-scam-check" ? 5 : 21;
    for (let i = 0, turns = 0; i < total; turns++) {
      expect(turns).toBeLessThan(150);
      const state = await control("next");
      const beat = state.scenarios[scenario].beat;
      console.log("Scenario event", state.scenarios[scenario].next, beat?.event ?? "world");
      i = state.scenarios[scenario].next;
      if (beat?.event === "review") {
        await echo(beat.member);
        await utterance(beat.text);
        await utterance(beat.response);
        await page.waitForTimeout(1500);
      }
      if (beat?.event === "voice") {
        if (scenario === "demo-evening") await echo(beat.member);
        if (["Do it.", "Yes."].includes(beat.text)) {
          await expect.poll(async () => {
            const result = await utterance("What's going on tonight?");
            return result.at(-1)?.result.structuredContent.data.plan?.version ?? 0;
          }, { timeout: 60000, intervals: [1000] }).toBeGreaterThan(0);
        }
        const spoken = !process.env.HIRZ_SIMULATOR_MODEL && beat.text.startsWith("From now on,") ? beat.text.toLowerCase().replace(/\.$/, "") : beat.text;
        const results = await utterance(spoken);
        console.log("Tools", results.map((e: { tool: string; status: string }) => `${e.tool}:${e.status}`).join(","));
        if (["What's going on tonight?", "Optimize energy tonight."].includes(beat.text) && !results.at(-1)?.result.structuredContent.data.plan) {
          await expect.poll(async () => {
            const ready = await utterance(beat.text);
            return ready.at(-1)?.result.structuredContent.data.plan?.version ?? 0;
          }, { timeout: 60000, intervals: [1000] }).toBeGreaterThan(0);
        }
      }
      if (beat?.event === "constitution.activate") {
        await page.goto(origin + "/constitution");
        await page.getByRole("button", { name: "Use this sentence while editing" }).click();
        await page.getByRole("button", { name: "Preview recorded English patch" }).click();
        await page.getByText(/Complete review \(/).click();
        await page.getByRole("button", { name: "Activate with passkey" }).click();
        await expect(page.getByRole("heading", { name: "Version 8 · active", exact: true })).toBeVisible();
        await page.goto(origin + "/simulator");
        await page.getByRole("combobox", { name: "Display", exact: true }).selectOption(process.env.HIRZ_SIMULATOR_DISPLAY ?? "show");
      }
      if (beat?.event === "app.approve") {
        await page.goto(origin + "/approvals");
        await page.getByRole("button", { name: "Approve with passkey", exact: true }).click();
        const readBack = page.locator("section").filter({ has: page.getByRole("heading", { name: "Door read-back" }) });
        await expect(readBack.getByRole("status")).toHaveText("unlocked", { timeout: 30000 });
        await page.goto(origin + "/simulator");
        await page.getByRole("combobox", { name: "Display", exact: true }).selectOption(process.env.HIRZ_SIMULATOR_DISPLAY ?? "show");
      }
      if (beat?.event === "contact.checkin_reply") {
        const before = await page.evaluate(async () => (await (await fetch("/api/simulator/transcript")).json()).filter((e: { kind: string }) => e.kind === "speech").length);
        await control("reply", { reply: "not_genuine" });
        expect(await page.evaluate(async () => (await (await fetch("/api/simulator/transcript")).json()).filter((e: { kind: string }) => e.kind === "speech").length)).toBe(before);
      }
    }
    const transcript = await page.evaluate(async () => (await fetch("/api/simulator/transcript")).json());
    await writeFile(`${artifacts}/scenario-transcript.json`, JSON.stringify(transcript, null, 2), { mode: 0o600 });
    if (scenario === "parents-scam-check") expect(transcript.some((e: { result?: { structuredContent?: { data?: { case?: { verification?: { status?: string } } } } } }) => e.result?.structuredContent?.data?.case?.verification?.status === "not_genuine")).toBe(true);
    if (process.env.HIRZ_SIMULATOR_DISPLAY !== "dot") {
      await page.locator('iframe[title="Hirz MCP App card"]').scrollIntoViewIfNeeded();
      await expect(page.frameLocator('iframe[title="Hirz MCP App card"]').getByText("simulated", { exact: false }).first()).toBeVisible();
    }
    await page.screenshot({ path: `${artifacts}/scenario-${scenario}-${process.env.HIRZ_SIMULATOR_DISPLAY ?? "show"}.png`, fullPage: true });
    if (scenario === "demo-evening" && process.env.HIRZ_SIMULATOR_DISPLAY !== "dot") await fullscreen();
    return;
  }
  await page.getByText("Recorded utterances", { exact: true }).click();
  await page.getByRole("button", { name: "What can you do?", exact: true }).click();
  await expect(page.getByLabel("Your request", { exact: true })).toBeFocused();
  await expect(page.getByLabel("Your request", { exact: true })).toHaveValue("What can you do?");
  await page.getByLabel("Your request", { exact: true }).fill("Show household context");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.locator('iframe[title="Hirz MCP App card"]')).toHaveCount(1);
  await expect(page.frameLocator('iframe[title="Hirz MCP App card"]').getByText("simulated", { exact: false }).first()).toBeVisible();
  await expect(page.frameLocator('iframe[title="Hirz MCP App card"]').getByText("Waiting for household information")).toHaveCount(0);
  await page.locator('iframe[title="Hirz MCP App card"]').scrollIntoViewIfNeeded();
  await accessibility(page, false);
  await page.screenshot({ path: `${artifacts}/simulator-dark.png`, fullPage: true });
  await page.getByRole("combobox", { name: "Theme", exact: true }).selectOption("light");
  await expect(page.frameLocator('iframe[title="Hirz MCP App card"]').locator("html")).toHaveAttribute("data-theme", "light");
  await accessibility(page, false);
  await page.screenshot({ path: `${artifacts}/simulator-light.png`, fullPage: true });
  await page.evaluate(async () => {
    const session = await (await fetch("/api/simulator/session")).json();
    const result = await fetch("/api/simulator/command", { method: "POST", headers: { "Content-Type": "application/json", "X-Hirz-Simulator-CSRF": session.csrf }, body: JSON.stringify({ operation: "card", tool: "get_action_audit", arguments: { window: "today" } }) });
    if (!result.ok) throw Error(`Audit card: ${result.status}`);
  });
  await fullscreen();
  await page.getByLabel("Your request", { exact: true }).fill("Let them in.");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const question = page.getByRole("region", { name: "Pending question" });
  await expect(question).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(question.getByRole("checkbox")).toBeFocused();
  await page.keyboard.press("Space");
  await question.getByRole("button", { name: "Send response", exact: true }).click();
  await expect(question.getByRole("spinbutton")).toBeVisible();
  await expect(question).toBeFocused();
  await question.getByRole("button", { name: "decline", exact: true }).click();
  await expect(question).toHaveCount(0);
  await page.getByRole("combobox", { name: "Display", exact: true }).selectOption("dot");
  await expect(page.locator("iframe")).toHaveCount(0);
  await page.getByRole("combobox", { name: "Echo account", exact: true }).selectOption("dad");
  await expect(page.getByRole("button", { name: "Link Echo with consent" })).toBeVisible();
  await expect(page.getByLabel("Conversation and tool transcript")).not.toContainText("get_household_context");
  const next = page.getByRole("button", { name: "Next event", exact: true });
  await next.click();
  await expect(page.getByText(/event 1\/21/)).toBeVisible();
  await next.click();
  await expect(page.getByText(/event 2\/21/)).toBeVisible();
  await next.click();
  await expect(page.getByRole("alert")).toHaveText("Finish this utterance through the named linked Echo first");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${artifacts}/simulator-dot-phone.png`, fullPage: true });
});
