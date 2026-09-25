# ADR-006 — Twin-first adapters: every domain ships real and twin behind one interface

**Status:** Accepted (2026-09-15)

**Decision:** Each adapter domain declares a `Protocol` and ships a real implementation coded against the vendor API and a twin implementation backed by physics-lite models on a simulated clock. The registry selects per domain at startup; every observation carries `source: real | twin`; every surface shows the label. The scenario DSL drives the twin and doubles as the integration test corpus.

**Amendment (2026-09-21):** Observation `source` has three values: `real`, `real API, demo devices`, and `twin`.

**Reasoning:**

- The author owns no Alexa device, EV, wearable, or smart-home hardware, and the product must demonstrate every capability end to end. Mocks would be dismissed; a labeled, reproducible, physically plausible twin is a product feature (onboarding preview, what-if planning, safe testing of a new constitution).
- Real data where it is free keeps the twin grounded: ComEd prices (the published Time-of-Day rate table, and the live Hourly Pricing feed) and Open-Meteo weather are real; Home Assistant's demo integration provides the real API over simulated devices (labeled `real API, demo devices`, never `real`); one physical energy-monitoring smart plug on HA's local integration is the living-room light, so a mixed real/twin household is a demonstrated configuration and verify-after-act runs against a measured power draw; Smartcar's sandbox and Ring's sandbox exercise the real API code paths.
- The same interface means buying a smart plug later is a configuration change, and a mixed real/twin household is a first-class configuration.
- Honest labeling converts a weakness into credibility with judges and, later, with customers.

**Alternatives considered:**

- *Hardcoded demo fixtures.* Rejected: numbers drift from physics, tests don't exercise real code paths, and the demo reads as fake.
- *Real hardware purchases.* Out of budget and would still leave EV, battery, and solar unrepresented.
- *Home Assistant only.* Good device layer, but no EV/battery/solar/wearable/contacts models and no scenario timeline; kept as the device adapter, not the twin.

**Consequences:** Twin models carry explicit calibration knobs and physics tests. The pipeline treats twin observations like real ones but the `state_stale` factor and verify-after-act apply equally, so a lying twin is caught the same way a flaky sensor would be.


## Item 12 contract amendment — 2026-09-19 (author-approved)

The author approved these choices individually during item 12 planning:

- Build all nine typed async protocols now, with shared lifecycle and canonical
  Action/Decision write arguments, but no production implementation, ingestion or
  execution. Prove mixed boot with labeled test implementations and actual CLI
  dispatch. Rejected moving real adapters/twin physics forward from items 13–15.
- Use a plain household-bound factory map, explicit per-entity binding overrides,
  method-name capabilities, and omitted domains as unavailable. Reject bad config
  and unavailable implementations. Rejected implicit twin defaults, mandatory
  all-domain configuration, plugin discovery and automatic fallback in item 12.
- Stamp only from trusted per-subject provenance; reject mismatches. Rejected
  trusting an adapter's label alone or silently labeling demo devices as real.
- Keep separate observation domains with JSONB expression indexes. Preserve
  legacy null-domain rows/history without inferring their meaning; decisions
  require new tagged readings. Rejected selecting streams by whichever fields
  happen to be present, inferred legacy backfills and extra relational columns.
  Tagged current or historical data prevents downgrade; history is never erased
  to make old code accept new data.
- Derive facts from their graph homes. A sole doorbell and a press aged at most
  60 seconds are required for visitor context; match stored half-open arrival
  windows without identification. Rejected indefinite press lifetime, guessed
  door/bell associations and an extra fixed tolerance around expected_at.
- Completeness comes from per-member presence; stale readings retain the existing
  risk treatment. Explicit absence needs no sleep/zone fields. Room kinds are
  nullable bedroom/other, price bands remain nonempty strings, and irrelevant
  tariff readings do not affect freshness. Rejected a room taxonomy, name
  inference, early tariff band definitions and implicit complete occupancy.
