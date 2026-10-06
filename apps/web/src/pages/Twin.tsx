import { useState } from "react";
import { api, useResource } from "../api";
import { AsyncButton, Load, Panel } from "../components/primitives";
import { date, type TwinRun } from "../types";

export function Twin() {
  const r = useResource<{ scenarios: { id: string; start: string; end: string }[]; runs: TwinRun[] }>("/twin", true);
  const [scenario, setScenario] = useState("parents-scam-check"),
    [event, setEvent] = useState('{"at":"17:01","event":"doorbell.press","entity":"doorbell.front_door"}');
  if (!r.data || r.error) return <Load {...r} />;
  const run = r.data.runs[0];
  const control = async (operation: string, extra: object = {}) => {
    await api("/twin/control", { operation, ...(operation === "start" ? { scenario } : { id: run?.id }), ...extra });
    r.retry();
  };
  return <>
    <p className="eyebrow">SIMULATED HOUSEHOLD</p>
    <h1>Twin</h1>
    <p>
      Isolated repository scenarios. Scripted approvals and replies are simulations and never authenticate an action.
    </p>
    <Panel title="Start an isolated run">
      <label>
        Repository scenario
        <select value={scenario} onChange={e => setScenario(e.target.value)}>
          {r.data.scenarios.map(s => <option key={s.id}>{s.id}</option>)}
        </select>
      </label>
      <AsyncButton run={() => control("start")}>Start scenario</AsyncButton>
    </Panel>
    {run && <>
      <Panel title={run.scenario}>
        <p className="badge">simulated</p>
        <p>{date(run.at)} · {run.controls.paused ? "Paused" : `${run.controls.speed}× clock`}</p>
        <p role="status">{run.refreshing ? "Refreshing scenario snapshot…" : run.snapshot?.status}</p>
        <div className="flex gap-2">
          <AsyncButton run={() => control(run.controls.paused ? "resume" : "pause")}>
            {run.controls.paused ? "Resume at 60×" : "Pause clock"}
          </AsyncButton>
          <AsyncButton run={() => control("step", { minutes: 1 })}>Step one minute</AsyncButton>
        </div>
        {run.snapshot?.error && <p role="alert">{run.snapshot.error}</p>}
        <p>Snapshots include events before the displayed time. Replay may take a moment.</p>
      </Panel>
      {run.snapshot?.checkins.map(check => <section key={check.contact} className="panel phone-screen">
        <p className="badge">SIMULATED CHECK-IN</p>
        <h2>Your mom is checking it’s really you.</h2>
        <p>Did you make this request?</p>
        {run.snapshot?.claim && <blockquote>{run.snapshot.claim}</blockquote>}
        <p>{check.status.replaceAll("_", " ")}</p>
        <div className="grid gap-2">
          {[
            ["not_genuine", "No, that wasn’t me"],
            ["genuine", "Yes, that was me"],
            ["will_call", "I’ll call her"]
          ].map(([reply, label]) => <AsyncButton
            key={reply}
            primary={reply === "not_genuine"}
            disabled={check.status !== "pending" || run.refreshing}
            run={() => control("inject", {
              event: {
                at: check.reply_at,
                event: "contact.checkin_reply",
                contact: check.contact,
                reply,
                requested_at: check.requested_at,
                deadline: check.deadline
              }
            })}
          >
            {label}
          </AsyncButton>)}
        </div>
        <p className="muted">This changes only the isolated scenario. No real message or call is sent.</p>
      </section>)}
      <Panel title="Inject a supported event">
        <label>
          Typed scenario event JSON
          <textarea value={event} onChange={e => setEvent(e.target.value)} rows={5} />
        </label>
        <p>
          Presence, recovery, doorbell, inbound-call and simulated check-in events use the repository scenario schema.
        </p>
        <AsyncButton run={() => control("inject", { event: JSON.parse(event) })}>Inject simulated event</AsyncButton>
      </Panel>
      <details className="panel">
        <summary>Source-labeled observations and limitations</summary>
        {run.snapshot?.limitations?.map(line => <p key={line}>{line}</p>)}
        <pre>{JSON.stringify(run.snapshot?.observations ?? [], null, 2)}</pre>
      </details>
    </>}
  </>;
}
