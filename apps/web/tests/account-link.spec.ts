import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
import { accessibility } from "./accessibility";

const backend = process.env.HIRZ_BROWSER_BACKEND ?? "http://127.0.0.1:5175";
const origin = backend.replace("127.0.0.1", "localhost"), login = "https://login.example.test";

// Browser exchange/presentation fixtures; real grant, JWT and isolation checks run in PostgreSQL tests.
for (const scenario of [{ width: 390, changed: false }, { width: 1280, changed: false }, { width: 390, changed: true }]) {
  test(`Self-link at ${scenario.width}px, session changed=${scenario.changed}`, async ({ page, context }) => {
    await page.setViewportSize({ width: scenario.width, height: 900 });
    let returned = false, exchanges = 0, finishes = 0, challenge = "";
    await page.route("**/api/auth/session", route => route.fulfill({ json: { authenticated: true, csrf: "synthetic-csrf", member: { display_name: "Synthetic member", role: "adult" } } }));
    await page.route("**/api/household", route => route.fulfill({ json: { graph: { members: [], assets: [] }, credentials: [] } }));
    await page.route("**/api/contacts", route => route.fulfill({ json: { links: [] } }));
    await page.route("**/api/memory/proposals?*", route => route.fulfill({ json: [] }));
    await page.route("**/api/account-link", route => route.fulfill({ json: {
      available: true, linked: false, session_binding: returned && scenario.changed ? "changed-session" : "original-session",
      login: { origin: login, client_id: "human-client", resource: "https://runtime.example.test/mcp", redirect_uri: origin + "/account-link" },
    } }));
    await page.route(`${login}/oauth2/authorize?*`, async route => {
      const params = new URL(route.request().url()).searchParams;
      expect(params.get("resource")).toBe("https://runtime.example.test/mcp");
      expect(params.get("code_challenge_method")).toBe("S256");
      challenge = params.get("code_challenge")!;
      returned = true;
      const callback = new URL("/account-link", origin);
      callback.search = new URLSearchParams({ code: "synthetic-code", state: params.get("state")! }).toString();
      await route.fulfill({ status: 302, headers: { location: callback.href }, body: "" });
    });
    await page.route(`${login}/oauth2/token`, async route => {
      exchanges += 1;
      const body = new URLSearchParams(route.request().postData()!);
      expect(body.get("grant_type")).toBe("authorization_code");
      expect(body.get("redirect_uri")).toBe(origin + "/account-link");
      expect(createHash("sha256").update(body.get("code_verifier")!).digest("base64url")).toBe(challenge);
      await route.fulfill({ headers: { "access-control-allow-origin": origin }, json: { access_token: "synthetic-access", refresh_token: "synthetic-refresh" } });
    });
    await page.route("**/api/auth/begin", async route => {
      expect(route.request().postDataJSON()).toEqual({ operation: "link_account", account_token: "synthetic-access", account_binding: "original-session" });
      expect(route.request().headers()["x-hirz-csrf"]).toBe("synthetic-csrf");
      await route.fulfill({ json: { id: "synthetic-ceremony", kind: "authenticate", publicKey: {
        challenge: Buffer.alloc(32, 1).toString("base64url"), rpId: new URL(origin).hostname, userVerification: "required", timeout: 60000,
      } } });
    });
    await page.route("**/api/auth/finish", async route => {
      finishes += 1;
      const body = route.request().postDataJSON();
      expect(body.account_token).toBe("synthetic-access");
      expect(body.credential.response.signature).toBeTruthy();
      await route.fulfill({ json: { message: "Your login is linked." } });
    });
    const cdp = await context.newCDPSession(page);
    await cdp.send("WebAuthn.enable");
    await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal", hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
    await page.goto(origin + "/household");
    await expect(page.getByRole("button", { name: "Link my login" })).toBeVisible();
    await accessibility(page);
    await page.evaluate(async () => {
      await navigator.credentials.create({ publicKey: {
        challenge: crypto.getRandomValues(new Uint8Array(32)), rp: { name: "Hirz", id: location.hostname },
        user: { id: crypto.getRandomValues(new Uint8Array(32)), name: "synthetic-member", displayName: "Synthetic member" },
        pubKeyCredParams: [{ type: "public-key", alg: -7 }], authenticatorSelection: { residentKey: "required", userVerification: "required" },
      } });
    });
    await page.getByRole("button", { name: "Link my login" }).click();
    await expect(page.getByRole("heading", { name: "Link your login" })).toBeVisible();
    expect(page.url()).toBe(origin + "/account-link");
    await accessibility(page);
    await page.getByRole("button", { name: "Confirm with my passkey" }).click();
    if (scenario.changed) {
      await expect(page.getByRole("alert")).toContainText("Start again from Household");
      expect(exchanges).toBe(0);
      expect(finishes).toBe(0);
    } else {
      await expect(page.getByRole("status")).toContainText("Your login is linked");
      expect(exchanges).toBe(1);
      expect(finishes).toBe(1);
    }
    const storage = await page.evaluate(() => JSON.stringify([Object.entries(sessionStorage), Object.entries(localStorage)]));
    expect(storage).not.toContain("synthetic-access");
    expect(storage).not.toContain("synthetic-refresh");
    expect(storage).not.toContain("hirz-account-link");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
