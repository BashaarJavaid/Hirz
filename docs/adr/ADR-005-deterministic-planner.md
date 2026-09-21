# ADR-005 — Deterministic MILP planner; the LLM only narrates

**Status:** Accepted (2026-09-15)

**Decision:** Household plans are produced by a rolling-horizon mixed-integer linear program solved with HiGHS via `scipy.optimize.milp`, with a greedy heuristic for cold starts. Bedrock Claude turns the plan's structured facts into narration data. No model participates in choosing actions or times.

**Reasoning:**

- Energy scheduling under prices, deadlines, comfort bands, and member constraints is a textbook MILP. The solver gives an optimum, a gap, and a baseline to compute savings against, which makes the scorecard's numbers defensible.
- Explainability follows from structure: the binding constraints and the rejected alternatives are outputs of the model, not stories.
- Determinism keeps the planner off the model budget and off the Alexa latency path (it runs on triggers, never inside a tool call).
- One dependency (`scipy`) already common in the stack; HiGHS handles the instance sizes (about 800 variables) in well under a second.

**Alternatives considered:**

- *LLM planning with tool calls.* Fluent but unverifiable; would produce the 42 kW charger the original mockup accidentally implied. Rejected.
- *OR-Tools CP-SAT.* Excellent solver, larger dependency and a different modeling style; not needed at this scale. Revisit if appliance sequencing grows combinatorial.
- *EMHASS (the Home Assistant energy-management add-on).* It already optimizes solar, a battery, and deferrable loads including EV charging with a linear program, so "an energy optimizer" is not what Hirz adds. Not adopted as a component: its configuration model has no place for member constraints with provenance, per-occupant comfort bands, or a constitution's bounds, and wrapping it would be more code than the 800-variable model it would replace. It is the benchmark: the README's claim is governance over coordinated automation, not a better optimizer, and the backtest compares against a timer schedule and a cheapest-slots strategy rather than against doing nothing (added 2026-09-17).
- *Rule-based scheduling (charge in cheapest slots).* Kept as the heuristic fallback; rejected as the primary because it cannot trade comfort against cost or respect coupled constraints.

**Consequences:** Every physical parameter (charger kW, battery kWh, zone R and C) is a knob in the household graph and the scenario file because real hardware never matches the model on paper; the planner exposes `optimality_gap` and the executor's verify-after-act feeds deviations back as re-plan triggers.

## Scheduled action authority amendment — 2026-09-18 (author-approved)

**Decision:** A scheduled action carries `requested_by` of the member who approved
its plan, with `surface: scheduler`. A plan nobody approved does not execute.
An autonomous re-plan inherits the approving member of the plan it supersedes.
Scheduled actions never run as `unknown` or a synthetic system identity.
Households can tighten scheduled behaviour with `requester.surface == "scheduler"`
conditions, which the existing grammar already supports. Implementation belongs
to roadmap item 19.

**Reasoning:** Authority must trace to a person for the audit row and the boundary's
`requester_role` input; a plan approval is exactly that trace. Scheduling or
re-planning does not create a new source of authority, and execution-time pipeline
re-evaluation still applies.

**Rejected alternatives:**

- *Run as the household owner:* substitutes the owner's authority for the actual
  approver's and misattributes the action.
- *Run as a system role:* invents authority without a person and requires a new
  policy role outside the household's existing member rules.
- *Run as unknown and rely on auto rules:* loses the approval trace and is denied
  by the seeds' `per_role.unknown: '*': never`; auto rules cannot override that veto.

## Read-only planner and historical experiment — 2026-09-21

**Decision (approved item 17 plan):** Use SciPy 1.18.0's
[`milp`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
with a five-second limit and 0.001 relative gap. Validate an incumbent against
its bounds, integrality, linear constraints, and the existing pure twin transitions
before accepting it. A timeout without an incumbent can use greedy; proven
infeasibility cannot. Newest-first, single-constraint removal probes diagnose
conflicts without applying a relaxation. A previous proposal is reference data,
not a valid replacement or execution grant.

The proposed canonical `Plan` keeps Action IDs; the internal result carries the
Actions, forecast provenance, diagnostics and comparison validity. No endpoint,
database schema, approval, device execution or coordinator intake is added.
EV schedules use on/off plus per-slot charge limits; targets above 80% are rejected
while the existing twin taper is preserved. HVAC heat/cool energy has an exclusivity
binary and produces setpoints and modes for the existing thermostat transition.
Battery charge/discharge and grid import/export are separately exclusive; battery
exports are prohibited. Solar exports receive no credit. Hard comfort bounds,
EV delivery, appliance completion and equal opening/ending battery energy apply
to every comparison. Energy tolerance is 0.000001 kWh; temperature tolerance is
0.0001°F. A failed comparison has null savings, never a zero saving.

Minimize electricity plus $0.01 per internal-throughput kWh; repeat with $0 and
$0.02. Peak and soft-comfort penalties are zero. Timer charges the car at 21:00;
immediate starts at the earliest permitted instant; greedy chooses forecast
slots and a contiguous appliance window. Their thermostat targets and battery
policy are shared. Battery self-consumption restores opening energy during
21:00–06:00 and preserves that reserve afterwards. To meet terminal equality,
surplus charging is limited to energy that can serve the remaining forecast
household load before the boundary; it is not limited to the opening reserve.
No realized future load is used for that limit.

The study requests 2025-09-01 17:30 through 2026-09-01 17:30 Chicago, for all
three approved household configurations on both profiles, with state carried
between days. Quarter-hour boundaries are UTC-based, retaining partial first
slots and 92/100-slot DST days. The ending temperature must permit the next
boundary's comfort requirement. The 12 kWh drive occurs at the 08:00 departure,
with no subsequent charging before the next 17:30 arrival.

Raw responses, URL/retrieval-time/SHA-256 manifests, workload parameters, JSON,
CSV and generated publication rows live in `scripts/backtest-data`. Downloads
are explicit, sequential, and resume missing responses. Day-ahead responses are
retained as evidence only. Forecasts use the nearest matching Chicago hour in
the preceding seven days whose hour ended at least 24 hours before the decision;
missing and ambiguous source hours are excluded and selected timestamps retained.
Realized weather is [Open-Meteo archive reanalysis](https://open-meteo.com/en/docs/historical-weather-api).
Hourly billing requires twelve five-minute quotes per UTC hour, following
[ComEd's explanation](https://hourlypricing.comed.com/live-prices/); these are
feed-based cost estimates, not reconciled bills. Both study profiles explicitly
apply the pinned 2026 tariff counterfactually, preserving the production tariff
validity checks and supply-plus-distribution exclusions.

**Rejected alternatives:** hindsight planning; filling missing billing quotes;
resetting state each day; crediting exports without a tariff; silently relaxing
comfort; claiming savings from less delivered energy; and persisting proposals
or implementing a scorecard before their roadmap items. Missing realized prices
invalidate that day's costs without resetting physical state. Missing forecasts
or an inability to continue inside hard constraints stops the affected strategy
and retains its state and failure evidence. Fixed forecast-derived controls are
not silently replaced with a feedback controller to rescue a historical figure.
Actual coverage and the remaining acceptance failures are in the
[item 17 verification entry](../verification-log.md#item-17--partial-2026-09-21).
