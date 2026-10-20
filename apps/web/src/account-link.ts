export type AccountLinkState = {
  available: boolean; linked?: boolean; session_binding?: string;
  login?: { origin: string; client_id: string; resource: string; redirect_uri: string } | null;
};

const storage = "hirz-account-link";
const refused = "This login request expired or changed. Start again from Household.";
function encoded(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function startLink(config: AccountLinkState): Promise<string> {
  if (!config.available || !config.login || !config.session_binding || config.linked) throw new Error(refused);
  const state = encoded(crypto.getRandomValues(new Uint8Array(32)));
  const verifier = encoded(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = encoded(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
  // Only the short-lived PKCE proof survives navigation; no access/refresh token is stored.
  sessionStorage.setItem(storage, JSON.stringify({ state, verifier, expires: Date.now() + 300000, binding: config.session_binding, login: config.login }));
  const url = new URL("/oauth2/authorize", config.login.origin);
  url.search = new URLSearchParams({ response_type: "code", client_id: config.login.client_id,
    redirect_uri: config.login.redirect_uri, resource: config.login.resource, scope: "openid hirz/read",
    state, code_challenge_method: "S256", code_challenge: challenge, prompt: "login" }).toString();
  return url.href;
}

export async function finishLink(config: AccountLinkState, returned: URLSearchParams): Promise<string> {
  const saved = sessionStorage.getItem(storage);
  sessionStorage.removeItem(storage);
  if (!saved || !config.available || !config.login || !config.session_binding || config.linked) throw new Error(refused);
  let value: unknown;
  try { value = JSON.parse(saved); } catch { throw new Error(refused); }
  if (!value || typeof value !== "object") throw new Error(refused);
  const pending = value as Record<string, unknown>;
  if (typeof pending.state !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(pending.state) || typeof pending.verifier !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(pending.verifier)
    || typeof pending.expires !== "number" || Date.now() >= pending.expires || pending.expires > Date.now() + 300000
    || pending.binding !== config.session_binding || JSON.stringify(pending.login) !== JSON.stringify(config.login)
    || returned.getAll("state").length !== 1 || returned.get("state") !== pending.state
    || returned.getAll("code").length !== 1 || !returned.get("code") || returned.has("error")) throw new Error(refused);
  // Cognito's public client accepts the S256 verifier; state and session are checked before exchange.
  // https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(new URL("/oauth2/token", config.login.origin), {
      method: "POST", credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer",
      signal: controller.signal, headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ grant_type: "authorization_code", client_id: config.login.client_id,
        redirect_uri: config.login.redirect_uri, code: returned.get("code")!, code_verifier: pending.verifier }),
    });
    if (!response.ok) throw new Error("Login could not be verified. Start again from Household.");
    const result: unknown = await response.json();
    if (!result || typeof result !== "object" || !("access_token" in result) || typeof result.access_token !== "string"
      || !result.access_token || result.access_token.length > 16384) throw new Error("Login returned an invalid response.");
    return result.access_token;
  } finally { clearTimeout(timer); }
}
