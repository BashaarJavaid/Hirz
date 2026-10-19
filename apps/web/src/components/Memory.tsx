import { useState } from "react";
import { api, useResource } from "../api";
import { AsyncButton, Load, Panel } from "./primitives";
import { Button } from "./ui/button";
import { date } from "../types";

type Proposal = {
  id: string;
  candidate: { key: "temperature_target_f"; value: number | string };
  created_at: string;
  audit_seq: number;
};

function Suggestion({ proposal, reviewed }: { proposal: Proposal; reviewed: (message: string) => void }) {
  const [busy, setBusy] = useState(false), [done, setDone] = useState(false);
  async function review(accept: boolean) {
    setBusy(true);
    try {
      const result = await api<{ decision: { decision: string }; record: { status: string } | null }>("/memory/review", {
        proposal_id: proposal.id, accept, request_id: crypto.randomUUID(),
      });
      if (result.decision.decision !== "execute" || result.record?.status !== (accept ? "accepted" : "rejected")) {
        throw new Error("This suggestion could not be updated. Refresh to check your current suggestions and household rules.");
      }
      setDone(true);
      reviewed(accept ? "Your temperature preference was saved." : "The suggestion was dismissed.");
    } finally { setBusy(false); }
  }
  return <article>
    <h3>Prefer {proposal.candidate.value}°F?</h3>
    <p>Suggested {date(proposal.created_at)}. Your household rules and comfort limits still apply.</p>
    <AsyncButton primary disabled={busy || done} run={() => review(true)}>Remember {proposal.candidate.value}°F</AsyncButton>
    <AsyncButton disabled={busy || done} run={() => review(false)}>Don’t remember</AsyncButton>
  </article>;
}

export function Memory() {
  const [after, setAfter] = useState(0), [message, setMessage] = useState("");
  const r = useResource<Proposal[]>(`/memory/proposals?after=${after}&limit=50`);
  return <Panel title="Your preference suggestions">
    <p>Only you can accept suggestions for your preferences. Suggestions do not affect plans until you accept them.</p>
    {message && <p role="status">{message}</p>}
    <Button onClick={r.retry}>Refresh suggestions</Button>
    {!r.data || r.error ? <Load {...r} /> : <>
      {r.data.length === 0 && <p>No suggestions to review on this page.</p>}
      {r.data.map(proposal => <Suggestion key={proposal.id} proposal={proposal} reviewed={text => { setMessage(text); r.retry(); }} />)}
      {r.data.length === 50 && <Button onClick={() => setAfter(r.data!.at(-1)!.audit_seq)}>More suggestions</Button>}
    </>}
    {after > 0 && <Button onClick={() => setAfter(0)}>Back to first suggestions</Button>}
  </Panel>;
}
