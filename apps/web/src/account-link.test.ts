import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { finishLink, startLink, type AccountLinkState } from "./account-link";
import { createHash } from "node:crypto";

const config: AccountLinkState = { available: true, linked: false, session_binding: "session",
  login: { origin: "https://login.example.test", client_id: "human", resource: "https://runtime.example.test/mcp", redirect_uri: "https://hirz.example.test/account-link" } };
const stored = new Map<string, string>();
beforeEach(() => {
  stored.clear();
  vi.stubGlobal("sessionStorage", { getItem: (key: string) => stored.get(key), setItem: (key: string, value: string) => stored.set(key, value), removeItem: (key: string) => stored.delete(key) });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ access_token: "synthetic-access", refresh_token: "synthetic-refresh" }))));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

test("PKCE binds the resource, session and one-use browser return without storing tokens", async () => {
  const url = new URL(await startLink(config));
  expect(url.origin + url.pathname).toBe("https://login.example.test/oauth2/authorize");
  expect(url.searchParams.get("resource")).toBe(config.login!.resource);
  expect(url.searchParams.get("code_challenge_method")).toBe("S256");
  const returned = new URLSearchParams({ code: "synthetic-code", state: url.searchParams.get("state")! });
  expect(await finishLink(config, returned)).toBe("synthetic-access");
  const [endpoint, request] = vi.mocked(fetch).mock.calls[0];
  expect(String(endpoint)).toBe("https://login.example.test/oauth2/token");
  expect(request).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer" });
  const body = request!.body as URLSearchParams;
  expect(createHash("sha256").update(body.get("code_verifier")!).digest("base64url")).toBe(url.searchParams.get("code_challenge"));
  expect(stored.size).toBe(0);
  await expect(finishLink(config, returned)).rejects.toThrow("Start again");
  expect(fetch).toHaveBeenCalledTimes(1);
});

test.each(["session", "state", "expired", "issuer", "duplicate", "cancelled", "malformed"])("refuses %s before any token exchange", async failure => {
  const url = new URL(await startLink(config));
  const returned = new URLSearchParams({ code: "synthetic-code", state: url.searchParams.get("state")! });
  let current = config;
  if (failure === "session") current = { ...config, session_binding: "changed" };
  if (failure === "state") returned.set("state", "wrong");
  if (failure === "expired") vi.spyOn(Date, "now").mockReturnValue(Date.now() + 301000);
  if (failure === "issuer") current = { ...config, login: { ...config.login!, origin: "https://other.example.test" } };
  if (failure === "duplicate") returned.append("code", "substituted");
  if (failure === "cancelled") returned.set("error", "access_denied");
  if (failure === "malformed") stored.set("hirz-account-link", "null");
  await expect(finishLink(current, returned)).rejects.toThrow("Start again");
  expect(fetch).not.toHaveBeenCalled();
  expect(stored.size).toBe(0);
});
