import { App, type McpUiHostContext } from "@modelcontextprotocol/ext-apps";
import { createRoot } from "react-dom/client";
import { useEffect, useRef, useState } from "react";
import { type Card, type Result, money, readResult } from "./schema";
import snapshot from "../../../hirz/adapters/doorbell/twin/snapshot.svg?inline";
import "./style.css";

declare const __CARD__: string;
const expandable = ["plan-card", "scorecard"].includes(__CARD__);
const app = new App({ name: "Hirz", version: "0.1.0" }, { availableDisplayModes: expandable ? ["inline", "fullscreen"] : ["inline"] }, { autoResize: false });
type Call = { name: string; arguments: Record<string, string | number | boolean> };
const time = (value: string) => new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function Annual({ card }: { card: Extract<Card, { kind: "plan" | "scorecard" }> }) {
  const evidence = card.annualized;
  return <section className="annual"><p>Backtest annualized extrapolation</p><strong>{money(evidence?.usd)}</strong>{evidence && <p>{evidence.eligible_days}/{evidence.total_days} eligible days · eligible-day mean × 365. Missing data may bias this estimate.</p>}</section>;
}

function CardApp() {
  const [result, setResult] = useState<Result>();
  const [context, setContext] = useState<McpUiHostContext>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const [car, setCar] = useState(50);
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const outstanding = useRef(false);
  const retry = useRef<Call | undefined>(undefined);
  const input = useRef<Record<string, string | number | boolean>>({});
  const preparation = useRef(Date.now());
  const mounted = useRef(true);
  const data = result?.data;
  const expectedKind = __CARD__ === "scorecard" ? "scorecard" : __CARD__.replace("-card", "");
  const card = data?.presentation?.kind === expectedKind ? data.presentation : undefined;
  const full = context?.displayMode === "fullscreen" && expandable;
  const stale = !!card && clock >= Date.parse(card.valid_until);
  const disabled = busy || stale || !!error || !["ok", "recorded"].includes(data?.status ?? "");

  function receive(value: unknown) {
    const next = readResult(value);
    setResult(next);
    if (next.data.presentation?.kind === "plan" && next.data.presentation.car_limit != null) setCar(next.data.presentation.car_limit);
    setError("");
  }

  async function call(request: Call, mutation = false, reuse = false) {
    if (outstanding.current) return;
    const epoch = generation.current;
    outstanding.current = true;
    setBusy(true);
    const exact = mutation && !reuse ? { ...request, arguments: { ...request.arguments, request_id: crypto.randomUUID() } } : request;
    retry.current = exact;
    try {
      const response = await app.callServerTool(exact);
      if (!mounted.current || epoch !== generation.current) return;
      const next = readResult(response);
      if (card?.kind === "doorbell" && mutation) {
        setNotice(next.speakable.headline);
      } else {
        receive(response);
      }
      retry.current = undefined;
      setError("");
    } catch {
      if (mounted.current && epoch === generation.current) setError("Could not refresh this card. Retry or link your account again.");
    } finally {
      outstanding.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    app.ontoolinput = ({ arguments: args }) => { input.current = (args ?? {}) as Record<string, string | number | boolean>; };
    app.ontoolresult = value => {
      generation.current++;
      retry.current = undefined;
      preparation.current = Date.now();
      setNotice("");
      try { receive(value); } catch { setResult(undefined); setError("This card's data is unavailable. Ask Hirz again."); }
    };
    app.ontoolcancelled = () => { generation.current++; retry.current = undefined; setResult(undefined); setError("The request was cancelled. Ask Hirz again."); };
    app.onhostcontextchanged = update => setContext(previous => ({ ...previous, ...update }));
    app.onteardown = async () => { mounted.current = false; generation.current++; return {}; };
    app.connect().then(() => setContext(app.getHostContext())).catch(() => setError("The host connection is unavailable."));
    return () => { mounted.current = false; generation.current++; void app.close(); };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = context?.theme ?? "light";
    function scale() {
      const dimensions = context?.containerDimensions;
      const ceiling = dimensions && "height" in dimensions ? dimensions.height : dimensions?.maxHeight;
      const factor = Math.min(window.innerWidth / 768, (ceiling ?? Infinity) / 480);
      document.documentElement.style.setProperty("--scale", String(factor));
      if (context) void app.sendSizeChanged({ height: Math.round(480 * factor) }).catch(() => undefined);
    }
    scale(); window.addEventListener("resize", scale);
    return () => window.removeEventListener("resize", scale);
  }, [context]);

  useEffect(() => {
    const tick = window.setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(tick);
  }, []);

  useEffect(() => {
    if (error || !result) return;
    let request: Call | undefined;
    let delay = 2000;
    if (data?.status === "preparing" && Date.now() - preparation.current < 30000) { request = { name: "get_household_plan", arguments: {} }; delay = 1000; }
    if (card?.kind === "verification" && card.status === "pending" && !stale && data?.case) request = { name: "verify_trusted_identity", arguments: { operation: "status", case_id: data.case.case_id } };
    if (card?.kind === "doorbell") request = { name: "get_household_context", arguments: { scope: "environment" } };
    if (!request) return;
    const exact = request;
    const timer = window.setInterval(() => {
      if (document.hidden || !mounted.current) return;
      if (data?.status === "preparing" && Date.now() - preparation.current >= 30000) return;
      if (card?.kind === "verification" && Date.now() >= Date.parse(card.valid_until)) return;
      void call(exact);
    }, delay);
    return () => clearInterval(timer);
  }, [result, error]);

  const approve = (approved: boolean) => {
    if (!data || disabled) return;
    if (card?.kind === "plan" && data.plan) void call({ name: "approve_action", arguments: { approved, plan_id: data.plan.plan_id, version: data.plan.version } }, true);
    if (card?.kind === "approval" && card.can_respond && !card.phone_required && data.decision?.approval) void call({ name: "approve_action", arguments: { approved, action_id: data.decision.action_id, approval_id: data.decision.approval.approval_id, ...(card.plan_id && card.version ? { plan_id: card.plan_id, version: card.version } : {}) } }, true);
  };
  async function expand() {
    try { const next = await app.requestDisplayMode({ mode: full ? "inline" : "fullscreen" }); setContext(previous => ({ ...previous, displayMode: next.mode })); }
    catch { setNotice("This host cannot change the display mode."); }
  }
  const plan = data?.plan;
  const savings = plan?.comparison_validity.valid ? plan.summary.estimated_savings_usd : null;
  return <main className={full ? "canvas fullscreen" : "canvas"} aria-label="Hirz household card" aria-busy={busy}>
    <header><span className="wordmark">hirz</span><span className="badge">{card?.source ?? "simulated"}</span>{expandable && (full || card && context?.availableDisplayModes?.includes("fullscreen")) && <button className="expand" onClick={() => void expand()} aria-label={full ? "Close details" : "Open details"}>{full ? "Close details" : "Details ↗"}</button>}</header>
    <div className="content">
      {!card && <><h1>{result?.speakable.headline ?? "Waiting for household information"}</h1><p role="status">{data?.status === "preparing" ? "Preparing your plan…" : result?.speakable.details.join(" ")}</p></>}
      {card?.kind === "plan" && plan && <>
        <p className="eyebrow">Estimated savings against your timer</p><h1 className="figure">{money(savings)}</h1>
        <p className="caption">{time(plan.horizon.start)} – {time(plan.horizon.end)}</p>
        <ul className="rows">{(full ? card.timeline : card.rows).map(row => <li key={row.action_id}>{full && row.at && <time>{time(row.at)} · </time>}{row.label}</li>)}</ul>
        {card.car_limit != null && <div className="ev-bar" role="meter" aria-label="Car charge limit" aria-valuenow={card.car_limit} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${card.car_limit}%` }} /></div>}
        {full && <><Annual card={card} />{card.annualized && <p>{card.annualized.label} · {card.annualized.period} · {card.annualized.profile} · {card.annualized.household_variant} · wear ${card.annualized.wear_per_internal_kwh}/kWh. Evidence SHA-256: <span className="hash">{card.annualized.sha256}</span></p>}<h2>Alternatives</h2>{plan.alternatives.map(a => <p key={a.label}>{a.label}: {money(a.validity.valid ? a.cost_delta_usd : null)} · {a.why_rejected}</p>)}
          {card.can_revise_car && <form onSubmit={event => { event.preventDefault(); if (!disabled) { preparation.current = Date.now(); void call({ name: "revise_household_plan", arguments: { text: `Do not charge the car past ${car} percent tonight.`, applies_to: "car", kind: "constraint", operation: "add", change: "car_limit", percent: car } }, true); } }}><label htmlFor="car-limit">Car charge limit (%)</label><input id="car-limit" type="number" min="0" max="80" step="1" required value={car} onChange={event => setCar(event.target.valueAsNumber)} /><button disabled={disabled}>Update limit</button></form>}
        </>}
      </>}
      {card?.kind === "approval" && <><h1>{card.label}</h1><ul className="rows"><li>{card.rule}</li><li>Risk: {card.risk_band}</li></ul>{card.phone_required && <p>Approval requires your phone. Phone approval is unavailable in this preview.</p>}</>}
      {card?.kind === "verification" && <><h1>{result?.speakable.headline}</h1><ul className="rows">{card.signals.map(signal => <li key={signal}>{signal}</li>)}</ul><p key={card.status} className="verification-result" role="status">{card.status.replaceAll("_", " ")}</p></>}
      {card?.kind === "doorbell" && <><h1>Someone is at the front door</h1><div className="door"><div>{card.snapshot === "twin" ? <img src={snapshot} alt="Simulated doorbell snapshot" /> : <p>Snapshot unavailable</p>}</div><div>{card.context.slice(0, 2).map(line => <p key={line}>{line}</p>)}<p className="lock" data-state={card.lock_state}><span aria-hidden="true" />{card.lock_state === "unknown" ? "Lock state unavailable" : `Observed: ${card.lock_state}`}</p></div></div></>}
      {card?.kind === "scorecard" && <><p className="eyebrow">Plan estimate · savings against timer</p><h1 className="figure">{money(savings)}</h1>{plan && <p className="caption">{time(plan.horizon.start)} – {time(plan.horizon.end)}</p>}<Annual card={card} /><p>Estimated peak reduction: {plan?.comparison_validity.valid && plan.summary.peak_kwh_avoided != null ? `${plan.summary.peak_kwh_avoided.toFixed(2)} kWh` : "Unavailable"}</p>{full && <><h2>Distinct device actions</h2><p>{card.counts.autonomous} without per-action approval · {card.counts.asked} asked · {card.counts.blocked} blocked · {card.counts.verified} verified</p><p>Categories can overlap. Previews and private contact cases are excluded.</p>{card.annualized && <p>{card.annualized.label} · {card.annualized.period} · {card.annualized.profile} · {card.annualized.household_variant} · wear ${card.annualized.wear_per_internal_kwh}/kWh. Evidence SHA-256: <span className="hash">{card.annualized.sha256}</span></p>}<h2>Decisions</h2>{data?.audit.map((entry, index) => <p key={index}>{time(entry.at)} · {entry.summary}</p>)}{data?.cursor && <button disabled={disabled} onClick={() => void call({ name: "get_action_audit", arguments: { ...input.current, cursor: data.cursor! } })}>Next page</button>}</>}</>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
    </div>
    <footer>
      {card?.kind === "plan" && card.can_approve && <button className="primary" disabled={disabled} onClick={() => approve(true)}>Approve plan</button>}
      {card?.kind === "plan" && full && <button disabled={disabled} onClick={() => approve(false)}>Skip tonight</button>}
      {card?.kind === "approval" && card.can_respond && !card.phone_required && <><button className="primary" disabled={disabled} onClick={() => approve(true)}>Approve</button><button disabled={disabled} onClick={() => approve(false)}>Deny</button></>}
      {card?.kind === "verification" && card.can_check && data?.case && <button className="primary" disabled={disabled} onClick={() => void call({ name: "verify_trusted_identity", arguments: { operation: "start", case_id: data.case!.case_id } }, true)}>Check with {card.contact_name}</button>}
      {card?.kind === "doorbell" && card.can_request && card.lock_state !== "unknown" && card.room && <button className="primary" disabled={disabled} onClick={() => void call({ name: "execute_household_action", arguments: { action: "request_door_unlock", minutes: 10, room: card.room! } }, true)}>Request 10-minute unlock</button>}
      {error && retry.current && <button disabled={busy} onClick={() => void call(retry.current!, false, true)}>Retry</button>}
      {!error && (stale && card?.kind !== "approval" || data?.status === "preparing" && clock - preparation.current >= 30000) && <button disabled={busy} onClick={() => { preparation.current = Date.now(); void call({ name: card?.kind === "verification" ? "verify_trusted_identity" : card?.kind === "scorecard" ? "get_action_audit" : card?.kind === "doorbell" ? "get_household_context" : "get_household_plan", arguments: card?.kind === "verification" && data?.case ? { operation: "status", case_id: data.case.case_id } : card?.kind === "doorbell" ? { scope: "environment" } : card?.kind === "scorecard" ? input.current : {} }); }}>Refresh</button>}
      {card?.kind === "plan" && card.rate_label && <small>{card.rate_label}</small>}
    </footer>
  </main>;
}

createRoot(document.getElementById("root")!).render(<CardApp />);
