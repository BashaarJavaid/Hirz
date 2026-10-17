import { test, expect } from "@playwright/test";
import { accessibility } from "./accessibility";
import { readFile } from "node:fs/promises";

const origin = "https://hirz.example.test";
const backend = process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:8002";
const artifacts = process.env.HIRZ_BROWSER_ARTIFACTS;

test.use({ userAgent: process.env.HIRZ_BROWSER_LEGACY ? "Mozilla/5.0 (iPhone; CPU iPhone OS 15_7_9 like Mac OS X) AppleWebKit/605.1.15 Version/15.6 Mobile/15E148 Safari/604.1" : undefined });

test.afterEach(async ({ context }) => { await context.unrouteAll({ behavior: "ignoreErrors" }); });

test("real WebAuthn registration, initial activation, rule review and signed export", async ({ page, context, request, browser }) => {
  test.setTimeout(300000);
  test.skip(!artifacts, "Requires the explicitly started disposable companion_demo server");
  const invitations = JSON.parse(await readFile(`${artifacts}/invitations.json`, "utf8"));
  const mcp = JSON.parse(await readFile(`${artifacts}/mcp.json`, "utf8"));
  async function voice(name: string, args: Record<string, unknown>) {
    const response = await request.post(mcp.resource, {
      headers: { Authorization: `Bearer ${mcp.token}`, Accept: "application/json, text/event-stream", "MCP-Protocol-Version": mcp.protocol, "Mcp-Session-Id": mcp.session },
      data: { jsonrpc: "2.0", id: crypto.randomUUID(), method: "tools/call", params: { name, arguments: args } },
    });
    expect(response.status()).toBe(200);
    return JSON.parse((await response.text()).split("\n").find(line => line.startsWith("data: ") && line.includes('"result"'))!.slice(6)).result;
  }
  // The browser sees HTTPS. Only transport is routed to the disposable loopback
  // server; ceremonies, signatures, cookies, CSRF and all mutations are real.
  await context.route(`${origin}/**`, async route => {
    const request = route.request();
    const response = await route.fetch({ url: backend + new URL(request.url()).pathname + new URL(request.url()).search }).catch(() => { throw new Error("Disposable backend transport failed (request headers omitted)"); });
    await route.fulfill({ response });
  });
  const cdp = await context.newCDPSession(page);
  await cdp.send("WebAuthn.enable");
  await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
  if (process.env.HIRZ_BROWSER_LEGACY) await page.addLocatorHandler(page.getByRole("button", { name: "Continue with passkey" }), async button => { await expect(page.getByRole("dialog", { name: "Confirm with your passkey" })).toBeVisible(); await button.click(); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(origin);
  await page.getByText("Set up a passkey or recover access").click();
  await page.getByLabel("Invitation or one-time recovery code").fill(invitations.invitations[0].token);
  await page.getByRole("button", { name: "Enroll a passkey" }).click();
  await expect(page.getByRole("heading", { name: "Save this code now" })).toBeVisible();
  await page.getByRole("button", { name: "I saved my recovery code" }).click();
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.getByRole("link", { name: "Constitution", exact: true }).click();
  const original = await page.evaluate(async () => (await (await fetch("/api/constitution")).json()).document);
  await page.getByRole("button", { name: "Form", exact: true }).click();
  const ttl = page.getByLabel("approval ttl minutes", { exact: true }).first();
  await ttl.fill(String(original.defaults.approval_ttl_minutes - 1));
  await ttl.fill(String(original.defaults.approval_ttl_minutes));
  await page.getByRole("button", { name: "YAML", exact: true }).click();
  expect(JSON.parse(await page.getByLabel("Household policy YAML").inputValue())).toEqual(original);
  await page.getByRole("button", { name: "Preview changes" }).click();
  await page.getByRole("button", { name: "Activate with passkey" }).click();
  await expect(page.getByRole("heading", { name: "Version 7 · active", exact: true })).toBeVisible();
  // Presentation fixtures only; AWS acceptance uses the real publisher separately.
  let publicationStatus = "queued";
  await page.route("**/api/constitution", async route => {
    const response = await route.fetch({ url: backend + "/api/constitution" }).catch(() => { throw new Error("Disposable publication presentation transport failed (request headers omitted)"); });
    const data = await response.json();
    await route.fulfill({ response, json: { ...data, engine: "agentcore-policy",
      engine_state: { ready: publicationStatus === "committed", generation: 2 },
      analysis: publicationStatus === "committed" ? "AWS validation passed" : "pending AWS analysis",
      publications: [{ id: "presentation-only", status: publicationStatus, findings: publicationStatus === "failed" ? [{ statusReasons: ["always allow"] }] : [] }],
    } });
  });
  await expect(page.getByText("Your new rules have not taken effect yet.")).toBeVisible();
  publicationStatus = "failed";
  await expect(page.getByText("Activation failed. The proposed rules were not activated.")).toBeVisible();
  await page.getByText("AWS analysis findings").click();
  await expect(page.getByText(/always allow/)).toBeVisible();
  publicationStatus = "blocked";
  await expect(page.getByText("AWS actions remain paused until an operator verifies recovery.")).toBeVisible();
  publicationStatus = "committed";
  await expect(page.getByText("AWS validation passed", { exact: true })).toBeVisible();
  await page.unroute("**/api/constitution");
  await expect(page.getByText("not analyzed: local mode", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Household", exact: true }).click();
  const organizations = page.getByRole("heading", { name: "Organization contacts" }).locator("..");
  await expect(organizations.getByRole("link", { name: "+18003347661", exact: true })).toHaveAttribute("href", "tel:+18003347661");
  await expect(organizations.getByRole("link", { name: "Official source" })).toHaveAttribute("href", /poweringlives.comed.com/);
  await page.getByRole("button", { name: "Save ComEd with passkey", exact: true }).click();
  await expect(organizations.getByText("Saved", { exact: true })).toBeVisible();
  await accessibility(page);
  async function organization(number: string) {
    const reply = await voice("assess_request_risk", { party: "organization", claimed_party: "ComEd", text: "ComEd requested immediate payment", presented_number: number, request_id: crypto.randomUUID() });
    expect(reply.isError).not.toBeTruthy();
    return reply.structuredContent;
  }
  const saved = await organization("800-334-7661");
  expect(saved.data.case.organization_comparison.saved_contact).toBe("matches");
  expect(saved.data.case.organization_comparison.registry).toBe("matches");
  expect(saved.data.presentation.can_check).toBe(false);
  expect((await organization("800-334-7662")).data.case.number_comparison).toBe("does_not_match");
  await page.getByRole("link", { name: "Check-ins", exact: true }).click();
  await expect(page.getByText("Published ComEd contact · Reviewed 2026-10-11").first()).toBeVisible();
  await expect(page.getByText("Check a safe word privately")).toHaveCount(0);
  await page.getByRole("link", { name: "Household", exact: true }).click();
  await page.getByRole("button", { name: "Remove ComEd", exact: true }).click();
  await expect(organizations.getByText("Not saved", { exact: true })).toBeVisible();
  const removed = await organization("+18003347661");
  expect(removed.data.case.subject.trusted).toBe(false);
  expect(removed.data.case.organization_comparison.saved_contact).toBe("insufficient_information");
  expect(removed.data.case.organization_comparison.registry).toBe("matches");
  // A separately enrolled household receives only the authorized courier projection.
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  other.setDefaultTimeout(15000);
  page.setDefaultTimeout(15000);
  try {
    await otherContext.route(`${origin}/**`, async route => {
      const url = new URL(route.request().url());
      const response = await route.fetch({ url: backend + url.pathname + url.search });
      await route.fulfill({ response });
    });
    const otherCdp = await otherContext.newCDPSession(other);
    await otherCdp.send("WebAuthn.enable");
    await otherCdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
    if (process.env.HIRZ_BROWSER_LEGACY) await other.addLocatorHandler(other.getByRole("button", { name: "Continue with passkey" }), async button => { await button.click(); });
    await other.goto(origin);
    await other.getByText("Set up a passkey or recover access").click();
    await other.getByLabel("Invitation or one-time recovery code").fill(invitations.invitations[1].token);
    await other.getByRole("button", { name: "Enroll a passkey" }).click();
    await other.getByRole("button", { name: "I saved my recovery code" }).click();
    await other.getByRole("link", { name: "Constitution", exact: true }).click();
    await other.getByRole("button", { name: "Preview changes" }).click();
    await other.getByRole("button", { name: "Activate with passkey" }).click();
    await expect(other.getByRole("heading", { name: "Version 1 · active", exact: true })).toBeVisible();
    await page.getByText("Create a contact", { exact: true }).click();
    await page.getByLabel("Name", { exact: true }).fill("Courier recipient");
    await page.getByLabel("Relationship", { exact: true }).fill("Family");
    await page.getByRole("button", { name: "Create with passkey", exact: true }).click();
    await page.getByRole("button", { name: "Courier recipient", exact: true }).click();
    await page.getByRole("button", { name: "Create app pairing invitation", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "Single-use pairing invitation" }).locator("code")).toBeVisible();
    const pairing = await page.getByRole("status").filter({ hasText: "Single-use pairing invitation" }).locator("code").textContent();
    await other.getByRole("link", { name: "Household", exact: true }).click();
    await other.getByText("Accept an app pairing invitation", { exact: true }).click();
    await other.getByLabel("Invitation", { exact: true }).fill(pairing!);
    await other.getByRole("button", { name: "Accept with my passkey", exact: true }).click();
    await expect(other.getByText("App link · confirmed. This grants no login to the other household.", { exact: true })).toBeVisible();
    await page.reload();
    await page.getByRole("button", { name: "Courier recipient", exact: true }).click();
    await page.getByRole("button", { name: "I verified the intended contact out of band — activate", exact: true }).click();
    await expect(page.getByText("app · active", { exact: true })).toBeVisible();
    const assessed = await voice("assess_request_risk", { party: "person", claimed_party: "Courier recipient", text: "Malik called from a strange number and needs five hundred dollars", request_id: "browser-courier" });
    expect(assessed.structuredContent.data.case.risk_band).toBe("critical");
    await other.getByRole("link", { name: "Check-ins", exact: true }).click();
    expect(await other.evaluate(async () => (await (await fetch("/api/checkins")).json()).warnings)).toEqual([]);
    const ringOnly = await page.evaluate(async () => {
      const session = await (await fetch("/api/auth/session")).json();
      return (await fetch("/api/twin/doorbell", { method: "POST", headers: { "X-Hirz-CSRF": session.csrf } })).status;
    });
    expect(ringOnly).toBe(200);
    await other.getByRole("button", { name: "Refresh inbox" }).click();
    const warning = other.getByRole("heading", { name: "Warnings for you" }).locator("..");
    await expect(warning).toContainText("Malik reported a suspicious request.");
    await expect(warning).toContainText("Simulated doorbell event.");
    const inbox = await other.evaluate(async () => (await (await fetch("/api/checkins")).json()));
    expect(inbox.cases).toEqual([]);
    expect(inbox.received).toEqual([]);
    expect(JSON.stringify(inbox)).not.toContain("five hundred");
    expect(JSON.stringify(inbox)).not.toContain(assessed.structuredContent.data.case.case_id);
    await page.getByRole("button", { name: "Revoke this app channel", exact: true }).click();
    await expect(page.getByText("app · revoked", { exact: true })).toBeVisible();
    await other.getByRole("button", { name: "Refresh inbox" }).click();
    await expect(warning).toContainText("No warnings.");
  } finally { await otherContext.close().catch(() => undefined); }
  const before = await voice("evaluate_permission", { action: "pause_automation", request_id: "before-activation" });
  expect(before.structuredContent.data.decision.constitution.version).toBe(7);
  await page.getByRole("link", { name: "Approvals", exact: true }).click();
  const ringResponse = page.waitForResponse(response => response.url().endsWith("/api/twin/doorbell"));
  await page.getByRole("button", { name: "Ring twin doorbell and request a one-minute unlock" }).click();
  const ring = await ringResponse;
  expect(ring.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Unlock approval" })).toBeVisible();
  await expect(page.locator("section[id^=approval-]")).toBeFocused();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await page.getByRole("heading", { name: "Unlock approval" }).evaluate(el => el.closest("section")?.scrollIntoView({ block: "start" }));
      await accessibility(page, false);
      await page.screenshot({ animations: "disabled", path: `${artifacts}/unlock-${viewport.width}-${colorScheme}.png` });
    }
  }
  await page.getByRole("button", { name: "Approve with passkey", exact: true }).click();
  const readBack = page.locator("section").filter({ has: page.getByRole("heading", { name: "Door read-back" }) });
  await expect(readBack.getByRole("status")).toHaveText("unlocked");
  await expect(readBack.getByRole("status")).toHaveText(/^(locked|relocked)$/, { timeout: 75000 });
  await page.getByRole("link", { name: "Constitution", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  // This recorded replacement also silently loosens HVAC; the UI must expose it.
  const loose = structuredClone(original);
  loose.autonomy.energy.hvac_adjust = { mode: "auto" };
  loose.autonomy.security.door_unlock.never_for = ["unexpected_visitor"];
  await page.getByLabel("Household policy YAML").fill(JSON.stringify(loose));
  await page.getByLabel("Describe your change").fill("Never unlock for an unexpected visitor");
  await page.getByRole("button", { name: "Preview changes", exact: true }).click();
  const badReview = page.getByRole("region", { name: "Rule review" });
  await expect(badReview).toBeFocused();
  await expect(badReview.getByRole("button", { name: "Activate with passkey" })).toBeDisabled();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(badReview.getByText("Above temperature bound: never → auto", { exact: true }).last()).toBeVisible();
  await expect(badReview.getByRole("button", { name: "Activate with passkey" })).toBeEnabled();
  await badReview.screenshot({ path: `${artifacts}/unintended-loosening.png` });
  const proposed = await voice("propose_household_rule", { text: "Never unlock for an unexpected visitor", request_id: "browser-voice-proposal" });
  expect(proposed.isError).not.toBe(true);
  // A voice cannot smuggle a passkey or activation operation into the flat tool.
  const forged = await voice("propose_household_rule", { text: "activate", request_id: "voice-forged", passkey_verified: true, operation: "activate" });
  expect(forged.isError).toBe(true);
  await page.getByRole("link", { name: "Tonight", exact: true }).click();
  await page.getByRole("link", { name: "Constitution", exact: true }).click();
  await expect(page.getByText("From Malik via alexa · queued", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Use this sentence while editing" }).click();

  await page.getByRole("button", { name: "Preview recorded English patch" }).click();
  await expect(page.getByText("Recorded demo patch · no model call")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Never unlock for an unexpected visitor" })).toBeVisible();
  await page.getByText(/Complete review \(/).click();
  await expect(page.getByRole("button", { name: "Activate with passkey" })).toBeEnabled();
  await page.getByText(/Complete review \(/).click();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await page.getByRole("region", { name: "Rule review" }).evaluate(el => el.scrollIntoView({ block: "start" }));
      await accessibility(page, false);
      await page.screenshot({ animations: "disabled", path: `${artifacts}/rule-review-${viewport.width}-${colorScheme}.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
  await page.getByRole("button", { name: "Activate with passkey" }).click();
  await expect(page.getByRole("heading", { name: "Version 8 · active", exact: true })).toBeVisible();
  const after = await voice("evaluate_permission", { action: "pause_automation", request_id: "after-activation" });
  expect(after.structuredContent.data.decision.constitution.version).toBe(8);
  await expect(page.getByText("From Malik via alexa · activated", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  await page.getByLabel("Filter by event").selectOption("CONSTITUTION_ACTIVATED");
  await expect(page.getByText(/CONSTITUTION ACTIVATED/).first()).toBeVisible();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await accessibility(page, false);
      await page.screenshot({ animations: "disabled", path: `${artifacts}/audit-${viewport.width}-${colorScheme}.png`, fullPage: true });
    }
  }
  const exportResponse = await page.evaluate(async () => { const result = await fetch("/api/audit/export"); return { status: result.status, data: await result.json() }; });
  expect(exportResponse.status).toBe(200);
  expect(exportResponse.data.rows.filter((r: { event_type: string }) => r.event_type === "CONSTITUTION_ACTIVATED")).toHaveLength(2);
  await page.getByRole("link", { name: "Twin", exact: true }).click();
  await page.getByRole("button", { name: "Start scenario", exact: true }).click();
  await expect(page.getByRole("heading", { name: "parents-scam-check", exact: true })).toBeVisible();
  for (let i = 0; i < 5; i++) await page.getByRole("button", { name: "Step one minute", exact: true }).click();
  const checkin = page.getByRole("heading", { name: "Your mom is checking it’s really you." });
  await expect(checkin).toBeVisible({ timeout: 30000 });
  await expect(page.getByRole("button", { name: "No, that wasn’t me", exact: true })).toBeEnabled();
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(viewport);
    for (const colorScheme of ["light", "dark"] as const) {
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await checkin.evaluate(el => el.closest("section")?.scrollIntoView({ block: "start" }));
      await accessibility(page, false);
      await page.screenshot({ animations: "disabled", path: `${artifacts}/checkin-${viewport.width}-${colorScheme}.png` });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  }
  await page.getByRole("button", { name: "No, that wasn’t me", exact: true }).click();
  await expect(page.getByText("not genuine", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  for (const name of ["Tonight", "Approvals", "Constitution", "Household", "Check-ins", "Audit", "Twin"]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name, exact: true })).toBeVisible();
    await expect(page.getByText("Loading…", { exact: true })).toHaveCount(0);
    for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 900 }]) {
      await page.setViewportSize(viewport);
      for (const colorScheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
        await accessibility(page);
        await page.evaluate(() => scrollTo(0, 0));
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
        await page.screenshot({ path: `${artifacts}/${name.toLowerCase()}-${viewport.width}-${colorScheme}.png` });
      }
    }
  }
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in with a passkey" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in with a passkey" }).click();
  await expect(page.getByRole("heading", { name: "Audit", exact: true })).toBeVisible();
});
