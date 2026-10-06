import { useState } from "react";
import { NavLink } from "react-router-dom";
import type { Result } from "../../../mcp-app/src/schema";
import { api, useResource } from "../api";
import { AsyncButton, Load, Panel } from "../components/primitives";
import { date, requestId, type Plan } from "../types";

export function Tonight() {
  const r = useResource<{
    plan: Plan | null;
    preparation: string | null;
    devices: { name: string; kind: string }[];
    policy_status: string;
    paused: boolean;
  }>("/tonight", true);
  const [message, setMessage] = useState(""), [limit, setLimit] = useState(50), [device, setDevice] = useState("");
  if (!r.data || r.error) return <Load {...r} />;
  const { plan, paused, policy_status } = r.data;
  const tool = async (name: string, input: object) => {
    const result = await api<Result>(`/tools/${name}`, { ...input, request_id: requestId() });
    setMessage(result.speakable.headline);
    r.retry();
  };
  return <>
    <p className="eyebrow">YOUR HOUSEHOLD</p>
    <h1>Tonight</h1>
    {policy_status !== "active" ? <Panel title="Activate your household rules">
      <p>Review and activate the initial policy before starting automation.</p>
      <NavLink to="/constitution">Review household rules →</NavLink>
    </Panel> : <>
      <Panel title={paused ? "Automation is paused" : "Household automation"}>
        <p>
          {paused ? "Already-authorized bounded endings still finish." : "Hirz follows your active household rules."}
        </p>
        <AsyncButton
          run={async () => {
            if (paused) await api("/resume", {});
            else await tool("execute_household_action", { action: "pause_automation" });
            r.retry();
          }}
        >
          {paused ? "Resume automation" : "Pause automation"}
        </AsyncButton>
      </Panel>
      <Panel title={plan ? "Your current plan" : "Prepare tonight’s plan"}>
        {plan ? <>
          <p className="badge">{plan.status}</p>
          <p>{date(plan.horizon.start)} – {date(plan.horizon.end)}</p>
          {plan.comparison_validity.valid && plan.summary.estimated_savings_usd !== null && <p className="figure">
            {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
              plan.summary.estimated_savings_usd
            )}
            <span> estimated saving</span>
          </p>}
          {plan.alternatives.map((a, i) => <p key={i}>{a.label}: {a.why_rejected}</p>)}
          <AsyncButton
            primary
            disabled={paused || ["refreshing", "blocked", "approved", "executing"].includes(plan.status)}
            run={() => tool("approve_action", { plan_id: plan.plan_id, version: plan.version, approved: true })}
          >
            Approve this plan
          </AsyncButton>
          <AsyncButton
            run={() => tool("approve_action", { plan_id: plan.plan_id, version: plan.version, approved: false })}
          >
            Skip this plan
          </AsyncButton>
        </> : <>
          <p role="status">
            {r.data.preparation === "pending"
              ? "The worker is preparing your plan…"
              : r.data.preparation === "failed"
                ? "Planning is blocked: the configured inputs did not produce an available plan."
                : "The worker prepares the plan from the household’s configured inputs."}
          </p>
          <AsyncButton
            primary
            disabled={r.data.preparation === "pending"}
            run={() => tool("get_household_plan", { horizon: "tonight" })}
          >
            {r.data.preparation === "failed" ? "Retry plan preparation" : "Prepare plan"}
          </AsyncButton>
        </>}
      </Panel>
      {plan && <Panel title="Change tonight’s plan">
        <AsyncButton run={() => tool("explain_plan", { plan_id: plan.plan_id, focus: "summary" })}>
          Why this plan?
        </AsyncButton>
        <label>
          Car
          <select value={device} onChange={e => setDevice(e.target.value)}>
            <option value="">Choose a car</option>
            {r.data.devices.filter(d => d.kind === "ev").map(d => <option key={d.name}>{d.name}</option>)}
          </select>
        </label>
        <label>
          Maximum charge (%)
          <input type="number" min={0} max={80} value={limit} onChange={e => setLimit(Number(e.target.value))} />
        </label>
        <AsyncButton
          disabled={!device || limit < 0 || limit > 80}
          run={() => tool("revise_household_plan", {
            text: `Keep ${device} at or below ${limit}% tonight`,
            applies_to: device,
            kind: "constraint",
            operation: "add",
            change: "car_limit",
            percent: limit
          })}
        >
          Update charge limit
        </AsyncButton>
        <p className="muted">Review the refreshed plan before approving it.</p>
      </Panel>}
    </>}
    {message && <p role="status">{message}</p>}
  </>;
}
