import { useState, type ReactNode } from "react";
import { Button } from "./ui/button";

export function AsyncButton({ children, run, primary = false, disabled = false }: {
  children: ReactNode;
  run: () => Promise<unknown>;
  primary?: boolean;
  disabled?: boolean;
}) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  return <div>
    <Button
      variant={primary ? "default" : "outline"}
      disabled={busy || disabled}
      onClick={async () => {
        setBusy(true);
        setMessage("");
        try {
          await run();
        } catch (e) {
          setMessage(e instanceof Error ? e.message : "Request failed.");
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "Please wait…" : children}
    </Button>
    {message && <p role="alert">{message}</p>}
  </div>;
}

export function Load({ error, retry }: { error: string; retry: () => void }) {
  return error ? <div role="alert">
    <p>{error}</p>
    <Button onClick={retry}>Retry</Button>
  </div> : <p role="status">Loading…</p>;
}

export function Panel({ title, children, id }: { title: string; children: ReactNode; id?: string }) {
  return <section id={id} tabIndex={id ? -1 : undefined} className="panel">
    <h2>{title}</h2>
    {children}
  </section>;
}

export function Secret({ value }: { value: string }) {
  return <div role="status" className="secret">
    <h2>Save this code now</h2>
    <p>Keep it somewhere private. It is shown once and only permits enrolling a replacement passkey.</p>
    <code>{value}</code>
  </div>;
}
