import { useEffect, useState } from "react";

let csrf = "";
export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST", credentials: "same-origin", signal,
    headers: { "Content-Type": "application/json", "X-Hirz-CSRF": csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = response.status === 409 ? (await response.json()).detail : null;
    throw new Error(typeof detail === "string" ? detail : response.status === 401 ? "Sign in again to continue." : "That request could not be completed. Refresh and try again.");
  }
  const data = await response.json();
  if (typeof data.csrf === "string") csrf = data.csrf;
  return data as T;
}

export function useResource<T>(path: string, poll = false) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let stopped = false, pending = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    setError("");
    async function load() {
      if (stopped || pending || document.hidden) return;
      pending = true;
      try {
        const next = await api<T>(path, undefined, controller.signal);
        if (!stopped) setData(next);
      } catch (e) {
        if (!controller.signal.aborted) { setError(String(e)); stopped = true; }
      } finally {
        pending = false;
        if (!stopped && poll && !document.hidden) timer = setTimeout(load, 2000);
      }
    }
    function visible() { clearTimeout(timer); if (!document.hidden) void load(); }
    document.addEventListener("visibilitychange", visible);
    void load();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); document.removeEventListener("visibilitychange", visible); };
  }, [path, poll, revision]);
  return { data, error, retry: () => setRevision(v => v + 1) };
}

function bytes(text: string): ArrayBuffer {
  return Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), v => v.charCodeAt(0)).buffer;
}
function encoded(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

type Descriptor = { id: string; type: PublicKeyCredentialType; transports?: AuthenticatorTransport[] };
type Options = { id: string; kind: string; publicKey: {
  challenge: string; user?: { id: string; name: string; displayName: string };
  excludeCredentials?: Descriptor[]; allowCredentials?: Descriptor[];
} };
export async function passkey(request: Record<string, unknown>) {
  const options = await api<Options>("/auth/begin", request);
  const key = { ...options.publicKey, challenge: bytes(options.publicKey.challenge) };
  const descriptors = (values?: Descriptor[]) => values?.map(v => ({ ...v, id: bytes(v.id) }));
  const invoke = () => options.kind === "register"
    ? navigator.credentials.create({ publicKey: { ...key, user: { ...options.publicKey.user!, id: bytes(options.publicKey.user!.id) }, excludeCredentials: descriptors(options.publicKey.excludeCredentials) } as PublicKeyCredentialCreationOptions })
    : navigator.credentials.get({ publicKey: { ...key, allowCredentials: descriptors(options.publicKey.allowCredentials) } as PublicKeyCredentialRequestOptions });
  // Older WebKit can lose the user gesture across asynchronous option fetching.
  // https://simplewebauthn.dev/docs/advanced/browser-quirks
  const ios = /(?:iPhone|iPad).*OS (\d+)_/.exec(navigator.userAgent);
  const credential = await (ios && Number(ios[1]) < 16 ? freshGesture(invoke) : invoke()) as PublicKeyCredential | null;
  if (!credential) throw new Error("Passkey request was cancelled.");
  const raw = credential.response;
  const response: Record<string, unknown> = { clientDataJSON: encoded(raw.clientDataJSON) };
  if (raw instanceof AuthenticatorAttestationResponse) response.attestationObject = encoded(raw.attestationObject);
  else if (raw instanceof AuthenticatorAssertionResponse) Object.assign(response, {
    authenticatorData: encoded(raw.authenticatorData), signature: encoded(raw.signature),
    userHandle: raw.userHandle ? encoded(raw.userHandle) : null,
  });
  return api<{ ok: boolean; recovery_code?: string; invitation?: string; version?: string }>("/auth/finish", {
    id: options.id, credential: { id: credential.id, rawId: encoded(credential.rawId), type: credential.type, response, clientExtensionResults: credential.getClientExtensionResults() },
  });
}


function freshGesture(invoke: () => Promise<Credential | null>): Promise<Credential | null> {
  return new Promise((resolve, reject) => {
    const dialog = document.createElement("dialog");
    dialog.setAttribute("aria-label", "Confirm with your passkey");
    const message = document.createElement("p");
    message.textContent = "Your passkey request is ready. Continue to open your device’s verification prompt.";
    const proceed = document.createElement("button"), cancel = document.createElement("button");
    proceed.textContent = "Continue with passkey"; cancel.textContent = "Cancel";
    const close = () => { dialog.close(); dialog.remove(); };
    proceed.addEventListener("click", () => {
      proceed.disabled = true;
      void invoke().then(resolve, reject).finally(close);
    }, { once: true });
    cancel.addEventListener("click", () => { close(); resolve(null); });
    dialog.addEventListener("cancel", () => { close(); resolve(null); });
    dialog.append(message, proceed, cancel); document.body.append(dialog); dialog.showModal(); proceed.focus();
  });
}
