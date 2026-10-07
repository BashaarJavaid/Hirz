import { useEffect, useRef, useState } from "react";
import { NavLink } from "react-router-dom";
import { api, passkey, useResource } from "../api";
import { AsyncButton, Load, Panel } from "../components/primitives";
import { Button } from "../components/ui/button";
import { SchemaForm, type Value } from "../schema-form";
import { requestId, type Constitution, type Review } from "../types";

function RuleReview({ draft, done }: { draft: Review; done: () => void }) {
  const [complete, setComplete] = useState(false);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "start" });
    panel.current?.focus({ preventScroll: true });
  }, [draft.id]);
  return <section ref={panel} tabIndex={-1} aria-label="Rule review" className="panel phone-screen">
    <p className="eyebrow">REVIEW YOUR RULE</p>
    <h2>{draft.sentence || "Review your household rules"}</h2>
    {draft.recorded && <p className="badge">Recorded demo patch · no model call</p>}
    <ul className="situations">
      {draft.review.lines.slice(0, 3).map((line, i) => <li key={i}>{line}</li>)}
    </ul>
    {!draft.review.lines.length && <p>No sampled situation changes.</p>}
    {!draft.review.lines.some(line => line.includes("does not identify")) && <p>Hirz does not identify the visitor.</p>}
    <details
      onToggle={e => {
        if (e.currentTarget.open) void api("/constitution/review", { id: draft.id })
          .then(() => setComplete(true)).catch(() => setComplete(false));
      }}
    >
      <summary>Complete review ({draft.review.lines.length} lines) and YAML changes</summary>
      <ul>{draft.review.lines.map((line, i) => <li key={i}>{line}</li>)}</ul>
      <pre>{draft.review.yaml_diff}</pre>
    </details>
    <details>
      <summary>Compiled Cedar</summary>
      <pre>{draft.review.cedar}</pre>
    </details>
    <p className="muted">dogwood-local · {draft.review.analysis}</p>
    <AsyncButton
      primary
      disabled={draft.review.lines.length > 3 && !complete}
      run={async () => {
        await passkey({ operation: "activate", draft_id: draft.id, candidate_hash: draft.candidate_hash });
        done();
      }}
    >
      Activate with passkey
    </AsyncButton>
  </section>;
}

export function ConstitutionPage() {
  const r = useResource<Constitution>("/constitution", true);
  const [yaml, setYaml] = useState<string>(),
    [form, setForm] = useState<Value>(),
    [mode, setMode] = useState("yaml"),
    [review, setReview] = useState<Review>(),
    [sentence, setSentence] = useState(""),
    [proposal, setProposal] = useState<string>();
  if (!r.data || r.error) return <Load {...r} />;
  const data = r.data;
  return <>
    <p className="eyebrow">HOUSE RULES</p>
    <h1>Constitution</h1>
    <p>Version {data.version} · {data.status} · dogwood-local</p>
    <p className="muted">not analyzed: local mode</p>
    {data.recorded_demo && <p><NavLink to="/simulator">Open local simulator</NavLink></p>}
    {review && <RuleReview
      key={review.id}
      draft={review}
      done={() => {
        setReview(undefined);
        setYaml(undefined);
        setForm(undefined);
        setProposal(undefined);
        r.retry();
      }}
    />}
    <Panel title="Edit the rules">
      <div className="flex gap-2">
        <Button aria-pressed={mode === "yaml"} onClick={() => setMode("yaml")}>YAML</Button>
        <AsyncButton
          run={async () => {
            setForm(await api<Value>("/constitution/parse", { yaml: yaml ?? data.yaml }));
            setMode("form");
          }}
        >
          Form
        </AsyncButton>
      </div>
      {mode === "yaml" ? <label>
        Household policy YAML
        <textarea rows={18} spellCheck={false} value={yaml ?? data.yaml} onChange={e => setYaml(e.target.value)} />
      </label> : <SchemaForm
        schema={data.schema}
        value={form ?? data.document}
        onChange={value => {
          setForm(value);
          setYaml(JSON.stringify(value, null, 2));
        }}
      />}
      <label>
        Describe your change
        <input value={sentence} onChange={e => setSentence(e.target.value)} />
      </label>
      <AsyncButton
        run={async () => setReview(await api<Review>("/constitution/draft", {
          yaml: yaml ?? data.yaml,
          sentence,
          proposal_id: proposal
        }))}
      >
        Preview changes
      </AsyncButton>
      {<AsyncButton
        disabled={!sentence}
        run={async () => {
          await api("/tools/propose_household_rule", { text: sentence, request_id: requestId() });
          r.retry();
        }}
      >
        Propose this rule
      </AsyncButton>}
      {data.recorded_demo && <>
        <p className="muted">Recorded demo supports: Never unlock for an unexpected visitor</p>
        <AsyncButton
          disabled={!sentence}
          run={async () => setReview(await api<Review>("/constitution/recorded-draft", {
            sentence,
            proposal_id: proposal
          }))}
        >
          Preview recorded English patch
        </AsyncButton>
      </>}
    </Panel>
    <Panel title="Proposed rules">
      <p>Voice proposals are suggestions. Only an owner’s passkey activation changes the rules.</p>
      {data.proposals.length ? data.proposals.map(p => <article key={p.id}>
        <p>{p.text}</p>
        <p className="muted">From {p.author ?? "a former linked member"} via {p.surface} · {p.status}</p>
        {p.failure && <p>{p.failure}</p>}
        {!["activated", "dismissed"].includes(p.status) && <>
          <Button
            onClick={() => {
              setSentence(p.text);
              setProposal(p.id);
            }}
          >
            Use this sentence while editing
          </Button>
          {p.draft_id && <Button onClick={() => setReview(data.drafts.find(d => d.id === p.draft_id))}>
            Review drafted changes
          </Button>}
          <AsyncButton
            run={async () => {
              await api("/constitution/dismiss", { id: p.id });
              r.retry();
            }}
          >
            Dismiss proposal
          </AsyncButton>
        </>}
      </article>) : <p>No proposals yet.</p>}
      <p className="muted">
        {data.drafting === "off"
          ? "English drafting is disabled. Voice proposals stay queued for manual editing."
          : "English proposals are queued for drafting. Review every change before activation."}
      </p>
    </Panel>
    {data.drafts.filter(d => d.status === "ready").length > 0 && <Panel title="Saved reviews">
      {data.drafts.filter(d => d.status === "ready").map(d => <Button key={d.id} onClick={() => setReview(d)}>
        {d.sentence || "Review saved changes"}
      </Button>)}
    </Panel>}
    <Panel title="Policy history">
      {data.history.map(h => <article key={h.version}>
        <h3>Version {h.version} · {h.status}</h3>
        <AsyncButton
          disabled={h.status === "active"}
          run={async () => setReview(await api<Review>("/constitution/draft", {
            yaml: h.yaml,
            sentence: `Restore version ${h.version}`
          }))}
        >
          Review rollback
        </AsyncButton>
      </article>)}
    </Panel>
  </>;
}
