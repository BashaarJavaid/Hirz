# MCP Tool Catalog

**Implemented in item 23:** only `what_can_you_do`, with no input parameters.
Its generated output schema wraps the existing `Speakable` in `speakable` and
`data.available_tools` containing only its own name. The headline describes Hirz;
the detail explicitly says household tools are not connected. There are no
household reads, authentication, UI resources or side effects. The exact output
and client checks are recorded in the [item 23 evidence](./verification-log.md#item-23--2026-09-23).
[Local transport contract](./adr/ADR-013-mcp-transport.md).

The remainder describes the target surface for later roadmap items.

The tool surface Alexa+ (and the simulator) sees. Five groups, twelve tools. The surface is deliberately small: an orchestrator picks reliably among a dozen distinct verbs and unreliably among two dozen near-duplicates, and Alexa's own guidance is tools whose outputs feed each other. The tool-selection test in `ROADMAP.md` item 25 is the arbiter of this surface: if a tool misfires there, the surface changes. Every tool follows the same contract:

- **Input** is a JSON Schema 2020-12 `inputSchema` that is **flat**: enums and scalar parameters only, no free-form objects, no `oneOf`. Every parameter is described in consumer terms and with synonyms (Alexa+ resolves "the living room", "lounge", "front room" through the description). Internal action-class names (`energy.ev_charge`) never appear in an input schema.
- **Output** conforms to an `outputSchema` and always includes `speakable` (`headline` of about 20 words or fewer, `details[≤3]`, `options[≤5]`) so voice-only devices are complete, plus structured `data`, plus optional `ui` (an MCP App resource reference) for display devices. Text is free of formatting artefacts (no pipes, no markdown), so it is also safe for Alexa's hydrated rendering when no UI payload is sent.
- **Display modes** follow Amazon's add-on design guide ([display modes](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-display-modes.html)): voice-only is the always-on baseline; a tool with a card declares **inline** (the default: one headline figure, at most three rows, one primary action) and, where the content is dense, **fullscreen** (entered through a control the customer operates, never spontaneously). The exact declaration syntax is taken from the guide when the tools are built and cited in the code; it is not guessed here. The old custom `presentation` hint survives only as the simulator's device switch (Echo Show / Echo Dot).
- **Errors** are MCP tool-execution errors with a consumer-language `message` and a machine `code`; never protocol errors for validation problems, so the host can self-correct. A parameter combination that makes no sense for the chosen action ("set_temperature" with no temperature) is this kind of error.
- **No internal IDs in speakable text.** Plan, action, and case ids, and internal class names, travel in `data` and in `_meta` only.
- **Latency** under the §8 budget; nothing in a tool waits on a model, a solver, the Gateway, an adapter, or a third-party network call. Tools that act hand execution to the worker and say so in `speakable`.
- **Scopes** (OAuth): `hirz:read`, `hirz:plan`, `hirz:act`, `hirz:verify`. A valid token without the required scope gets HTTP 403, a friendly JSON message and an `insufficient_scope` challenge naming the required scope. Missing or invalid credentials get HTTP 401 with PRM discovery. The Skill-bridge demo token carries `hirz:read` only (ADR-007).

Naming follows the 2025-11-25 guidance: lowercase, underscores, verb first. Amazon's "Tools, Schema, Data Design" page of the add-on design guide is read and cited when the tools are built (`ROADMAP.md` item 25).

---

## Context

| Tool | Scope | Purpose |
|---|---|---|
| `what_can_you_do` | none | Returns a contextual capability summary ("Tonight I can plan energy, keep the house comfortable for your parents, and check suspicious requests"). Required by Alexa+'s onboarding rules; works for unlinked users with a generic summary. |
| `get_household_context` | read | The household right now, by `scope`: `people` (who is home and expected), `member` (one member's preferences, role, presence, and whether they are a trusted contact and which verification methods are available; input `member` by name or relationship with synonyms; never returns channel values), `energy` (the rate plan and the current price period, battery and EV state of charge, solar, today's cost and savings so far, source labels), `environment` (zones, temperatures, targets, lights, shades, locks, cameras, presence per zone, any active doorbell visitor context), `constraints` (active constraints with provenance: "Dad: kitchen in use until 11 PM"), `plan` (current plan headline and approval state), `security` (unusual situations, including a doorbell that has gone offline), or `all`. One read tool, one materialized view, one query. |

## Planning

| Tool | Scope | Purpose |
|---|---|---|
| `get_household_plan` | plan | The current plan for a horizon (`tonight`, `overnight`, `tomorrow_morning`, `next_24h`) with goals honored, actions, numbers, alternatives, and approval state. Optional `objective` tilt (`cheapest`, `greenest`, `most_comfortable`) requests a re-plan with that weighting. The summary leads with dollars saved and always includes the "do nothing" and "do everything now" comparisons, so no separate forecast tool exists. Fresh plan if one exists; otherwise the last plan marked `refreshing` plus an enqueued re-plan. Options: `Approve`, `Change something`, `Skip tonight`. Card: inline summary, fullscreen timeline. |
| `revise_household_plan` | plan | Records a spoken preference or constraint (`text`, `applies_to` member/asset/zone, optional `window`, `kind` ∈ `preference`, `constraint`, `one_time`) with the linked account and surface as its provenance (Alexa does not say who spoke; a name in the sentence is kept as `claimed_author`, shown as claimed), runs Coordinator normalization, and, if the plan is affected, marks it `refreshing` and enqueues the re-plan. No solver runs in the call, so the tool does not return a revised plan or a savings delta. Its `speakable` states the constraint, which is certain ("Got it, the car stops at 50. I'm updating the plan."); the card re-fetches when the new version lands, about a second later, and shows what moved and the new figure; by voice the member hears it on the next `get_household_plan`. "Don't charge past 50" and "Don't run the dishwasher until I'm done in the kitchen at eleven" both land here. |
| `explain_plan` | read | Why the plan is what it is: facts, considered alternatives, rejected ones with reasons, the rules that shaped it, and, with `focus: conflicts`, the conflicts between goals, member constraints, and the constitution with suggested resolutions and the members involved. Optional `focus` may also name an action or a goal. |

## Action

| Tool | Scope | Purpose |
|---|---|---|
| `approve_action` | act | Approves or declines the current plan, a specific action within it, or a pending approval, with requester confirmation elicitation when the constitution requires it. A plan that is `refreshing` cannot be approved ("Still updating, one moment"), so a cached plan is never approved as though it held a change just asked for. Runs pipeline stages 1–6 for what it approves; returns what is now executing (asynchronously, via the worker, `ARCHITECTURE.md` §5.6), what still needs approval, and what was blocked. Voice can resolve an approval only for classes whose `ask_channels` include `alexa`; for `security.*` classes (never voice-approvable, `docs/constitution.md` §2.5) the tool creates the approval, sends it to the companion app, and its `speakable` says the request is waiting on the phone. |
| `execute_household_action` | act | An immediate action, chosen from a consumer-language `action` enum: `charge_car`, `stop_charging`, `set_temperature`, `turn_on_light`, `turn_off_light`, `request_door_unlock`, `hold_battery`, `apply_profile`, `pause_automation` (every `auto` becomes `ask` until a member resumes Hirz in the app; pausing only tightens, so a voice may do it). Flat optional parameters, each described with synonyms: `room`, `temperature_f`, `percent`, `profile` (`recovery_morning`, `guests_arriving`, `night`, `away`), `for_whom`. The server maps each enum value to an action class through a table generated from `hirz/risk/classes.yaml`; the class name appears only in `data` and `_meta`. Runs pipeline stages 1–6 and either asks, denies, or hands each action to the worker for execution within seconds. Returns the Decision(s) with `status: executing` and a `speakable` that does not promise an outcome the boundary has not yet allowed, such as "I'm starting the charge. I'll tell you on your phone if it doesn't go through."; the verified outcome lands in the audit ledger and is reported by `get_action_audit`, the plan card, and a push notification. The call never waits on the Gateway or an adapter. **There is no money action in the enum**: a request to send money is routed to `assess_request_risk` by that tool's description, because Hirz has no way to move money, by design. |

## Trust

| Tool | Scope | Purpose |
|---|---|---|
| `assess_request_risk` | verify | Assesses a described request against the household's own records. This is also where any request to send money, share a code, or pay someone lands ("requests to send money" is in the description, with synonyms). `claimed_party: person` ("Malik called from a strange number and needs five hundred dollars"): signals, band, and recommended next steps. An optional `presented_number` is compared with that person's verified channels only when the member actually reads it out; the answer is "matches the number you have saved" or "does not match", never "it is really him", and with no number given the tool says nothing about the number. Checking with the contact is offered at every band, not only CRITICAL. `claimed_party: organization` ("someone from the utility is asking for a payment"): checks the presented channel against saved verified contacts for that organization and the curated registry and returns `matches`, `does_not_match`, or `insufficient_information`. Never treats caller-provided facts as true. |
| `verify_trusted_identity` | verify | Opens or advances a verification case for a trusted contact using the constitution's method order; returns status (`pending`, `genuine`, `not_genuine`, `will_call`, `no_answer`) and what was used. The check-in asks the contact about the specific request, not "was it you?". Alexa cannot speak when the reply arrives: the first `speakable` says to ask again in a minute, the card and the member's phone update on their own, and a later call returns the result. `genuine` is spoken as "Malik says he did ask for that. Talk to him on the number you have saved", never as advice to pay; `no_answer` as "Malik hasn't answered. Don't send anything." The contact answers in their own Hirz app and may belong to another Hirz household. Asked about someone with no open case, it reports whether they are a trusted contact and which verification methods are available; it never returns channel values. |

## Governance

| Tool | Scope | Purpose |
|---|---|---|
| `propose_household_rule` | plan | Records a rule the member says out loud ("from now on, never unlock the door for someone we're not expecting") as a **proposal**. The call stores the sentence and returns at once; no model runs inside it. The worker then drafts the YAML patch (`docs/constitution.md` §3), validates and compiles it, and pushes the diff to the companion app, where activation happens under a passkey. `speakable`: "I've written that as a rule and sent it to your phone. It won't take effect until you approve it there." Anyone in the room can propose; a voice can never activate, loosen, or tighten anything by itself. |
| `evaluate_permission` | read | Dry-run the pipeline for a hypothetical action ("could you unlock the door for my brother tomorrow?"), using the same flat `action` enum and parameters as `execute_household_action`: the would-be Decision with the rule and band, no side effects, no audit row beyond a `DRY_RUN` marker. The same evaluator produces the situation lines on the rule-preview screen (`docs/constitution.md` §3). |
| `get_action_audit` | read | What Hirz did and why over a window (`today`, `last_night`, `this_week`) or for a specific action: the daily scorecard numbers (dollars saved first, then the annualized figure, then peak kWh avoided) and the list of decisions in consumer language. |

### What was merged, and where it went

Earlier drafts listed twenty-three tools. Nothing was dropped; each capability now lives in one place: `get_household_member`, `get_current_constraints`, `get_energy_state`, and `get_environment_state` are scopes of `get_household_context`; `create_household_plan`, `optimize_energy_plan`, and `forecast_energy_cost` are `get_household_plan`; `record_household_preference` is `revise_household_plan`; `evaluate_plan_conflicts` is `explain_plan` with `focus: conflicts`; `approve_plan` and `request_high_risk_approval` are `approve_action`; `execute_energy_action` and `apply_environment_profile` are `execute_household_action`; `verify_organization` is `assess_request_risk` with `claimed_party: organization`; `get_trusted_contact` is answered by `verify_trusted_identity`. The twelfth tool, `propose_household_rule`, was added on 2026-09-17 so the constitution is reachable from Alexa, not only from the companion app.

---

## MCP App resources

All cards follow `docs/design.md`: Amazon's published design tokens verbatim, a 768×480 base canvas, one job per card, light and dark modes.

| Resource | Rendered by | Modes | Content |
|---|---|---|---|
| `ui://hirz/plan-card` | `get_household_plan`, `revise_household_plan` | inline, fullscreen | Inline: dollars saved tonight, three rows, Approve. Fullscreen: the timeline, all actions, alternatives. Buttons call `approve_action` / `revise_household_plan` through the host bridge |
| `ui://hirz/approval-card` | `approve_action`, `execute_household_action` (when ASK) | inline | One action, its rule, its band, Approve / Deny (for `security.*` classes the card says the approval is on the phone and shows no Approve button) |
| `ui://hirz/verification-card` | `assess_request_risk`, `verify_trusted_identity` | inline | One headline, up to three signals, verification status (`pending` → result; the card re-calls `verify_trusted_identity` through the host bridge while pending, so the screen updates without anyone asking) |
| `ui://hirz/doorbell-card` | `get_household_context` (scope `environment` or `security`) when a visitor context is active | inline | Snapshot, schedule context worded as context ("Mom is expected now", never "Mom is at the door"), unlock request button (pipeline-gated) |
| `ui://hirz/scorecard` | `get_action_audit` | inline, fullscreen | Inline: dollars saved, annualized figure, peak kWh avoided. Fullscreen: counts and the decision list |

All cards are built with `@modelcontextprotocol/ext-apps`, render in the host's sandboxed iframe, and call tools only through the host bridge so every action still passes the pipeline. Cards are optional overlays; the `speakable` block carries every critical fact.

---

## Elicitation

Used sparingly and only where Alexa+ would otherwise guess: requester confirmation for security classes (`Who am I talking to?` with the member list as a titled enum), and "which zone?" when a comfort request is ambiguous and no default zone is set. Elicitation schemas are flat, single-select, and carry defaults per the 2025-11-25 spec. The requester answer is recorded as *claimed* and can only lower the linked account's authority; it is never treated as identification (`ARCHITECTURE.md` §7).

---

## Emulator system contract

The simulator's emulated host is given these rules, which mirror Alexa+'s published functional requirements, so what judges see is a faithful preview:

- Use only tools from `tools/list`; never invent capabilities.
- Speak the `speakable.headline`, then at most the `details`; offer at most 5 `options`.
- Never say tool names, ids, or JSON. Keep spoken turns under 30 seconds.
- Before any commitment (approve a plan, unlock, contact someone), read back the key details and require an explicit yes.
- In voice-only mode, never refer to the screen.
- On tool error, say what happened in plain words and offer a next step.

The generic, black-box parts of this contract (Streamable HTTP on 2025-11-25, Protected Resource Metadata, the `401` challenge, schema completeness, naming, declared display modes, warm round trip under 500 ms, spoken length under 30 seconds, no formatting artefacts) are checked by the open-source conformance checker (`ROADMAP.md` item 25a), which Hirz's CI runs against its own server. Hirz's own tests keep only the Hirz-specific rules: `speakable` present, options ≤ 5, headline length, no internal IDs or class names in consumer strings.


Item 18's reserved `governance.record_constraint` and
`governance.withdraw_constraint` are internal coordinator operations. Exclude them
from the future `execute_household_action` consumer device-action enum. Constraint
MCP intake remains item 25; the current interface is the internal Python service.


`approve_action` has three existing internal paths:

| Case | Internal path |
|---|---|
| Plan consent | `PlanService.approve`; refused while the plan is `refreshing` |
| Planned device ASK | `PlanService.respond_to_action` with `plan_id` plus `approval_id`; votes through `Pipeline.vote`, then performs the audited resume |
| Standalone approval | `Pipeline.vote`, then `Pipeline.redeem` / `Pipeline.enqueue` |

Item 25 maps the flat tool input onto these three cases and adds no fourth path.

`revise_household_plan`'s text field is provenance: item 25 builds `ConstraintSpec`
from `applies_to`, `kind` and `window`; the sentence grammar in
`hirz/planner/coordinator.py` stays for the scenario host and tests only.

## Local authentication (item 24)

Generic `what_can_you_do` remains anonymous. The authenticated startup and separate
simulated issuer are documented in [development procedures](./development.md#item-24-local-oauth).
Other tools default to protected `hirz:read` access and cannot register without
authentication wiring; their eventual catalog scopes must be supplied explicitly.
The normal catalog still contains only generic onboarding. `oauth_probe` is a
test/smoke-only read of resolved identity, with a fixed required scope per test.
Unmapped/child tokens can use generic onboarding but receive 403 for protected
calls. Required keys/database unavailable gives 503. Policy denials remain tool
results. Full household tools/isolation and Inspector OAuth registration remain
later work; [ADR-014](./adr/ADR-014-local-oauth.md) records the exact local contract.
