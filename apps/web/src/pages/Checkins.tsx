import { useEffect, useState } from "react";
import { api, passkey, useResource } from "../api";
import { AsyncButton, Load, Panel } from "../components/primitives";

const answers = [["not_genuine", "No, that wasn’t me"], ["genuine", "Yes, that was me"], ["will_call", "I’ll call them"]] as const;
type Received = { id: string; requester: string; text: string; request_hash: string; source: string };
type Case = { case_id: string; claim: { text: string }; verification?: { status: string; method: string; source: string } };
type Result = { speakable: { headline: string }; data: { case: Case } };
type Inbox = { received: Received[]; cases: Result[] };

function SafeWord({ id }: { id: string }) {
  const [word, setWord] = useState(""), [message, setMessage] = useState("");
  return <details><summary>Check a safe word privately</summary>
    <label>Safe word<input type="password" autoComplete="off" minLength={8} maxLength={128} value={word} onChange={e => setWord(e.target.value)} /></label>
    <AsyncButton run={async () => {
      const result = await api<{ matches?: boolean; limited?: boolean; message: string }>("/checkins/safe-word", { case_id: id, value: word });
      setWord(""); setMessage((result.matches === true ? "The word matches. " : result.matches === false ? "The word does not match. " : "") + result.message);
    }}>Check word</AsyncButton><p role="status">{message}</p>
  </details>;
}

export function Checkins() {
  const [poll, setPoll] = useState(true);
  const r = useResource<Inbox>("/checkins", poll);
  useEffect(() => { if (r.data) setPoll(r.data.received.length > 0 || r.data.cases.some(v => v.data.case.verification?.status === "pending")); }, [r.data]);
  if (!r.data || r.error) return <Load {...r} />;
  return <><h1>Check-ins</h1>
    <p>A yes confirms only the quoted request. It is never advice to pay. “I’ll call” records intent.</p>
    <AsyncButton run={async () => r.retry()}>Refresh inbox</AsyncButton>
    <Panel title="Requests for you">
      {r.data.received.length === 0 && <p>No pending requests.</p>}
      {r.data.received.map(item => <article key={item.id}>
        <p>{item.requester} is checking with you · Real app check</p><h2>Did you make this request?</h2>
        <blockquote>{item.text}</blockquote>
        {answers.map(([answer, label]) => <AsyncButton key={answer} run={async () => {
          await passkey({ operation: "contact", contact: { operation: "reply", reference: item.id, request_hash: item.request_hash, answer } }); r.retry();
        }}>{label}</AsyncButton>)}
      </article>)}
    </Panel>
    <Panel title="Your private checks">
      {r.data.cases.map(result => { const item = result.data.case; return <article key={item.case_id}>
        <blockquote>{item.claim.text}</blockquote><p role="status">{result.speakable.headline}</p>
        {item.verification && <p>{item.verification.source === "real" ? "Real" : "Simulated"} · {item.verification.method === "verified_email" ? "Email" : "App"}</p>}
        <SafeWord id={item.case_id} />
        {item.verification && item.verification.status !== "pending" && <details><summary>Retry this same request</summary>
          <p>Confirm another check through the selected method.</p>
          {(["app", "email"] as const).map(method => <AsyncButton key={method} run={async () => {
            await api("/checkins/retry", { case_id: item.case_id, method, confirmed: true, request_id: crypto.randomUUID() }); r.retry(); setPoll(true);
          }}>Confirm retry by {method}</AsyncButton>)}
        </details>}
      </article>; })}
    </Panel>
  </>;
}

type LinkView = { kind: "enrollment" | "checkin"; requester?: string; text?: string; request_hash?: string };
export function ContactLink() {
  const [token] = useState(() => window.location.hash.slice(1));
  const [view, setView] = useState<LinkView>(), [done, setDone] = useState(false);
  useEffect(() => { window.history.replaceState(null, "", "/contact-links"); }, []);
  return <main className="login"><p className="wordmark">Hirz</p><h1>Private contact request</h1>
    {done ? <p role="status">Your response was recorded.</p> : !view ? <>
      <p>Opening this link does not confirm anything.</p>
      <AsyncButton disabled={!token} run={async () => {
        await api("/auth/session"); setView(await api<LinkView>("/contact-links/view", { token }));
      }}>Review private request</AsyncButton>
    </> : view.kind === "enrollment" ? <>
      <p>Confirm this mailbox. The household owner must then confirm the intended contact out of band.</p>
      <AsyncButton run={async () => { await api("/contact-links/confirm", { token }); setDone(true); }}>Confirm my mailbox</AsyncButton>
    </> : <>
      <p>{view.requester} is checking with you · Real email check</p><h2>Did you make this request?</h2><blockquote>{view.text}</blockquote>
      <p>A yes confirms only this request. “I’ll call” records intent, not an arranged call.</p>
      {answers.map(([answer, label]) => <AsyncButton key={answer} run={async () => {
        await api("/contact-links/confirm", { token, request_hash: view.request_hash, answer }); setDone(true);
      }}>{label}</AsyncButton>)}
    </>}
  </main>;
}