- Replace the CLI's aggregate evidence list with explicit simulated observations,
  room metadata and deterministic scam evidence. A read-only copied snapshot can
  fill missing facts only; no partial observation merges or stored-fact overrides.
  Rejected maintaining aggregate flags by inventing members, presses or metadata.
  Seeds stay unchanged; no runtime metadata mutation path is introduced.

Exact interfaces and fact rules have one specification home:
[`ARCHITECTURE.md` §5.11](../../ARCHITECTURE.md#511-adapters). Operator procedures
and the incompatible CLI evidence-file change are in
[`docs/development.md`](../development.md#adapter-contracts-and-graph-facts-item-12).
Local verification uses disposable databases; no development schema reset,
automatic migration, remote CI run or new threat-model claim is part of item 12.

### Doorbell press bound to approval — 2026-09-21 (author-approved)

Correction to items 9 and 12: the 60-second press window governs autonomous
and initial evaluation. A `security.door_unlock` ASK binds the sole doorbell's
`asset_id`, `last_press_at` and `expected` Boolean in the existing approval binding;
no snapshot image or visitor hint is stored there. Voting and redemption use that
press's visitor classification while re-evaluating live state and the action hash.
A newer press refuses the approval with `DENY_APPROVAL_MISMATCH`; expiry retains
precedence. Approvals without a bound press retain their existing behavior.

Rejected widening the press window to the approval TTL: a second visitor could
ride the first visitor's approval. The fact-hash mechanism is unchanged; the bound
press and its derived fact enter the existing hashed policy facts, as specified in
[architecture §3.4](../../ARCHITECTURE.md#34-internal-pipeline-contract-item-9).
Verification: [doorbell approval correction](../verification-log.md#doorbell-press-bound-to-approval).

## Item 13 models and read adapters amendment — 2026-09-19 (author-approved)

The author approved the following during explicit planning batches:

- Build every listed model and eight read adapters in memory; retain the existing
  registry and canonical observations. Pure hypothetical controls exercise physics;
  every adapter write is unavailable. Rejected pulling execution, graph ingestion,
  persistence, subscriptions, notifications, or scenario YAML parsing forward.
- Use an injected monotonic clock, forward-only jumps, anchored numerical steps
  and intermediate projections. Rejected rewind state storage and background
  ticking. Seed independent streams per household/model/subject/time bucket;
  polling and unrelated members cannot change the simulation.
- Keep calibration knobs explicit, with override → graph → approved-default
  precedence. Rejected invented initial state and silently choosing missing inputs.
  Use float physics, canonical rounded observations and Decimal prices.
- Use loss-accounted EV/battery models, a symmetric split of battery round-trip
  efficiency, constant-power appliance cycles, and duty-limited RC thermal zones.
  Rejected invented appliance waveforms and silently discarding physical losses.
- Use NOAA's small solar-position calculation plus an explicitly synthetic cloud
  approximation; supply weather and all synthetic tariff inputs. Rejected new
  dependencies, live fetches in item 13 and fabricated ComEd rates. Twin prices
  require an in-memory household with the twin rate plan; stored seeds stay intact.
- Use weekly presence with bounded arrival/departure jitter and daily correlated
  recovery scores; require their parameters. Choose the first occurrence of folded
  local times and shift nonexistent times by the DST gap. Rejected implicit guest
  identities and using a wearable score as a medical interpretation.
- Keep contact scripts, inbound calls and expected-visitor hints private to the
  simulation. Expose only redacted verified channels and graph-derived visitor
  context. Bundle an original labeled SVG rather than a third-party stock photo.
- Extend the canonical observation state for cameras, shades and doorbell motion;
  add the energy tariff-state read. Rejected a second observation shape or a Ring
  transport disguised as a twin event input.
- Verify locally, including disposable PostgreSQL regressions and an installed
  wheel. No remote CI push/dispatch, development migration, or new threat-model
  claim. Private helper names, file splits and test-only inputs are implementation
  choices; new behavioral questions still require the author's answer.

The exact model parameters, interfaces and time semantics live in
[`docs/twin-and-scenarios.md` §2.11](../twin-and-scenarios.md#211-item-13-in-memory-contract).
Procedures live in [development](../development.md#twin-models-and-read-adapters-item-13).

## Item 14 credential-free energy amendment — 2026-09-20 (author-approved)

The approved implementation plan fixes these choices:

- One household-bound `energy:real` factory, the existing registry/lifecycle and
  explicit asset bindings. Missing location disables weather only. Reject other
  rate plans/classes, real battery/solar reads and every write; no twin fallback.
  Rejected ingestion, worker polling, database changes and execution in this item.
- Require a tariff-file path and the Residential Single Family Without Electric
  Space Heat class explicitly. Scheduling prices are supply plus the published
  resultant Distribution Facilities Charge, with separate bill items excluded.
  Time-of-Day uses its four distribution periods; Hourly uses standard flat
  distribution. Rejected class inference from assets, base-only distribution,
  fabricated export prices and describing this scheduling basis as a whole bill.
- Approximate billing periods with Chicago calendar months (summer June–September)
  and apply daily periods on weekends and DST. Enforce supply validity; retain
  the delivery vintage from its effective month until replaced, without a live
  validity claim. Rejected applying today's delivery schedule to older history.
  `get_supply_history` supports older supply-only research without that fiction.
- Keep canonical price slots, weather samples and observations. Both real and
  twin reads return series with bounds, explicit gaps and provenance; completeness
  follows coverage. Rejected bare tuples and silently filling missing data.
- Use installed httpx, sequential daily ComEd requests, ten-second request timeouts,
  no automatic retries/cache, and a 366-day request limit. A daily failure fails
  the read; valid null/missing data remain gaps. Keep negative Decimal prices;
  reject malformed/nonfinite/unit-mismatched data and conflicting duplicates.
- The [documented five-minute API](https://hourlypricing.comed.com/hp-api/)
  has inclusive bounds and UTC timestamps. Treat quotes as five-minute intervals,
  not finalized billing. The [first-party price page](https://hourlypricing.comed.com/live-prices/)
  uses `/rrtp/ServletFeed?type=daynexttoday&date=YYYYMMDD`; its `Date.UTC` values
  are chart labels for Chicago hours, as supported by the retained source page
  and DST responses. Parse only that restricted syntax, never JavaScript. Omit
  both ambiguous fall-back 1 a.m. intervals. Rejected interpreting chart labels
  as UTC instants, choosing a fold silently, interpolation and price-kind fallback.
  Historical retrieval proves neither publication time nor no-hindsight planning.
- Use [Open-Meteo hourly forecasts](https://open-meteo.com/en/docs), declared
  coordinates, °F, cloud-cover percent, UTC and the current maximum 16-day window.
  Carry the preceding valid hour to an unaligned start only within that hour;
  missing hours break coverage. Rejected geocoding and archive fallback.
- Keep primary PDFs, hashed raw response fixtures and a recorded-default/live-opt-in
  smoke. Verify the actual August coverage, not an assumed complete month; require
  live reads and installed-wheel checks before closing. No remote CI dispatch or
  new threat-model claim.

Interface details live in [architecture §5.11](../../ARCHITECTURE.md#511-adapters),
rate/time semantics in [twin §2.6](../twin-and-scenarios.md#26-tariff), and commands
in [development](../development.md#credential-free-energy-adapters-item-14).

## Item 15 local HA amendment — 2026-09-20 (author-approved)

The approved implementation plan adds local Home Assistant software while leaving
item 15 partial until the physical energy-monitoring plug gate passes.

- Use the existing household factory map, lifecycle, canonical observations and
  explicit `asset_bindings`. Non-secret YAML declares the HA origin, control
  entities, optional power sensors and trusted real/demo provenance. Read the
  token only from the private local `.env`; move the pinned websockets package to
  runtime and reuse httpx. Rejected credential-bearing configuration, discovery
  that expands the binding allowlist, ingestion and another transport framework.
- Follow [HA WebSocket authentication and subscription acknowledgments](https://developers.home-assistant.io/docs/api/websocket/)
  and [REST service calls](https://developers.home-assistant.io/docs/api/rest/).
  One lazy subscription, ten-second connection/authentication/REST deadlines,
  no reconnect or automatic service retry. Preserve upstream timestamps and
  units, convert W to kW, and use the older combined observation time. Missing
  power must not erase known switch state. Rejected optimistic state writes,
  trusting service-returned state as verification, and raw upstream diagnostics.
- Permit only unscheduled light/switch on/off and single-target climate changes,
  using the existing `Action, Decision` signatures and an injected Pipeline.
  Claim one durable signed execution attempt before dispatch, after checking the
  stored proposal, hash, household, binding and committed grant no older than ten
  seconds. Rejected in-memory replay sets, clearing an uncertain claim, accepting
  proposal-only Decisions, or weakening the pipeline for a smoke test.
- Record service success and direct HA verification separately; keep uncertain
  outcomes unknown and poll for at most ten seconds without resending. Verify
  raw climate readings to 0.000001 °F rather than rounded graph facts. Reject
  unsupported modes/setpoints, extra parameters and contradictory effects.
  Rejected scheduling, retries, notification delivery, twin writes and the full
  executor lifecycle in item 15. Downgrade may not erase attempt evidence.
- `Registry.get_state(asset_id)` permits only an explicit same-household twin
  fallback in scenario mode. Preserve primary bindings and write routing; errors
  in authentication, data or provenance never trigger it. Rejected implicit
  fallback, relaxed ordinary stamping and using twin readings to verify HA writes.
- Approve a narrowly isolated bootstrap for uniquely named disposable smoke/test
  databases: initial HA bindings, explicit synthetic room metadata, and one-time
  input observations before execution. Seeds remain twin-only, no audit rows are
  fabricated, and all device writes including restoration require real grants.
  Verify and retain an audit export before deleting a smoke database; preserve
  the database on failure. Rejected development migrations or changing seed rules.
- Runtime inspection found `climate.ecobee` in `heat_cool`, advertising only a
  ranged target. On 2026-09-20 the author explicitly approved keeping it read-only
  and testing 72 °F on another supported demo climate. Use `climate.heatpump` in
  its existing heat mode. Read units from `/api/config.unit_system.temperature`;
  the [climate contract](https://developers.home-assistant.io/docs/core/entity/climate/)
  distinguishes single targets, ranges and modes. Rejected mode changes, invented
  scalar targets for ecobee and silently rounding an unsupported setpoint.

This is `dogwood-local` enforcement. It does not implement the AWS signer/Link
boundary or earn any additional threat-model row. Physical-device selection and
purchase remain outside this work. Contracts live in [architecture §5.11](../../ARCHITECTURE.md#511-adapters),
procedures in [development](../development.md#home-assistant-adapter-item-15), and
actual checks in [the evidence log](../verification-log.md#item-15--partial-2026-09-20).

### Terminal HA dispatch attempts — 2026-09-21 (author-approved)

A local HA execution attempt whose service request fails hard after
`Pipeline.claim_execution` stays terminal and is never retried on the same action
id. Item 19's executor appends `VERIFY_FAILED` with reason `dispatch_uncertain`
and marks the action failed; the scheduler proposes a fresh `Action` with a new
id through the full pipeline again. Rejected a retry counter on the same action:
it reintroduces the double-actuation ambiguity the single-attempt claim was built
to remove.

## Item 16 observation-stage scenarios — 2026-09-20 (author-approved)

The author approved the following choices individually before implementation:

- Run both complete timelines in memory, with explicit deferrals for services and
  assertions belonging to later items. Reject fabricated tool results, speech,
  approvals, execution and audit events. The item 16 completion gate is observation
  verification; real scripted tool execution, `scenario_runs` persistence, and the
  full demo assertions remain later integration work. Rejected pulling those
  services forward or replacing the timelines with reduced stories.
- Commit explicit all-twin inputs, including a synthetic tariff and supplied
  weather; keep the stored household seeds unchanged. Rejected implicit adapter
  fallback, real feeds/HA bindings, and unreviewed model initialization. The author
  approved the exact fixture values and an explicit Mom arrival at 19:10, which
  is independent of the deferred unlock and the schedule's expected window.
- Record tool-name scripts directly on voice events with the linked demo account
  and surface. Calls remain deferred; no guessed wire arguments or LLM selection.
  Rejected inferring speaker identity or claiming a working MCP host.
- A recorded patch replaces complete rules, names its base and next version, and
  changes only the in-memory scenario policy after the linked owner's preceding
  proposal, schema/compiler/native Dogwood validation, and deterministic preview.
  Rejected a general patch language, unauthenticated production activation, or a
  test bootstrap exception for graph policy writes. It is recorded and simulated,
  never passkey-authenticated; failures retain the previous policy.
- Keep inbound numbers/claims and contact scripts private to the world. The
  simulated reply does not create a VerificationCase, send a check-in, or prove a
  contact authenticated. Rejected copying simulation omniscience into tool input.
- Use exact event jumps for headless/step and paced terminal traces otherwise.
  Step replays and exits before events at its target; no persisted resume or
  terminal session. Relative local times use existing DST semantics, with file
  order for equal timestamps. Reports are redacted JSON and never overwrite files.
- Active checks can pass with individually reported future assertions deferred;
  report only `item16_observations_passed`. Reject vacuous passes for future `never`
  assertions or calling a stopped/unchecked run complete. Unknown inputs fail.
- Verify both CLIs, focused/full Python checks, disposable PostgreSQL regressions,
  installed-wheel execution and final formatting. Replace the scenario CI
  placeholder without pushing or dispatching a run. No development migration,
  physical device action, new dependency or threat-model claim.

The contract lives in [the scenario specification](../twin-and-scenarios.md#31-item-16-runnable-contract).
The committed scenario YAML files are the single home of the approved input
values. Procedures are in [development](../development.md#scenario-runner-item-16).

**Item 16 weather amendment (2026-09-21, author-approved):** Recorded scenarios
keep weather supplied by the twin, derived inline from a cited Open-Meteo archive
fixture for the same Chicago calendar night one year earlier; replay never fetches
weather and retains `twin (supplied weather)` labeling. Live Open-Meteo is reserved
for item 17's backtest and real households. Rejected live forecasts at run time:
a fixed-date scenario cannot replay identically in CI, the video and judging,
and the 16-day forecast window excludes the October scenario at November judging.
No DSL extension or RealEnergy archive fallback is introduced.

## Explicit manual thermostat events — 2026-09-21

Item 18 accepts current, explicit `source: twin` thermostat observations from a
linked submitter in the internal coordinator and disposable smoke. The observation
contract now carries `mode: heat | cool | off` alongside `target_f`; mode requires
a device observation for an HVAC asset. Pipeline versions the observation and its
`manual:device` constraint atomically. The submitter is not claimed to be the
person who touched a thermostat. Real HA/Link detection and scenario event wiring
remain deferred; no raw device-write method or execution bypass was added.

## Durable executor and checkpoint amendment — 2026-09-21

Item 19's local composition root combines `HIRZ_ADAPTERS`, stored explicit bindings,
HA YAML provenance and an explicitly configured twin scenario. Supported writes are
twin HVAC, EV controls, battery dispatch, appliance start and lights, plus the
existing HA lights/switches and single-setpoint climates. HVAC execution accepts
66–76 °F and tighter policy/device restrictions. Unsupported values are rejected;
approved values are never clamped. Security, covers and profiles remain deferred.

The executor uses the existing durable claim for every dispatch. HA verification
reads HA directly, never a Registry fallback. Dispatch success and verified command
state remain separate audit events. Device dispatch and verification each have a
ten-second bound; EV dispatch has thirty seconds. A reversible mismatch or uncertain
attempt can schedule one fresh Action after a direct read confirms the control is
still unmet. The original attempt stays terminal, and the new request goes through
all Pipeline checks without inheriting votes. Appliance starts are not retried.

Twin control effects and checkpoints commit together; checkpoints include physical
state, configuration identity and simulation position with signed hash evidence.
The simulation clock pauses during a sweep and advances between polls; restored
simulation excludes wall-clock downtime. Readings before evaluation and after writes
enter graph history through `governance.record_observations`, attributed to the
initiator/approver on the scheduler surface. Rejected accepted-command-as-success,
HA-to-twin write verification, caller-supplied readings, and local recovery claims
while the database or worker remains offline. Failure notices are durable pending
records, not delivered push/email messages.

## Executable scenarios — 2026-09-22 (author-approved)

Item 22 composes the existing Coordinator, Pipeline, PlanService, refresh worker,
Executor and template Explainer inside a disposable PostgreSQL scenario host.
Structured `{tool, arguments, save_as}` calls are simulation interfaces, not MCP or
authentication. Bare tool names remain deferred. No solver or model runs inside a
scripted call. Hourly retains its planning regression; parents retains observations
and explicit deferred forbidden-action checks. Rejected a second execution engine
and fabricated service/audit results.

The author extends the disposable-test bootstrap exception to this scenario's
seed, supplied room metadata, explicit bindings, rate plan and EV needed-by time.
All later persisted changes and every device write require Pipeline decisions.
Seeded validated v7 is the execution policy; simulated v8 preview stays separate
and produces no activation audit event. Security, trust, Link, authenticated
activation, MCP and UI remain deferred.

Bindings map seed asset slug to `{adapter, entity}`. HA uses its explicit config
for allowlisting and provenance; scenario-only read fallback stays labeled twin.
Writes and verification use the primary adapter. The main evening uses twin
devices, local published ComEd rates and supplied weather, with no live feeds or
Bedrock. A separate current-time, normal-speed HA demo lamp scenario verifies and
restores `light.bed_light` through signed Pipeline execution. The physical-plug
check remains separate.

Private artifacts retain the report, full signed audit and public key. Successful
database deletion requires both database-chain and exported-file verification
against the independently obtained signing-key fingerprint. Failed databases and
available evidence remain. Step/unchecked/deferred checks cannot earn full evening
success. Rejected treating an observation replay or an unverified export as the
item 22 execution gate.


### HA smoke quiet-hours consent — 2026-09-22

The current-time lamp smoke must obey the seeded household's quiet-hours rule.
Extend the existing explicitly declared response mechanism to standalone lamp
requests: retain ASK, record a visible linked-member answer through Pipeline.vote,
and enqueue the unchanged request with the original requester and bound approval.
A rejected or absent answer does not schedule the lamp; the worker still checks
permission before dispatch and owns the preauthorized ending. Planned responses
continue through PlanService. Rejected removing quiet hours, weakening freshness,
forcing daytime for a live adapter, or treating a matching final lamp state as
proof of a toggle. Both ordered VERIFIED rows remain required.

## Household tools amendment — 2026-09-23

The author approved initial, explicitly labeled verified-channel fixtures only for disposable twin database bootstrap. Subsequent verification transitions require Pipeline decisions, and worker-only simulated replies or expiry use existing twin scripts. No real contact delivery is claimed. Full contract and rejected alternatives: [ADR-015](./ADR-015-household-tools.md).

### Profiles/objectives follow-up — 2026-09-23

Explicit household profiles expand only to existing thermostat and light actions. Each action passes Pipeline and worker checks independently; missing observations still fail closed. Startup configuration grants no device authority, and no new adapter or inferred household preset is introduced. Exact contract and rejected alternatives: [ADR-015](./ADR-015-household-tools.md#completion-scope-amendment--2026-09-23-author-approved).
