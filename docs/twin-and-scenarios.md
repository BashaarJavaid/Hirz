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
in-memory models and eight read adapters (§2.11). Production transports, action
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
when necessary. Require contiguous daily local-time periods covering 00:00–24:00,
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

The item 6 seed files use two YAML documents (graph, then unvalidated constitution).
They bind every initial asset to `twin` and contain no observations; a scenario
must supply its `initial` state and adapter overrides when item 16 implements the
runner. The seeded arrival window is schedule context only and never evidence of
visitor identity. Loader details are in [development procedures](./development.md).


Two scenarios carry the demo. They are separate files on purpose: a scenario describes one household, and the DSL is not extended to span two.

**`scenarios/parents-scam-check.yaml`** (the cold open, Mom and Dad's home):

```yaml
id: parents-scam-check
seed: 20261013
household: constitutions/quinn-parents.yaml          # Mom (owner), Dad (adult); Malik is a trusted contact with a verified Hirz-app channel
clock: {start: "2026-10-13T17:00:00-05:00", speed: 60}
adapters: {devices: twin, energy: twin, calendar: twin, doorbell: twin, contacts: twin}
timeline:
  - at: "17:04"   ; event: call.inbound           ; presented_number: "+1 312 555 0199" ; claim: "Malik in trouble, needs five hundred dollars"
  - at: "17:05"   ; event: voice                  ; member: mom ; text: "Malik just called from a strange number. He says he's in trouble and needs five hundred dollars. Is it really him?"
  - at: "17:06"   ; event: contact.checkin_reply  ; contact: malik ; reply: not_genuine   # the check-in asked about the specific request: another number, $500
  - at: "17:07"   ; event: voice                  ; member: mom ; text: "Alexa, is it him?"           # Alexa cannot speak unprompted; the card and Mom's phone already show the answer
  - at: "17:25"   ; event: doorbell.press         ; expected_visitor: null      # courier-pickup pattern: unexpected visitor while a CRITICAL case is recent
assert:
  audit_sequence_includes:
    - VERIFY                                       # assess_request_risk lands CRITICAL; a VerificationCase opens
    - VERIFIED                                     # Malik's own app: not_genuine
    - EXECUTED:communication.contact_trusted_contact   # courier correlation: warn Mom, notify the contact Hirz verified
  verification: {band: critical, presented_number: not_provided, status: not_genuine}
  speakable_never_mentions: [number_match]          # Mom never read the number out, so Hirz says nothing about it
  never:
    - EXECUTE:finance.*
    - EXECUTE:security.door_unlock
```

Three short corpus scenarios sit beside it and are asserted the same way. **`scenarios/parents-scam-no-answer.yaml`**: the same call, Malik never replies, the case ends `no_answer`, and Alexa says not to send anything and to call the saved number. **`scenarios/parents-ordinary-request.yaml`**: "Dad wants to know when dinner is" lands LOW with no warning, and checking with Dad is still offered. **`scenarios/stranger-in-window.yaml`** (Malik's home): a stranger rings at 19:04 inside Mom's expected window; the approval reads "Someone is at the front door. Mom is expected now.", Malik denies it on his phone, and the assertions are `ASK_CONSTITUTION:security.door_unlock`, `REJECTED`, and never `EXECUTED:security.door_unlock`.

**`scenarios/demo-evening.yaml`** (Malik's home):

```yaml
id: demo-evening
seed: 20261013
household: constitutions/quinn-home.yaml            # household graph + constitution seed; starts at v7 WITHOUT never_for: [unexpected_visitor]
clock: {start: "2026-10-13T17:30:00-05:00", speed: 60}
adapters: {devices: twin, ev: twin, energy: real, wearable: twin, calendar: twin, doorbell: twin, contacts: twin}
rate_plan: comed_time_of_day                          # published ComEd rate table; a second corpus scenario runs the same evening on comed_hourly
bindings: {light.living_room: ha, lock.front_door: ha}  # one physical smart plug, and Home Assistant's demo lock (`real API, demo devices`, shown as simulated) so the unlock rides the signed-command path in AWS mode; both fall back to twin if absent (scenario mode only)
initial:
  ev: {soc: 0.34, plugged_in: true}
  battery: {soc: 0.55}
  zones: {living_room: {temp_f: 68}, guest_room: {temp_f: 67}}
  presence: {home: [malik], sleeping: []}
timeline:
  - at: "17:30"   ; event: presence.arrive        ; member: malik ; note: "earlier than usual"
  - at: "17:31"   ; event: voice                  ; member: malik ; text: "From now on, never unlock the door for someone we're not expecting."
  - at: "17:32"   ; event: constitution.activate  ; member: malik ; patch: fixtures/patch-never-unexpected-visitor.yaml   # passkey activation in the app; the recorded patch is what HIRZ_LLM=off uses in place of the drafted one, labeled as recorded
  - at: "17:33"   ; event: voice                  ; member: malik ; text: "What's going on tonight?"
  - at: "17:35"   ; event: voice                  ; member: malik ; text: "Don't charge the car past 50. I'm not driving tomorrow."   # the constraint is confirmed at once; the plan is `refreshing` and cannot be approved yet
  - at: "17:36"   ; event: voice                  ; member: malik ; text: "Do it."                           # approves the revised plan, after it landed
  - at: "18:40"   ; event: doorbell.press         ; expected_visitor: null
  - at: "18:40"   ; event: voice                  ; member: malik ; text: "Let them in."                     # DENY_CONSTITUTION under the rule activated at 17:32
  - at: "18:58"   ; event: doorbell.motion        ; classification: vehicle
  - at: "19:04"   ; event: doorbell.press         ; expected_visitor: mom
  - at: "19:04"   ; event: voice                  ; member: malik ; text: "That's my mom, let her in."
  - at: "19:05"   ; event: app.approve            ; member: malik ; class: security.door_unlock   # security is never approved by voice; the screen says "Mom is expected now", not "unlock for Mom"
  - at: "19:06"   ; event: link.replay            ; of: security.door_unlock                        # the accepted unlock command is sent again: refused, LINK_REJECTED (AWS mode; local mode runs Link's verifier with the development key)
  - at: "22:40"   ; event: voice                  ; member: dad   ; text: "Don't run the dishwasher until I'm done in the kitchen at eleven."   # arrives on Dad's own linked account; provenance is the account, never the voice
  - at: "23:05"   ; event: presence.sleep         ; member: mom ; zone: guest_room
  - at: "23:30"   ; event: voice                  ; member: malik ; text: "Optimize energy tonight."      # appliance_start after 22:00 is ASK under quinn-home
  - at: "23:31"   ; event: voice                  ; member: malik ; text: "Yes."                          # voice approval is allowed for non-security classes
  - at: "+1d 06:45" ; event: wearable.recovery    ; member: malik ; score: 41
  - at: "+1d 07:00" ; event: voice                ; member: malik ; text: "Good morning."
assert:
  audit_sequence_includes:
    - CONSTITUTION_PROPOSED
    - CONSTITUTION_ACTIVATED             # v8, before any plan approval exists
    - PLAN_CREATED
    - PLAN_REVISED                       # after "don't charge past 50"
    - APPROVED                           # "Do it", only after the revised plan landed
    - EXECUTE:energy.battery_dispatch    # discharge through the Mid-Day Peak
    - EXECUTE:energy.hvac_adjust
    - DENY_CONSTITUTION:security.door_unlock    # 18:40, citing constitution v8
    - EXECUTED:environment.lights        # living-room lamp on at 18:55 for Mom's arrival; the physical plug when bound
    - ASK_CONSTITUTION:security.door_unlock
    - APPROVED
    - EXECUTED:security.door_unlock
    - EXECUTED:security.door_lock        # the relock, run by Hirz Link from its own clock
    - LINK_REJECTED                      # the replayed unlock
    - PLAN_REVISED                       # after Dad's kitchen constraint
    - ASK_CONSTITUTION:energy.appliance_start   # the household's own rule: ask outside 07:00–22:00
    - APPROVED                           # by voice; appliance_start is not a security class
    - EXECUTED:energy.ev_charge          # in the Overnight period, after 21:00
    - EXECUTED:energy.appliance_start    # after Dad's constraint and Malik's approval
  plan_summary:
    estimated_savings_usd: {min: 1.00, max: 8.00}   # against the timer baseline; provisional; ROADMAP item 17 derives the range from the backtest and replaces it
    peak_kwh_avoided: {min: 5.0}
    comfort_violations_minutes: {max: 0}
  ev_soc_at: {"+1d 06:30": {min: 0.50}}
  never:
    - EXECUTE:finance.*
    - EXECUTE:security.access_code_share
```

Event kinds: `voice`, `app.approve|deny` (a member acting in the companion app; the only way a `security.*` approval can happen), `presence.arrive|leave|sleep|wake`, `calendar.add|remove`, `tariff.spike|update`, `weather.update`, `ev.drive|plug|unplug`, `call.inbound`, `contact.checkin_reply`, `doorbell.press|motion`, `device.fail`, `device.manual_change` (someone used the thermostat or the lock by hand: `OUT_OF_BAND_CHANGE`, and a manual hold for comfort devices), `link.replay|tamper|readdress` (the tamper playground's moves), `link.offline`, `wearable.recovery`, `constitution.activate` (optionally with a recorded `patch`), `clock.jump`.

`voice` events are delivered to the simulator's emulated host (or, in headless test mode, to a scripted host that calls the tools the emulator would call, so tests don't need Bedrock).

---

## 4. Running scenarios

```
hirz scenario run scenarios/demo-evening.yaml --speed 60            # interactive, companion app follows along
hirz scenario run scenarios/demo-evening.yaml --headless --assert   # CI: scripted host, asserts audit + numbers
hirz scenario step scenarios/demo-evening.yaml --to "18:40"         # pause before the unexpected visitor for recording
```

Scenario runs are recorded (`scenario_runs`) with the seed, the adapter mix, and the resulting audit range, so a demo video can cite the exact run it shows.

**Numbers are derived, never typed.** The demo household is on ComEd's Time-of-Day rate, whose all-in Mid-Day Peak price is several times its Overnight price, so the flexible load in the demo (about 12 kWh of EV charging, one home-battery cycle, a dishwasher, HVAC pre-conditioning) is worth dollars a night rather than cents. The assertion range in `plan_summary` is provisional until `ROADMAP.md` item 17 replaces it: the backtest script pulls a year of ComEd hourly history through the feed's date-range parameters, runs the planner on the demo loads for every day on both rate profiles, and writes the observed spread, the annualized saving per profile, the worst spike night avoided, and the hours charged at negative prices. The script and its data are kept in `scripts/` so every figure is reproducible. A reproducible number can still be a weak comparison, so the saving is measured against a timer schedule a careful household already uses, with "do everything now" and the cheapest-slots heuristic beside it, all held to the same comfort, the same energy into the car, and a battery that ends no emptier than it began. On Hourly Pricing the backtest plans from what was knowable at the time and is billed at realized prices; state carries between days; it reports a distribution, including the days on which Hirz adds little, for a home with solar, battery, and car, a home with a car only, and a home with no car; and the Time-of-Day replay before 2026-07-23 is labeled a counterfactual simulation (`ARCHITECTURE.md` §5.4). The scorecard leads with dollars (tonight, then annualized from the backtest); `peak_kwh_avoided` comes second. The `tariff.spike` event remains a twin-only test of the planner under a price spike and is never used to inflate a demo number.

---

## 5. Labeling

Twin observation outputs used as numeric policy facts are quantized to four decimal places on write by graph validation, the same as real observations.

Every observation carries `source`, one of three values. `real`: a live feed or a physical device (Open-Meteo, the ComEd hourly feed, the smart plug through Home Assistant, Smartcar, Ring sandbox events). `real API, demo devices`: Home Assistant's demo integration, a real API over simulated entities, never shown as plain `real`. `twin`: Hirz's own models. A published rate table is `real (published ComEd rate)`: real prices, not a live feed.

Cards show two visual states so a judge or a household can read them at a glance (`docs/design.md`): **live** (`real`) and **simulated** (`twin` and `real API, demo devices`, the more conservative reading). The full three-way source stays on every observation in the data, in the companion app's detail view, in the audit trail, and in the MCP `get_household_context` output (`data.sources`). The demo video shows the badges; honesty here is a scoring asset, not a liability.

**Public demo households are simulated only.** A household created by the hosted demo's "Start demo" button (`ARCHITECTURE.md` §5.14) can bind only `twin` adapters; the registry refuses any real binding for it, and a test asserts that.
