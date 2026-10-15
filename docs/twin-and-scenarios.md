# Digital Twin and Scenario Engine

The twin is how Hirz demonstrates every capability end to end with no hardware, and how the scenario corpus doubles as the integration test suite. It is a real subsystem with a real interface, labeled honestly in every surface as `twin`. See `ARCHITECTURE.md` §5.11–§5.12 and [ADR-006](./adr/ADR-006-twin-first-adapters.md).

---

## 1. Design rules

1. **Same interface as real.** A twin adapter implements the same `Protocol` as its real counterpart. Core code cannot tell them apart; only the `source` stamp differs.
2. **Physics-lite, not random.** Numbers come from small models with named parameters so they stay plausible and reproducible. A judge who owns an EV should never see a home charger add 28 percent in half an hour.
3. **Seeded and reproducible.** Every scenario run has a seed; the same seed produces the same trace.
4. **Sim clock.** All twin models advance on `SimClock`, which can run at wall speed, at a multiplier, or jump to a timestamp. The scheduler and the planner use the injected clock, never `datetime.now()` directly.
5. **Mixable.** A household can run real Home Assistant devices and a twin EV at the same time. The registry decides per domain, and `asset_bindings` can override per entity, which is how the demo runs one physical smart plug (the living-room light) inside an otherwise twin `devices` domain. Falling back from a real binding to its twin when the device is absent is a **scenario and demo feature only**. In a real household an unreachable device is `unavailable; actual state unknown`, the twin never stands in for it, and a twin read-back never satisfies verify-after-act for a real device.
6. **Real data where it is free.** Open-Meteo weather is a live feed, and electricity prices come from one of two real ComEd rate profiles (§2.6): the published Time-of-Day rate table or the live Hourly Pricing feed. The twin consumes them so the optimizer's numbers are grounded in a real tariff and real weather.

---

