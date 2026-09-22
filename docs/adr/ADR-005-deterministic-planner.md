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

### Causal historical replay amendment — 2026-09-21

The author approved fixing the stopped historical runs now, within item 17. This
amends the earlier decision to retain fixed forecast-derived controls during
realized replay. The economic MILP still runs once per local day. Its proposed
Actions, their hashes, and their lack of execution authority are unchanged.
`replay` remains a strict validator; `feedback.simulate` supplies hypothetical
applied controls and then passes them through that same validator. This is not
coordinator intake, a live controller, or an exception to Pipeline authorization.

Every study strategy uses the same causal device protection. The thermostat
selects the existing heat/cool mode from current temperature and the current
weather observation. It prepares for a tightening comfort window at that window's
already-declared occupied target. Backward reachability uses the configured
thermal mass, resistance, occupants and rated power. In forecast baseline
construction it uses forecast weather; during replay it holds the current
observation constant for this local prediction. It never reads later realized
weather. An unachievable band still fails validation; no capacity, tolerance or
comfort requirement is relaxed.

The simulated battery follows the requested dispatch for MILP, or the approved
self-consumption/restoration policy for the three baselines, subject to the same
no-export and terminal-energy protection. Discharge cannot exceed present net
household demand. The reachable lower energy bound reserves enough remaining
charging time to restore opening energy. The upper bound permits excess stored
energy only when remaining **guaranteed** self-consumption can remove it: base
load minus the installed PV model's zero-cloud upper bound, limited by battery
power and efficiency. This bound is known before the decision and does not use
realized future load, weather or prices. With no supplied PV bound, guaranteed
future self-consumption is conservatively zero. Scheduled EV and HVAC consumption
are deliberately omitted from this guarantee. Any curtailed or corrective
charging/discharging is metered, loses energy normally, and incurs normal wear.
There is no terminal state reset or unmetered energy adjustment.

Historical inputs explicitly select `causal_controls`. The same reachable battery
bounds and occupied-target preparation are included in the MILP and baseline
construction before solving, so a schedule cannot rely on energy the controller
will predictably curtail. Forecast acceptance first checks the requested schedule
strictly, then simulates its declared device behavior. The fixed-control input
mode remains available for existing scenario snapshots; there is no inference of
controller capabilities from the availability of a PV forecast.

Environmental samples retain the declared quarter-hour zero-order hold. Replay
splits at EV charge-limit and appliance completion times; each segment's HVAC
power follows the existing explicit thermal transition from its opening state
and current forcing. Battery dispatch responds to those current commanded loads,
not a subsequently observed interval total. Requested schedules, applied controls
and segment boundaries are retained in compressed JSON. Reported grid energy is
aggregated back to the original slots. Supply-negative and total-price-negative
charging durations count the union of EV and battery charging, without counting
simultaneous charging twice.

**Rejected alternatives:** clipping battery export without restoring terminal
energy; resetting SoC; giving the optimizer later weather or prices; replanning
against realized prices; relaxing comfort or energy tolerances; granting more
HVAC power; allowing the optimizer feedback that baselines lack; and making
missing billing prices stop a physically valid run. Physical completion and
eligible cost-comparison coverage are separate gates. Missing billing hours
still suppress savings, and missing forecasts or physical failures still stop
and retain the affected run. Compression is for retained evidence size; offline
reproduction compares the unrounded numerical output, excluding timing only.

Annual replications run sequentially. A concurrent trial reached the five-second
limit on one day, while a repeat reached the requested gap with a different
schedule. Running competing solves or compressing artifacts during a timed solve
was rejected. The solver still accepts validated timeout incumbents, but a timed
result is not promised bitwise reproducible across machine loads; retained study
outputs must independently pass exact reproduction before publication.

## Coordinator amendment — 2026-09-21

