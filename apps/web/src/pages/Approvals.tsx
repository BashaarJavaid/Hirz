import { useEffect, useState } from "react";
import type { Result } from "../../../mcp-app/src/schema";
import { api, passkey, useResource } from "../api";
import { AsyncButton, Load, Panel } from "../components/primitives";
import { date, requestId, type Pending } from "../types";
import snapshot from "../../../../hirz/adapters/doorbell/twin/snapshot.svg?inline";

function PushSetup() {
  const state = useResource<{
    available: boolean;
    public_key: string | null;
    deliveries: { status: string; attempts: number }[];
  }>("/push", true);
  const [message, setMessage] = useState("");
  return <Panel title="Phone notifications">
    <p>On iPhone, add Hirz to your Home Screen, then open it there to enable notifications.</p>
    <AsyncButton
      disabled={!state.data?.available}
      run={async () => {
        if (!("Notification" in window) || !("serviceWorker" in navigator)) throw new Error(
          "Push is unavailable in this browser. iPhone notifications require iOS 16.4 or later " +
          "and the Home Screen app. Your approval inbox remains usable."
        );
        const permission = await Notification.requestPermission();
        if (permission !== "granted") throw new Error("Notifications were not enabled. Use your approval inbox.");
        const worker = await navigator.serviceWorker.register("/sw.js");
        await navigator.serviceWorker.ready;
        const key = Uint8Array.from(
          atob(state.data!.public_key!.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0)
        );
        const subscription = await worker.pushManager.getSubscription() ?? await worker.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: key
        });
        await api("/push/subscribe", subscription.toJSON());
        setMessage("Notifications enabled on this browser.");
        state.retry();
      }}
    >
      Enable notifications
    </AsyncButton>
    {state.data && !state.data.available && <p>Push is not configured. Requests remain in your approval inbox.</p>}
    {message && <p role="status">{message}</p>}
    {state.data?.deliveries.map((d, i) => <p key={i}>{d.status} · {d.attempts} delivery attempts</p>)}
  </Panel>;
}

export function Approvals() {
  const [message, setMessage] = useState(""), [requestedApproval, setRequestedApproval] = useState<string>();
  const r = useResource<{
    approvals: Pending[];
    locks: {
      name: string;
      observation: {
        source: string;
        observed_at: string;
        state: { locked: boolean | null; available: boolean | null };
      } | null;
    }[];
    demo_controls: boolean;
    door: { context: string[]; snapshot: string | null; lock_state: string } | null;
  }>("/approvals", true);
  useEffect(() => {
    if (!requestedApproval || !r.data?.approvals.some(p => p.id === requestedApproval)) return;
    const card = document.getElementById(`approval-${requestedApproval}`);
    card?.scrollIntoView({ block: "start" });
    card?.focus({ preventScroll: true });
    setRequestedApproval(undefined);
  }, [requestedApproval, r.data]);
  if (!r.data || r.error) return <Load {...r} />;
  return <>
    <p className="eyebrow">YOUR DECISION</p>
    <h1>Approvals</h1>
    <PushSetup />
    {r.data.demo_controls && <Panel title="Disposable phone test">
      <p className="badge">simulated</p>
      <AsyncButton
        run={async () => {
          await api("/twin/doorbell", {});
          const result = await api<Result>("/tools/execute_household_action", {
            action: "request_door_unlock",
            minutes: 1,
            request_id: requestId()
          });
          const approval = result.data.decision?.approval;
          setRequestedApproval(approval?.approval_id);
          setMessage(approval
            ? "Request ready. Review the unlock approval below, then choose Approve with passkey."
            : result.speakable.headline);
          r.retry();
        }}
      >
        Ring twin doorbell and request a one-minute unlock
      </AsyncButton>
      {message && <p role="status">{message}</p>}
    </Panel>}
    {(r.data.locks ?? []).map(lock => <Panel key={lock.name} title="Door read-back">
      <p>{lock.name}</p>
      <p className="badge">{lock.observation?.source === "real" ? "live" : "simulated"}</p>
      <p role="status">
        {lock.observation?.state.available === true && typeof lock.observation.state.locked === "boolean"
          ? lock.observation.state.locked ? "locked" : "unlocked"
          : "unavailable; actual state unknown"}
      </p>
      {lock.observation && <p className="muted">Observed {date(lock.observation.observed_at)}</p>}
    </Panel>)}
    {!r.data.approvals.length && <Panel title="You’re all caught up"><p>No eligible pending requests.</p></Panel>}
    {r.data.approvals.map(p => <Panel
      key={p.id}
      id={`approval-${p.id}`}
      title={p.action.class.startsWith("security.") ? "Unlock approval" : "A household action needs you"}
    >
      <p className="badge">{p.action.target.adapter === "twin" ? "simulated" : "Device request"}</p>
      <p>{p.action.reason}</p>
      <p>{p.status} · {p.quorum.replaceAll("_", " ")} · Expires {date(p.expires_at)}</p>
      {p.action.class.startsWith("security.") ? <div className="phone-screen">
        {r.data?.door?.snapshot === "twin" && <img src={snapshot} alt="Simulated doorbell snapshot" />}
        <h2>Someone is at the front door.</h2>
        {r.data?.door?.context.map((line, i) => <p key={i}>{line}</p>)}
        <p>
          Unlock for {String(p.action.params.open_minutes)} {Number(p.action.params.open_minutes) === 1
            ? "minute" : "minutes"}?
        </p>
        <p className="muted">Household security rule · {p.risk_band} risk</p>
        <p>I confirm this request. A schedule does not identify the visitor.</p>
        <div className="flex gap-2">
          {[true, false].map(approved => <AsyncButton
            primary={approved}
            key={String(approved)}
            run={async () => {
              await passkey({ operation: "approve", approval_id: p.id, action_hash: p.action.content_hash, approved });
              r.retry();
            }}
          >
            {approved ? "Approve with passkey" : "Deny"}
          </AsyncButton>)}
        </div>
      </div> : <div className="flex gap-2">
        {[true, false].map(approved => <AsyncButton
          primary={approved}
          key={String(approved)}
          run={async () => {
            await api("/tools/approve_action", {
              action_id: p.action.action_id,
              approval_id: p.id,
              approved,
              request_id: requestId()
            });
            r.retry();
          }}
        >
          {approved ? "Approve" : "Deny"}
        </AsyncButton>)}
      </div>}
    </Panel>)}
  </>;
}