Item 12 provides the nine async contracts and registry. Item 13 implements the
in-memory models and eight read adapters (§2.11). Item 14 adds credential-free ComEd/Open-Meteo reads (§2.6); action
execution, observation ingestion and scenario fallback remain later items. New observations require the correct domain
as well as source; member presence and wearable readings occupy separate streams.
The graph locations, legacy-row treatment and exact derivation rules are in
[`ARCHITECTURE.md` §5.11](../ARCHITECTURE.md#511-adapters). `Registry.stamp()` validates
provenance without writing graph state. Never call raw adapter write methods from
scenario setup: production execution still belongs to the pipeline/executor.

## 2. Models

### 2.1 Thermal zone

Discrete RC model per zone, 1-minute internal step:

```
T[t+1] = T[t] + dt/C · ( Q_hvac·u[t] + Q_internal(occupants) + Q_solar(irradiance, orientation) − (T[t] − T_out[t]) / R )
```

Parameters per zone: `C` (kWh/°F thermal mass), `R` (°F/kW envelope resistance), `Q_hvac` (kW heating or cooling), coupling to adjacent zones (a small conductance). Defaults are calibrated so a 2,000 sq ft house pre-warms a living room by 4 °F in about 45 minutes at 3 kW, and drifts about 1 °F/hour at a 30 °F outdoor delta. Every parameter is a knob in the scenario file because the physical world always needs tuning a model can't see.

### 2.2 EV battery

`capacity_kwh` (default 75), `soc`, `charger_kw` (default 7.4 for a Level 2 home charger; 11 optional), charge efficiency 0.92, a taper above 80 percent (power scales linearly to 30 percent of max at 100), and `driving` events that subtract energy. Useful derived facts: 34 → 50 percent at 7.4 kW takes about 1 h 45 min; 34 → 62 percent takes about 3 h 5 min. The demo numbers are computed from this model, never typed by hand.

### 2.3 Home battery

`capacity_kwh` (default 13.5), `power_kw` (5), round-trip efficiency 0.90, reserve floor 10 percent, cycle counter for the planner's throughput penalty.

### 2.4 Solar PV

`kw_peak` (default 6), orientation and tilt, clear-sky irradiance from sun position (latitude/longitude from the household address, computed with a small solar-position routine, no external dependency), scaled by Open-Meteo cloud cover. Output feeds the energy balance and the planner's forecast.

### 2.5 Appliances

Named cycle profiles (`dishwasher`: 105 min, 1.2 kWh, noise level; `laundry`: 60 min, 0.9 kWh; `dryer`: 50 min, 2.5 kWh). A start creates a load trajectory and a completion event.

### 2.6 Tariff

The rate plan is an attribute of the household (`household.rate_plan`), and the planner always receives one all-in price per slot: supply plus delivery, in cents per kWh. Three sources produce that vector behind the same `energy.get_prices` interface:

- **`comed_time_of_day`** (the demo household's plan). ComEd's residential Time-of-Day rate, full supply-plus-delivery version live since 2026-07-23: four fixed daily periods (Morning, Mid-Day Peak 1 PM to 7 PM, Evening, Overnight 9 PM to 6 AM) with summer and non-summer prices. The rates live in `tariffs/comed-time-of-day.yaml`, a small table transcribed from ComEd's published supply-charge information sheet and delivery-charge guide, each row carrying its source URL and effective date. Labeled `real (published ComEd rate)`: a real rate, not a live feed. Period hours and every price are checked against ComEd's own documents when the file is written (`ROADMAP.md` item 14); nothing in this repo types them from memory.
- **`comed_hourly`**. ComEd's Hourly Pricing live feed (day-ahead hourly plus 5-minute real-time, no auth) for supply, with the delivery charge added from the same tariff file. Labeled `real`. The feed serves historical ranges (`datestart`/`dateend`, verified 2026-09-17 back to September 2025), which is what the backtest uses.
- **`twin`**. Time-of-use base with configurable peak windows and stochastic spikes, seeded; day-ahead and real-time series both produced so the planner path is identical to the real feed.

**Implemented scheduling basis (item 14).** Here “all-in” means **supply plus billed
Distribution Facilities Charge**, in Decimal cents/kWh. It is not the whole bill:
IEDT, taxes, capacity, other separate bill line items, and fixed customer/metering
charges are excluded. Preserve the adjustments already present in ComEd's published
resultant distribution charges (IDUF, EDAF, DSPR, RBAF, TPAF and DGRA); do not add them
again or replace the resultant with the base charge. Supply retains its published
uncollectible-cost adjustments. Export prices are null and real energy advertises
no export-price capability.

Only `residential_single_family_without_electric_space_heat` is supported and must
be explicitly selected. Time-of-Day uses period-specific billed distribution;
Hourly Pricing uses the standard flat billed distribution. No asset implies a
customer class. The canonical YAML retains every row's source URL, document effective
date, applicable half-open billing period and verification date, and references the
retained primary PDFs with SHA-256. Supply is valid for June 2026–May 2027 billing
periods. The delivery guide's resultant tables show “June 2026” alongside an older
April heading; the pinned vintage is June 2026 (pages 1–2), applied from that month
until replaced. It is not a live rate check or a guarantee of future bill charges.
Older dates need supply-only history; they must not receive fabricated delivery.
The commercial launch date described above is distinct from the sheets' billing
validity; a pre-launch scenario replay remains a labeled counterfactual.

Billing periods are approximated by calendar months in `America/Chicago`, with
June–September summer. Daily periods, including weekends, are 06:00–13:00 morning,
13:00–19:00 mid-day peak, 19:00–21:00 evening, and 21:00–06:00 overnight. Apply local
DST using UTC traversal, so spring and fall days have 23 and 25 hours. Requests are
aware, half-open, limited to 366 elapsed days, and clipped to exact requested bounds.
`day_ahead` uses hourly slots; `realtime` uses five-minute slots, including for the
static tariff. No interpolation or switching between price kinds is permitted.

**Feed interpretation.** ComEd's [five-minute API](https://hourlypricing.comed.com/hp-api/)
uses inclusive local request bounds and returned UTC millisecond timestamps. Fetch
each Chicago calendar day sequentially, including its next-midnight endpoint; collapse
identical duplicates and filter coverage in UTC. Each quote covers its timestamp
through five minutes later. These are quoted supply prices, not the finalized hourly
billing series. Negative values remain negative after the explicit distribution sum.
The [first-party chart](https://hourlypricing.comed.com/live-prices/) requests
`/rrtp/ServletFeed?type=daynexttoday&date=YYYYMMDD`; its restricted `Date.UTC(...)`
array encodes Chicago wall-clock labels, despite its name. Retained spring/fall
fixtures and page source support this interpretation, not an upstream guarantee.
Never evaluate the response as JavaScript. A fall-back 1 a.m. label cannot distinguish
the two occurrences: omit both and report the ambiguity. Historical day-ahead data
has unknown publication time and does not establish no-hindsight planning.
Missing/null/unpublished prices are gaps; conflicts, malformed arrays, nonfinite
numbers, invalid units or a failed daily request make the entire read unavailable.

**Weather.** [Open-Meteo](https://open-meteo.com/en/docs) receives the household's
coordinates directly, `hourly=temperature_2m,cloud_cover`, `temperature_unit=fahrenheit`,
`timezone=UTC`, and `forecast_days=16`. The supported window is current UTC midnight
through midnight 16 days later; no geocoding or archive fallback. Missing coordinates
remove weather capability without disabling prices. A valid hourly sample covers
only its hour; for an unaligned start, repeat that hour's value at the requested
boundary. Missing hours remain gaps, with no carry across them. Twin supplied weather
retains its declared hold-until-next-sample semantics and uses the same series shape.
All requests use a ten-second httpx timeout without automatic caching or retries.

### 2.7 Occupancy and presence

Members have weekly schedules with arrival/departure noise; scenario events override (early arrival, guests). Sleep state per member from a bedtime window and a zone. `who_is_home` and `sleeping_in(zone)` are derived facts the pipeline and the constitution read.

### 2.8 Wearable recovery

A daily recovery score series per member with autocorrelation and scenario overrides ("low recovery Tuesday"). Shaped like Oura's readiness / Whoop's recovery so the real adapters map onto the same field.

### 2.9 Devices: locks, cameras, lights, shades, doorbell

State machines with realistic latencies (lock 1.5 s, camera arm 0.5 s) and failure injection hooks (`fail_next: unlock`). Doorbell presses carry a stock snapshot image and an optional `expected_visitor` hint the scenario provides; motion events carry a classification (`human`, `animal`, `vehicle`) shaped like Ring's; `device.fail` on the doorbell produces the offline event that raises `state_stale` for `security.door_unlock`. Hirz never identifies people from images, so the twin doesn't either.

### 2.10 Contacts and calls

A scenario can inject an inbound-call event with a presented number and a transcript summary. That event is the state of the world, not something Hirz knows: Hirz cannot see a call, and it learns only what the member then says to Alexa. If the member does not read the number out, no tool output may say anything about the number, and the scenario asserts that. A scenario can also script the trusted contact's response to a check-in (`genuine`, `not_genuine`, no answer, delay). The contact may live in another Hirz household: in the demo, Malik is a trusted contact of his parents' household and answers from his own app.

---

### 2.11 Item 13 in-memory contract

`hirz/twin/` contains pure model transitions and `TwinWorld`; each implemented
adapter lives in its existing domain's `twin/` package. `TwinConfig` requires an
aware start/end, seed, base electrical load, weather, tariff, model dictionaries,
weekly schedules, overrides, couplings and private call/contact scripts. Empty
collections are explicit. Asset/member keys are canonical UUIDs; adapter reads
continue to use existing entity strings or member/contact UUIDs. Configuration
is supplied as typed Python models; scenario YAML loading remains item 16.

`TwinWorld` receives canonical household, member, asset, binding, contact,
redacted-channel and calendar records plus the config and `SimClock`. It validates
household membership and model/asset kinds. Every twin-bound asset needs its model;
every member needs presence, weekly schedules and recovery inputs. Configuration
values explicitly supplied by the caller override graph physical parameters,
which override the approved defaults below. Missing nondefault inputs fail.
Numbers must be finite and meet their declared bounds.

**Clock and advancement.** `SimClock(start, speed, timer=monotonic)` is callable
and exposes `now()`, `set_speed()` and `jump()`. Zero pauses; positive speed scales
elapsed monotonic time. Backward jumps and negative/nonfinite speeds fail.
`TwinWorld.advance_to(at)` advances models without changing the clock; `read()`
uses the injected clock. The caller must keep both consistent. Nothing runs in a
background thread. Minute boundaries are anchored to simulation start, with extra
boundaries for weather changes, schedules, overrides, midnight, appliance/device
completion and storage limits. Intermediate reads project from the last committed
boundary, so polling does not insert extra integration steps. Rewinds require a
new world. Reads and queries outside the configured horizon fail; endpoint state
reads are allowed at the horizon end.

Scheduled transitions precede supplied overrides at the same instant; overrides
retain their supplied order. Recovery updates at local midnight. A SHA-256-derived
stdlib random stream is keyed by seed, household, model, subject and time bucket;
reading or adding another subject never consumes an existing subject's randomness.
Local schedules use the first folded time; nonexistent times shift forward by the
DST gap. Colliding scheduled transitions affecting the same state are rejected.

**Physical models.** Pure `advance` methods return new states; they do not issue
`Action`s or create `Decision`s. Hypothetical control inputs and accumulated energy
are simulation data, never authority to execute a device command.

| Model | Parameters and behavior |
|---|---|
| Thermal | Defaults: mass 0.46875 kWh/°F, resistance 64 °F/kW, HVAC thermal output 3 kW, occupant gain 0.1 kW/person, COP 1; mode, target, initial temperature and solar-gain area (including explicit zero) are required. Symmetric explicit zone links default to 0.01 kW/°F. Reject configurations unstable at one minute. Duty limits heat/cooling to the target; electricity equals absolute delivered heat divided by COP. Horizontal irradiance supplies solar gain. |
| EV | Defaults from §2.2; require initial SoC, plugged-in/charging flags and charge limit. Integrate the linear taper analytically; cap exactly at the limit. Account separately for input, stored energy, losses and driving. An unplugged EV draws no charging power; driving requires unplugged state and sufficient energy. |
| Battery | Defaults from §2.3; require initial SoC and signed dispatch. Each direction has efficiency sqrt(0.90). Positive dispatch discharges; negative charges. Saturate at power/energy limits. Initial SoC below reserve is valid but cannot discharge. Equivalent cycles = absolute stored-energy throughput / twice capacity. |
| PV | Require location, tilt and orientation; default peak 6 kW. Use [NOAA fractional-year solar equations](https://gml.noaa.gov/grad/solcalc/solareqns.PDF) for the sun vector. Power = peak × positive panel/sun dot product × (1 − coefficient × cloud fraction), zero below the horizon. Cloud coefficient defaults to 0.8; this is a synthetic direct-beam approximation, not a NOAA yield model. |
| Appliances | `PROFILES` contains the three named durations/energies from §2.5. Require profile parameters, running state and noise in dBA. Use constant power, complete once at the exact end, and reject a second start while running. |

Require base electrical load explicitly. Sum it with EV, HVAC and appliance
consumption, battery input/output and PV production to derive grid import/export.
Energy accounting uses unrounded model values; graph observations retain the
existing four-decimal policy-number representation. No savings are published by
this item. Conservation tolerance is 1e-8 kWh absolute plus 1e-9 relative.
The calibration check uses 70 °F inside, 40 °F outside, no occupant/solar/coupling
gains: 3.8–4.2 °F warming in 45 minutes at 3 kW and 0.9–1.1 °F drift in an hour
without HVAC. The EV check accepts 100–110 minutes for 34→50%.

**Weather and tariff.** Supplied weather begins at its declared coverage start;
timestamps must be strictly ordered within that coverage. Values hold until the
next sample (the final sample through coverage end); no extrapolation or fetches.
A synthetic tariff requires `household.rate_plan=twin`, using an in-memory copy
when necessary. In mixed households the twin factory permits that explicit
rate-plan-only difference and requires every other household field to match.
Require contiguous daily local-time periods covering 00:00–24:00,
Decimal import prices, band names, slot minutes, spike probability and nonnegative
spike range. Negative base prices are valid. Slots are anchored to simulation
start; their base rate is selected at slot start in household local time. Queries
clip the boundary slots. Day-ahead uses base prices; real-time adds seeded uniform
per-slot spikes quantized to four decimal cents/kWh. Optional export prices do not
receive spikes. Advertise `has_export_price` only when every period supplies one.

**People and devices.** Presence requires explicit initial present/sleeping/zone
state, weekly transitions and arrival/departure jitter (uniform integer ±minutes).
Sleep requires a zone; guests are supplied household members. Overrides last until
the next scheduled change affecting that state. Recovery requires initial score,
mean, rho and noise standard deviation: daily score is rounded and clamped to
0–100 after `mean + rho * (previous - mean) + Gaussian noise`; an override feeds the
following day. None of these values are medical interpretations.

Lock transitions take 1.5 seconds and camera arm takes 0.5 seconds; other device
delays are explicit. Device initial availability/state is required. Reject
concurrent pending transitions; `fail_next` consumes one matching transition and
leaves state unchanged. Offline reads contain only `available=false`; actual
state is unknown. Hypothetical pending transitions can be supplied as initial
world state; no adapter write can create one in item 13.

**Read contracts.** Eight adapters implement polling reads: devices, EV, energy,
presence, wearable, calendar, contacts and doorbell. Async lifecycle uses the
existing registry. Omitted configuration remains unavailable; there is no implicit
fallback. All action-write methods and `subscribe()` raise `AdapterUnavailable`
and are absent from advertised capabilities. `energy.get_tariff_state()` returns
the canonical household-subject price-band observation. Observation IDs use UUID5
of household/start/seed/domain/subject; every observation is `source=twin`, with
scope validation and compatibility with `Registry.stamp()`.

Canonical `ObservationState` adds nullable `camera_armed`, bounded
`cover_position_percent`, `motion_classification` (human/animal/vehicle) and
`last_motion_at`; the last two must occur together. Camera/shade fields require
the matching device asset; motion requires a doorbell and a nonfuture timestamp.
Appliances use existing `on`. Calendar queries select overlapping intervals;
expected arrivals additionally filter `kind=arrival`. Channel reads return only
redacted records verified by simulated now. Unknown subjects fail.

The doorbell accepts strict JSON world inputs with `kind` (press/motion/online/
offline), `entity_id`, aware `at` equal to the current simulated instant, and
`classification` only for motion. Headers must be empty. Pause the clock when
injecting exact-time events. Press/motion fail while offline. This API is not a
Ring endpoint. Snapshot returns the packaged original labeled SVG, or null while
offline; live-view is null. Expected-visitor hints remain private simulation state
and never override graph-derived arrival context.

Contact scripts specify request/deadline and optional reply time for genuine,
not_genuine, will_call or no_answer. They expose model status only: no communication
is sent and no verification case changes. Inbound numbers/transcript summaries
remain private world data and never enter adapter outputs. Model events and energy
counters are separate from the audit ledger. Persistence, execution, subscriptions,
notification transport and the scenario runner remain later roadmap work.

---

## 3. Scenario DSL

The committed YAML files are the executable specification. Each scenario describes
one household; scripts call internal services with explicit linked-account
provenance. No model selects tools or makes decisions in these runs.

| Scenario | Required local evidence |
|---|---|
| [Evening](../scenarios/demo-evening.yaml) | Authenticated seed v7; recorded voice proposal and passkey activation of persisted v8; plans, revisions and explicit consent; v8 unexpected-unlock denial; lamp verification; vehicle motion; expected-window ASK, exact phone approval, ten-minute twin unlock and local relock; Dad's linked-account constraint; overnight physics and consent invariants |
| [Parents scam](../scenarios/parents-scam-check.yaml) | Persisted CRITICAL case without an inferred caller number; explicitly simulated verified-channel check-in and not-genuine reply; result spoken on Mom's subsequent request; separately authorized courier warnings; no finance grant or unlock |
| [No answer](../scenarios/parents-scam-no-answer.yaml) | Persisted pending case before its deadline, worker expiry, and subsequent advice not to send anything and to call the contact saved in the member's phone |
| [Ordinary request](../scenarios/parents-ordinary-request.yaml) | “Malik wants to know when dinner is”; persisted LOW assessment, no scam warning, contact checking still offered |
| [Stranger in window](../scenarios/stranger-in-window.yaml) | Evening's committed initial inputs and 17:31/17:32 rule change, without energy planning; ten-minute request at 19:04, exact request denied by passkey at 19:05, no unlock through completion |

The approval inbox supplies “Mom is expected now. Hirz does not identify the
visitor.” The existing companion screen prefixes “Someone is at the front door.”
A schedule is context, never identification. The headless runner checks the
actual authenticated inbox; existing browser regressions cover its rendering.

Canonical audit selectors use `CONSTITUTION_PROPOSED`, `CONSTITUTION_ACTIVATED`,
`PLAN_CREATED`, `PLAN_REVISED`, `PLAN_APPROVED`, `DENY_CONSTITUTION`,
`ASK_CONSTITUTION`, `APPROVED`, `REJECTED` and `VERIFIED`. A bounded lock ending
retains the `security.door_unlock` class with inverse `locked: true`; there is no
`security.door_lock` class. Check-in transitions are persisted VerificationCases,
not fabricated device `VERIFIED` events. The old illustrative audit sketches and
provisional $1–$8 / 5 kWh thresholds have been removed. The evening YAML retains
its previously verified initial forecast ranges and overnight invariants; inputs
are not tuned to make the narrative more favorable. Revisions are separate
remaining-horizon forecasts and cannot be added together.

**Approved scope:** local twin unlock/relock. Link replay rejection and relocking
operated independently of the cloud remain item 38a. The evening retains that
explicit deferral and emits no `LINK_REJECTED` evidence. Hourly retains the existing
observation/planning contract, with no full-sequence claim. The separate HA lamp
smoke continues to verify and restore its actual demo binding at normal speed.

### Full local sequence contract (item 35)

`execution.full_sequence: true` requires structured executable scripts. Added
calls use the existing flat `ProposalInput` and `ActionInput`; existing lamp and
planning script shapes are unchanged. Every `save_as` name is unique within the
run. Activation requires `proposal: $rule` alongside `member` and `patch`;
`app.approve` and `app.deny` require `request: $unlock` and `member`. Missing,
forward, unresolved and wrong-kind references fail before bootstrap. There is no
“latest request” inference.

The disposable host uses the shared Python software authenticator and actual
companion HTTP endpoints over httpx ASGI transport. It enrolls through invitations,
keeps server-issued cookies, sends Origin/CSRF, reviews drafts and signs activation
and approval ceremonies. Authentication expires on wall time; household execution
uses scenario time. Seed activation preserves its version. Recorded patches go
through proposal/draft/review/activation services; execution reloads persisted
policy and requires active policy thereafter. Approval ceremonies bind the saved
action, its approval ID and content hash. These are local software-passkey tests,
not physical-phone acceptance or an authentication bypass.

`assert.checks` adds `result`, `action` and `approval`, each with `subject: $name`.
`equals` selects dotted fields of the captured canonical tool result, persisted
action row, or captured authenticated inbox (`approval` and `door`). Result wording
checks use `wording_contains` / `wording_excludes` string lists. Policy checks read
the stored active policy. Existing observations, persisted verification checks,
audit selectors and numeric tolerances remain supported.

`full_sequence_passed` requires every timeline event and tool, every reached
assertion and signed-export verification. Unchecked runs, omitted work and
unapproved deferrals fail; deliberate `step` runs remain `stopped`. Reports retain
setup authentication, canonical results, inbox context, signed audit artifacts and
the approved Link limitation. Successful export verification precedes disposable
database cleanup; failures retain the database and available private evidence.
No development migration, new endpoint, dependency or real contact delivery is
part of this contract.

### 3.1 Item 16 runnable contract

`hirz.twin.scenario.LoadedScenario(path)` validates one strict YAML document and
loads its seed, recorded patches, canonical graph records and explicit `TwinConfig`
into an isolated `TwinWorld`. `run_scenario(...)` is async and returns a JSON-ready
run report. These are simulation interfaces, not new Action/Decision/AuditEvent
shapes or execution authority. There is no database, signing key, LLM, external
feed or device credential. Native Dogwood is required for simulated activation.
Scenario weather is supplied inline, derived from a cited [archive fixture](../scenarios/fixtures/manifest.json), and never fetched during replay.

Top-level fields are `id`, `seed`, `household`, `clock` (`start`, `end`, `speed`),
`rate_plan: twin`, explicit `adapters`, `initial`, `timeline`, and `assert`.
Household and patch paths resolve relative to the scenario file. Member, contact
and asset references use seed slugs and resolve only within that household.
`initial` uses the existing TwinConfig fields except start/end/seed, which come
from the scenario. Its model dictionaries use seed slugs instead of UUIDs;
zone references are resolved the same way. Required empty collections are
explicit. Overrides, inbound calls and contact scripts are supplied through the
timeline; their initial collections must be empty. Existing documented physical
parameter precedence still applies. Approved concrete values live only in the
committed fixtures, never in implicit loader defaults.

Times are quoted `HH:MM` or `+Nd HH:MM`, relative to the starting local date,
inside the inclusive configured horizon. Events must be nondecreasing; ties keep
file order. Existing folded/gap DST semantics apply. Physics advances to an event
before that event changes the world. A world mutation commits an event boundary;
ordinary reads remain projections and do not perturb integration. A clock at zero
is used internally for exact event injection, independently of terminal pacing.

Implemented events are presence arrive/leave/sleep/wake (member, optional zone;
sleep requires zone), wearable recovery (member, score), doorbell press/motion
(explicit entity, classification for motion), private inbound call and contact
reply, voice scripts, and simulated constitution activation. Doorbell visitor
hints remain private and cannot establish presence or identity. A call has
`presented_number` and `claim`; a contact reply has `contact`, `reply`,
`requested_at`, and `deadline`, with its event time as the reply time. Only one
check-in model per contact is supported; a no-answer event occurs at its deadline.
These are private, time-indexed model inputs, never communication or verification
case mutations by themselves. The service-backed parents runner consumes them through the existing check-in service, then correlates the persisted twin press through the shared courier worker.

Observation-stage voice events require `member`, `text` and a nonempty `script` of known tool names.
Structured internal execution calls are defined in the item 22 contract below.
The member names a linked demo account, never an identified speaker. Scripts
produce deferred tool entries without tool arguments, consumer speech or results.
The supported vocabulary's remaining events require `deferred` and may carry an
inert `payload` mapping and linked `member`. Unknown event names or unexpected
fields fail. Deferred payloads are not executed or exported.

A `constitution.activate` event names the linked owner and `patch`. The patch has
`base_version`, `version` and full replacement rules under `autonomy`; it does not
merge fields within a rule. A preceding proposal script from that same owner,
exact base version and a one-version increment are required. The candidate must
pass the existing constitution schema, compiler and native Dogwood validation;
the existing preview derives situation lines. Only then is the in-memory policy
swapped. Failure leaves the previous policy intact. The report labels this
recorded/simulated, `authenticated: false`, and `dogwood-local`. No audit row or
production authentication/activation is implied.

`assert.checks` contains `{at, kind, equals}` entries. Observation checks add
`domain` and `subject` (seed slug or `household`); `equals` selects canonical
ObservationState fields, normalized through the existing model. Policy checks
compare `version`; private call checks compare `count`; private contact checks
name a contact subject and compare model `status`. All checks at a timestamp run
after all events at that timestamp. Observation subjects and sources are checked
explicitly, so a household tariff cannot match a battery's household ID.
`assert.deferred` entries contain an `expectation` and `reason`; future ordered
audit occurrences and `never` expectations remain individually visible rather
than passing without an executor. Future numeric expectations are provisional
assertions, not calculated or published savings.

Reports contain input SHA-256 hashes, seed, simulated start/end, explicit adapter
mix, indexed event statuses, canonical observation snapshots, policy version and
preview, indexed assertion statuses and deferrals. Raw voice/call text, inbound
numbers, private channel values/hashes and deferred payloads are withheld.
Contact assertions expose their check result, not private script contents.
Reports are not audit exports; there is no invented audit range or signature.

---

## 4. Running scenarios

```
hirz scenario run scenarios/demo-evening.yaml --speed 60            # paced terminal trace
hirz scenario run scenarios/demo-evening.yaml --headless --assert   # internal service execution and overnight assertions
hirz scenario step scenarios/demo-evening.yaml --to "18:40"         # pause before the unexpected visitor for recording
```

Item 16 exports an in-memory run report with `--output NEW_FILE`, refusing overwrite.
Item 22 execution additionally retains a signed audit export and private artifacts;
no `scenario_runs` table is introduced.
See [development](./development.md#scenario-runner-item-16) for exit codes, step
boundaries, validator setup and verification commands.

**Numbers are derived, never typed.** The evening's initial forecast assertions come from its retained signed plan record; revisions have separate remaining-horizon forecasts. Annual figures come from the historical backtest and its retained inputs in `scripts/`, never from adding revisions or annualizing the scenario. A reproducible number can still be a weak comparison, so the saving is measured against a timer schedule a careful household already uses, with "do everything now" and the cheapest-slots heuristic beside it, all held to the same comfort, the same energy into the car, and a battery that ends no emptier than it began. On Hourly Pricing the backtest plans from what was knowable at the time and is billed at realized prices; state carries between days; it reports a distribution, including the days on which Hirz adds little, for a home with solar, battery, and car, a home with a car only, and a home with no car; and the Time-of-Day replay before 2026-07-23 is labeled a counterfactual simulation (`ARCHITECTURE.md` §5.4). The scorecard leads with dollars (tonight, then annualized from the backtest); `peak_kwh_avoided` comes second. The `tariff.spike` event remains a twin-only test of the planner under a price spike and is never used to inflate a demo number.

---

## 5. Labeling

Twin observation outputs used as numeric policy facts are quantized to four decimal places on write by graph validation, the same as real observations.

Every observation carries `source`, one of three values. `real`: a live feed or a physical device (Open-Meteo, the ComEd hourly feed, the smart plug through Home Assistant, Smartcar, Ring sandbox events). `real API, demo devices`: Home Assistant's demo integration, a real API over simulated entities, never shown as plain `real`. `twin`: Hirz's own models. A published rate table is `real (published ComEd rate)`: real prices, not a live feed.

Cards show two visual states so a judge or a household can read them at a glance (`docs/design.md`): **live** (`real`) and **simulated** (`twin` and `real API, demo devices`, the more conservative reading). The full three-way source stays on every observation in the data, in the companion app's detail view, in the audit trail, and in the MCP `get_household_context` output (`data.sources`). The demo video shows the badges; honesty here is a scoring asset, not a liability.

**Public demo households are simulated only.** A household created by the hosted demo's "Start demo" button (`ARCHITECTURE.md` §5.14) can bind only `twin` adapters; the registry refuses any real binding for it, and a test asserts that.

### Item 17 read-only planning snapshots (2026-09-21)

`planning` is an optional array of `{at, member, ev_target, expected_savings,
expected_peak}`. Each snapshot uses the current simulated physical state, the
linked member account, explicit supplied weather, and a horizon ending at the
next Chicago 17:30. The two demo snapshots are 17:33 (80%) and 17:35 (50%), due
08:00. The 22:40 kitchen request is absent from both inputs. These are hypothetical
proposals; the observation world's EV remains uncharged and tool execution,
approvals, audit rows and device actions remain deferred. The report has a
separate `planning` section with canonical proposals, actions, solver status,
comparison validity and assertions. Wall-clock timings are omitted here to keep
scenario reports deterministic; the planner smoke records them.

`energy: real` is allowed only for the rate input; physical assets still use twin
bindings and supplied weather remains simulated. The Time-of-Day scenario checks
production tariff validity and labels prices `real (published ComEd rate)`.
`demo-evening-hourly.yaml` uses the 2025-10-13–14 counterpart and a pinned-2026-tariff
counterfactual with the lagged persistence supply forecast. Its explicit
`schedule_date_shift_days: -365` remaps seed schedule events. Both start the living
room at 70°F, and planning weather extends to the next 17:30 from the same retained
48-hour fixture. Successful planning/observation reports use
`item17_planning_and_observations_passed`; the parents scenario retains its item 16
observation status. This status does not assert that the year-long study passed.

The snapshot's expected savings and peak values are derived from retained
`../scripts/backtest-data/demo-evening*.json` reports. They replace the provisional
planning-only assertions. The Time-of-Day execution assertions now use the item 22 signed scenario run; historical figures remain unchanged.

Historical replay keeps the same once-daily proposals but applies the shared
causal simulation controls specified in the [ADR-005 amendment](./adr/ADR-005-deterministic-planner.md#causal-historical-replay-amendment--2026-09-21).
These controls are internal hypothetical transitions, not scenario events or
executed Actions. Scenario forecast comparisons retain strict schedule replay;
the baseline thermostat now prepares far enough ahead for its declared occupied
target using the existing physical power limit. Supplied scenario weather,
linked-account provenance, observations and execution deferrals remain intact.


### Item 18 manual-event boundary

Twin HVAC observations now include `mode: heat | cool | off` together with
`target_f`. `scripts/smoke_coordinator.py` submits explicit current twin thermostat
events through a linked account and Pipeline, recording both the observation and
its two-hour `manual:device` hold atomically. The account is a submitter, not an
identified physical actor. The planner retains target and mode, meters the held
thermal behavior in every comparison, and emits no thermostat Action during the
hold. Automatic HA/Link detection and `device.manual_change` scenario DSL wiring
remain later work; item 18 does not make that future scenario event executable.

### Item 22 executable contract

`execution:` opts into an isolated PostgreSQL run using existing internal services.
The main evening's committed YAML is the executable input. Hourly and parents keep
their earlier scoped contracts. See the [approved decisions](./adr/ADR-006-twin-first-adapters.md#executable-scenarios--2026-09-22-author-approved).

`execution` supplies a linked `member`, optional `plan_at`, `ev_target`,
`ev_needed_by`, explicit seed-asset `rooms` (`bedroom` or `other`) and `responses`.
Each response names a start/end, linked member, surface, action class, asset and
Boolean answer. Each matching pending approval receives one visible simulated
turn; unmatched or unresolved work cannot pass the overnight gate. Standalone
lamp requests may remain pending for a declared `environment.lights` response.
An affirmative response records a Pipeline vote and re-enqueues the unchanged
request with its original linked requester and approval id; the worker still
re-evaluates it before acting. The HA smoke declares this response explicitly
so quiet hours can require consent without aborting the test.

A structured script call uses `{tool, arguments, save_as}`. Supported internal
calls are plan/context reads, constraint intake (`text`, optional `replaces`),
plan consent (`plan`, `approved`), and a lamp request (`asset`, `on`, optional
`duration_s`). Arguments are flat and validated per call. `$name` resolves a
previous saved identifier within this run; `current` selects the current plan.
`initial_target` identifies the explicit initial EV target. Bare tool names remain
individually deferred. The host does not implement the public tool catalog.

`bindings` maps seed asset slugs to `{adapter: twin | ha, entity: ...}`. HA requires
`--ha-config`, current time and normal wall-clock pacing. The primary adapter
verifies its own writes; fallback observations never verify an HA outcome.

`assert.audit_sequence_includes` consumes distinct ordered signed rows, with
optional `EVENT:class` selectors resolved through canonical Actions. `never`
uses the same selectors (including domain wildcards). `plan_summary` maps initial
forecast fields to `{min, max}`; it never accumulates savings across revisions.
`ev_soc_at` maps scenario times to `{min, max}` and uses the existing numeric
tolerance. Reports distinguish passed, failed, deferred, unchecked and not-reached.
Only the complete evening execution and overnight outcomes earn the item 22 gate.

Physics advances before service work. Required endings precede timeline entries;
file order is preserved at equal timestamps. Current observations precede
planning/refresh and openings; declared responses precede checks. Writes retain
monotonic microsecond ordering; refresh runs immediately after each tick, and
fractional bounded durations preserve exact ending times. Pacing changes wall
waiting only. Step mode exits before target-time timeline entries. At 07:00 the
run reports the overnight outcome without creating tomorrow's plan.

`--artifacts-dir NEW_DIR` defaults to `secrets/scenario-runs/<scenario>-<unique>/`.
The directory is private (`0700`); report, audit and PEM files are exclusive-created
(`0600`). `--output` retains its existing exclusive-create behavior. A successful
run verifies the full chain and exported file against the signing key's public
fingerprint before deleting the disposable database. Failure retains its database
and available evidence. No development migration is performed.

## Service-backed parents scenario (item 33a)

`parents-scam-check.yaml` declares an execution member and explicit
`verified_app_fixtures`. Its structured calls use canonical assessment/check-in
inputs; `confirmed: true` represents the scripted member's explicit check-in
confirmation, never courier permission. All subsequent records require Pipeline
grants. `kind: verification` checks the persisted case, reply, warning publication,
source and honest wording. The audit assertions require both warning executions
and forbid finance execution and unlocks. Signed private exports use the same
runner as the evening scenario. The legacy observation-only runner regression
fixture lives in `tests/fixtures/parents-observations.yaml`.