Item 18 adds bounded deterministic sentence intake and a read-only coordination
service. Its grammar, conflict output and physical hold semantics are specified in
[architecture §5.5](../../ARCHITECTURE.md#55-coordinator). Account ownership comes
from Pipeline, never from names in sentences. Exact EV targets and ceilings are
separate requirements; incompatible requests remain stored. Only an explicit
replacement or a uniquely matched `change` request withdraws an earlier request.
Known policy prohibitions and bounds use the existing evaluator; unresolved future
conditions remain pending execution-time evaluation. Quorum reporting uses its
existing `ApprovalRequirements`; voting remains Pipeline's responsibility.

Selected comfort preferences first minimize slot-duration-weighted absolute
ending-temperature deviation, equally across zones. A second pass minimizes
existing electricity and wear costs without increasing the first optimum beyond
numerical tolerance. Both passes share five seconds, including model construction.
Only validated incumbents survive, and diagnostics disclose unfinished preference
optimization or cost refinement. Without preferences, the existing cost objective
and retained experiment inputs remain unchanged. Hard bands are never relaxed.

Manual twin observations preserve target **and mode** for exactly two hours from
the event. They identify the submitting account, not the physical actor. A renewal
withdraws the previous hold and starts another two-hour window; any linked member
may release it. Environmental values use zero-order holds when slots split at
request boundaries. Held thermostat heat/cooling follows the existing thermal
transition, enters every strategy's metering, and produces no thermostat Action
inside the hold. Unsafe or infeasible holds produce conflicts, never corrective
Actions. Newest-first removal probes reconstruct the entire effective workload,
including bands and holds; their proposed relaxation is never applied.

Rejected: an LLM parser, silent target reduction by a ceiling, preference overrides
of hard bounds, automatic conflict resolution, plan-level voting, recurring rules,
a cleanup worker, and automatic HA change detection. Plans, jobs, execution, MCP,
UI and full scenario wiring remain in later items. No published saving changes
without successful reproduction of the retained experiment.

## Durable consent and explicit revisions amendment — 2026-09-21

Item 19 persists canonical proposals and separate action links. Owners, adults and
energy-eligible caregivers can consent. Scheduled work retains the approver's
linked account with `surface: scheduler`; account revocation or tighter rules can
hold it. Cancellation is available to the approver or owner. An explicit revision
requires fresh consent; an explicitly requested autonomous replacement inherits
its predecessor's approver. Each activation obtains a separate `energy.optimize_cost`
grant reserving the nonnegative electricity-plus-wear estimate. Unknown per-device
costs remain unknown, so a configured per-device budget cannot be bypassed by a
fabricated zero estimate. Refunds and settlement remain deferred.

Revision preserves executed evidence, cancels unstarted superseded work and expires
its pending approvals with `PLAN_REVISED`. Device ASK/DENY, unavailability or exhausted
retry holds remaining unstarted work, marks the plan `refreshing`, and records a
pending member notice. Approval while refreshing is refused. Explicit revision is
the recovery path in item 19; automatic refresh jobs, freshness and the documented
trigger set move to item 19a. Notification delivery remains companion-app work,
and full scenario orchestration remains item 22.

Planner actions now carry command-state deadlines. Nonzero EV and battery controls
include a stop at the next change or horizon end; stops receive ten seconds for
verification. Coordinator-supplied HVAC asset IDs populate target zones before
hashing. Rejected retroactively changing approved commands, extending a late
opening's interval, cancelling a required ending, and counting future temperature
or delivered charge as immediate command verification.

## Durable refresh amendment — 2026-09-21

Refresh rebuilds an explicitly supplied workload from current configured facts;
physical parameters and forecast coverage are never inferred. It preserves the
approved horizon, original battery terminal obligation, delivered EV energy,
completed appliance work and running cycles. Started bounded controls remain fixed
until their existing endings. Forecast slots split at commitments and rate changes.
HA thermal plans use observed heat/cool mode, device limits and optional advertised
setpoint increments; unsupported modes or missing required facts are held conflicts.

Timer, immediate and greedy comparisons replay the same remaining workload and
commitments. Published comparisons are labeled remaining-horizon estimates; a
blocked read invalidates claims without rewriting the historical proposal. Strict
per-asset prediction defaults are >1°F, >2 percentage points SoC and >0.25 kW.
Persisted fingerprints omit retrieval timestamps; unmatched observed thermostat
controls create renewable two-hour holds, with no inferred physical actor.

Rejected resetting battery obligations to the current SoC, restarting completed
appliances, extending bounded operations during refresh, silently substituting twin
facts for real devices, adding savings across revisions, and hiding infeasibility
behind historical claims. Internal refresh only: MCP, companion delivery, scenario
orchestration, live price/weather ingestion and AWS remain outside this item.


## Accepted preference coordination amendment — 2026-09-21

Map declared/accepted graph temperature preferences into transient, provenance-bearing
comfort windows in the existing Coordinator. They are not synthetic durable
constraints. An explicit request by that member for the same room/window takes
precedence. Fresh presence supplies a room until its existing deadline; arrival
context applies only from expected arrival through event end. Conflicting rooms
require clarification, and present-in-another-room evidence suppresses arrival
context. Carry the graph identity/version through explanations and conflicts.

Acceptance queues the existing automatic refresh in the preference transaction.
Refresh recomputes evidence and retains the household baseline temperature separately
from an applied preference, preventing stale overlays from becoming a default.
Inherited consent, hard bounds, holds and bounded endings are unchanged. Rejected
feeding provider hints or transcripts to the planner, inventing a default room,
letting stale presence persist through the horizon, and treating memory acceptance
as a fresh plan/device approval. [Contract](../../ARCHITECTURE.md#59-memory).

## Planned device approval resumption — 2026-09-22 (author-approved)

Item 22 adds canonical Plan status `awaiting_approval` and the internal
`PlanService.respond_to_action` operation. A device ASK preserves its pending
approval while pausing other unstarted work. Already-authorized endings continue.
A Pipeline vote grants no execution authority. The audited refresh lifecycle
rechecks the original action, accepted inputs, policy, linked scheduler identity,
quorum, TTL and execution window before scheduling it again. Dispatch still
requires the ordinary current boundary check. No freshness or approval clock is
extended; revision and cancellation invalidate the old work. Rejected conflating
plan consent with device approval, automatically voting in the worker, and copying
an execution grant into a replacement action.

The scenario declares its simulated affirmative turns explicitly. The EV target
is replaced at 17:35, with a separate ceiling. Dad's kitchen request is attributed
to Dad's linked account and explicitly normalized to 23:00; it does not claim to
move an already-late dishwasher. Fresh plan consent is required at 23:31. The
approved horizon ends at 07:00 and EV delivery is due at 06:30.

The executable replay exposed that pausing unstarted work after the 22:40 request
also prevents the guest room's late preheating. On 2026-09-22 the author approved
an earlier explicit 72°F guest-room request. The 17:35 intake is included in the
17:36 plan consent, so the room is warm before Dad's revision. Rejected silently
executing a revised plan before consent or weakening its hard comfort minimum.

Actuator rounding must preserve the existing replay guarantees. Four-decimal
thermostat rounding can reduce electrical load enough to make a previously exact
battery discharge export. The quantization pass removes that uncommitted export
and correspondingly reduces later charging, preserving terminal energy. Existing
replay checks still reject infeasible reserves or immutable commitments. Rejected
loosening the no-export or terminal-energy tolerances and altering backtest claims.

Partial-slot prediction retains the EV action's full charge ceiling while advancing
the existing physics only to the observation time. Prorating the ceiling incorrectly
predicted zero power during charging and repeatedly invalidated healthy plans.
Control ownership compares observations and action parameters at the same existing
graph precision. Neither correction relaxes drift thresholds or device authority.

Remaining-work comparisons retain the fixed timer window across midnight, using
the 21:00 start preceding the known EV deadline; the battery's morning terminal
floor uses that same anchor. Refresh also carries the last
coordinated EV target and deadline into its next workload: an expired 50% delivery
request cannot resurrect the superseded 80% default. The historical evening-start
backtest inputs and retained figures are unchanged.

The author also approved an explicit 17:35 request to run the dishwasher after
23:31. The host normalizes that to the existing `appliance_not_before` grammar,
without adding a parser or inferring a timing constraint from the tariff. This
ensures the declared nighttime device vote is exercised; Dad's later 23:00
constraint remains separately attributed and does not claim to move the schedule.

A late remaining-work baseline must restore terminal battery energy through the
approved horizon, including after 06:00 when necessary. The former fixed morning
cutoff could hold a physically feasible plan and make its terminal obligation
unreachable. Surplus discharge and the existing no-export checks remain in force;
the baseline cannot silently discard the terminal requirement.

### Exact bounded durations — 2026-09-22 (author-approved)

The author approved one additional canonical amendment after replay exposed a
whole-second timing conflict: `Revert.after_s` accepts strict integer or finite
floating-point seconds, at least one microsecond. Existing integer values and
canonical hashes remain valid. Planner and retry durations retain the exact
interval to their original absolute ending. The scripted host refreshes immediately
after the executor's monotonic microsecond ticks instead of introducing a one-second
gap. Rejected backdating the clock, rounding endings past the approved horizon,
relaxing terminal energy, and hiding execution latency in a changed EV/battery goal.
