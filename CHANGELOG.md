# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- 2026-09-21: Add read-only MILP proposals, strict twin-replayed baseline comparisons, archived historical replay and planning snapshots; publish partial coverage rather than unsupported annual claims ([item 17 evidence](./docs/verification-log.md#item-17--partial-2026-09-21), [ADR-005 amendment](./docs/adr/ADR-005-deterministic-planner.md#read-only-planner-and-historical-experiment--2026-09-21)).

- 2026-09-21: Record [terminal HA dispatch attempts and fresh-action retries](./docs/adr/ADR-006-twin-first-adapters.md#terminal-ha-dispatch-attempts--2026-09-21-author-approved) and the Phase 2 review's [Phase 3 carry-overs and ordered-plug follow-up](./ROADMAP.md).

### Fixed

- 2026-09-21: Fix historical planner replay with shared causal simulated thermostat
  and battery controls; verify the full year and wear sensitivities without
  relaxing constraints or extending execution authority
  ([ADR-005 amendment](./docs/adr/ADR-005-deterministic-planner.md#causal-historical-replay-amendment--2026-09-21),
  [completion evidence](./docs/verification-log.md#full-offline-reproduction-and-completion--2026-09-21)).

- 2026-09-21: Replace the scenarios' constant weather with inline archived Chicago
  weather while retaining deterministic twin replay
  ([verification](./docs/verification-log.md#scenario-weather-from-archived-observations)).

- 2026-09-21: Bind a door-unlock ASK's doorbell press to its approval so delayed
  voting/redemption retains visitor context; refuse newer presses without widening
  the autonomous window ([verification](./docs/verification-log.md#doorbell-press-bound-to-approval)).

- 2026-09-21: Phase 2 cleanup batch 1: use the simulation clock for registry
  reads, retain failure classes in redacted logs, reject absent-member sleep,
  apply pending development migrations and clarify adapter/scenario docs
  ([verification](./docs/verification-log.md#phase-2-cleanup-batch-1)).

- 2026-09-18: Quantized graph numeric policy facts to four decimal places before
  strict Cedar range validation, preserving float storage and observation no-ops;
  [verification](./docs/verification-log.md#graph-policy-fact-quantization--2026-09-18).

- 2026-09-18: Missing HVAC baselines skip deviation scoring without weakening
  other required facts ([ADR-004 amendment](./docs/adr/ADR-004-no-ml-risk-scoring.md#missing-hvac-baseline-amendment--2026-09-18-author-approved));
  pipeline and boundary failure logs include the exception class without payloads
  ([verification](./docs/verification-log.md#missing-hvac-baseline-and-exception-class-logging--2026-09-18)).

- 2026-09-18: Closed item 11 after the authorized empty-audit development schema
  reset and reseed; [verification](./docs/verification-log.md#development-database-reset-and-phase-1-review--2026-09-18).
- 2026-09-18: Phase 1 review: tests discover the local Dogwood binary, pipeline
  and boundary failures log operation context, and unused `Household.budgets` is
  removed so budgets remain in constitution rules; documented the activation
  migration prerequisite and audit-clock failure mode.

- 2026-09-18: Updated the CI installed-wheel catalog check from 21 to 23 entries
  to include item 9's pause/resume actions; [verification](./docs/verification-log.md#item-9-ci-build-check--2026-09-18).

### Added

- 2026-09-20: Item 16 offline scenario runner, explicit twin fixtures, scripted
  deferred tool traces, simulated recorded-policy patches, observation assertions
  and JSON reports; scenario CI now exercises the approved observation gate
  ([ADR-006](./docs/adr/ADR-006-twin-first-adapters.md#item-16-observation-stage-scenarios--2026-09-20-author-approved)).

- 2026-09-20: Item 15 software: household-bound HA reads/subscriptions, narrow local
  Pipeline-authorized writes with durable attempt claims, direct verification and
  scenario-only twin read fallback; recorded/live smokes restore demo state and
  retain signed audit evidence. The physical plug gate remains outstanding
  ([ADR-006](./docs/adr/ADR-006-twin-first-adapters.md#item-15-local-ha-amendment--2026-09-20-author-approved),
  [evidence](./docs/verification-log.md#item-15--partial-2026-09-20)).

- 2026-09-20: Completed item 14: credential-free ComEd/Open-Meteo reads, reviewed
  tariff sources, explicit price/weather coverage and provenance, and recorded/live
  smoke verification; real prices compose with explicitly bound twin assets
  ([ADR-006](./docs/adr/ADR-006-twin-first-adapters.md#item-14-credential-free-energy-amendment--2026-09-20-author-approved),
  [evidence](./docs/verification-log.md#item-14--complete-2026-09-20)).

- 2026-09-19: Completed item 13's in-memory twin models, simulated clock and eight
  read adapters with explicit calibration, deterministic replay and labeled
  observations; action execution remains deferred. Added the credential-free
  smoke and corrected the derived EV timing in the twin spec
  ([ADR-006 amendment](./docs/adr/ADR-006-twin-first-adapters.md#item-13-models-and-read-adapters-amendment--2026-09-19-author-approved),
  [verification](./docs/verification-log.md#item-13--complete-2026-09-19)).

- 2026-09-19: Completed item 12's nine adapter contracts, registry/source stamping,
  separate observation domains and graph-derived policy/risk facts; the CLI now
  accepts explicit fill-only simulated facts. Legacy observations are preserved,
  and production adapters remain later work ([ADR-006 amendment](./docs/adr/ADR-006-twin-first-adapters.md#item-12-contract-amendment--2026-09-19-author-approved),
  [verification](./docs/verification-log.md#item-12--complete-2026-09-19)).

- 2026-09-18: Recorded plan-approver authority for scheduled actions and autonomous
  re-plans, with an execution prohibition for unapproved plans;
  [author-approved ADR-005 amendment](./docs/adr/ADR-005-deterministic-planner.md#scheduled-action-authority-amendment--2026-09-18-author-approved).
- 2026-09-18: Extended [roadmap item 12](./ROADMAP.md) with graph homes for Phase 2
  facts and the requirement to translate CLI evidence into in-memory observations.

- 2026-09-18: Item 11's read-only `hirz decide` CLI previews stored, unactivated
  policies using the existing pipeline, explicit hypothetical identity/target
  inputs and canonical Decision JSON. [Contract and tradeoffs](./docs/adr/ADR-003-constitution-yaml-to-cedar.md#item-11-amendment--2026-09-18-author-approved);
  [verification](./docs/verification-log.md#item-11--2026-09-18).

- 2026-09-18: Phase 1 item 10: read-only audit verification, private sequence-range
  exports and offline verification with independently trusted public keys.
  [Contract and tradeoffs](./docs/adr/ADR-002-postgres-over-dynamodb.md#item-10-amendment--2026-09-18-author-approved);
  [verification and limitations](./docs/verification-log.md#item-10--complete-2026-09-18).

- 2026-09-18: Phase 1 item 9: deterministic internal pipeline, durable single-use
  execution grants, persisted quorum approvals, exact daily budget reservations,
  and atomic household pause/resume. Signed audit append is pulled forward from
  item 10; physical execution and public authentication remain later work.
  [Contract and scope](./ARCHITECTURE.md#34-internal-pipeline-contract-item-9);
  [verification](./docs/verification-log.md#item-9--complete-2026-09-18).

- 2026-09-18: Phase 1 item 8: standalone deterministic risk scoring, typed facts
  and canonical risk results, catalog freshness thresholds, and a shared floor
  function used by constitution validation. Semantics and boundaries:
  [ADR-004](./docs/adr/ADR-004-no-ml-risk-scoring.md#item-8-amendment--2026-09-18-author-approved);
  checks and API output: [item 8 evidence](./docs/verification-log.md#item-8--complete-2026-09-18).

- 2026-09-18: Phase 1 item 7: validated constitution engine, canonical Action,
  deterministic English/situation preview, native Dogwood compiler and local
  boundary, and database-free `constitution validate|compile|preview` commands.
  Required local conformance replaces the CI placeholder; the pinned binary ships
  in the non-root container. Corrected seed files preserve existing stored history.
  Semantics: [ADR-003](./docs/adr/ADR-003-constitution-yaml-to-cedar.md#item-7-amendment--2026-09-18-author-approved-semantics);
  validation and limits: [item 7 evidence](./docs/verification-log.md#item-7--complete-2026-09-18).

- 2026-09-18: Phase 1 item 6: versioned Household Graph, household-scoped repositories,
  redacted current/historical context, and explicit two-household demo bootstrap
  with `hirz seed` / `hirz context`. Constitutions remain unvalidated; the bootstrap
  exception and storage tradeoffs are recorded in [ADR-002](./docs/adr/ADR-002-postgres-over-dynamodb.md#item-6-amendment--2026-09-18-author-approved).
  Operating procedures: [development](./docs/development.md); validation:
  [item 6 evidence](./docs/verification-log.md#item-6--complete-2026-09-18).

- 2026-09-18: Phase 0 item 5 complete: a second person followed the README on a clean machine (reported by the author; evidence entry in `docs/verification-log.md`). Phase 0 is done; Phase 1 item 6 is next.
- 2026-09-18: `docs/verification-log.md` holds the full verification evidence per roadmap item; the Phase 0 paragraphs moved there verbatim and `ROADMAP.md` keeps one sentence per item with a link. `CLAUDE.md`/`AGENTS.md` gain a "Where records go" table (one home per kind of record) and a shorter "Current phase".
- 2026-09-17: Phase 0 item 4 complete and verified on `main`: all
  eleven GitHub Actions jobs, pinned tools/actions, read-only repository access,
  existing Python/TypeScript checks, disposable Compose integration checks,
  package/fresh-wheel and non-root container checks. Future scenario, conformance,
  latency, Cedar, and release jobs are explicit successful placeholders; browser
  tests and frontend bundles are also deferred. No AWS publication or new
  application guarantees. After PR #1 merged, all eleven jobs passed in
  [main run 35310102678](https://github.com/BashaarJavaid/Hirz/actions/runs/35310102678)
  at `fdc06fca4499794b55a84ffcae6e8203654b2a9b`. Python 36 passed with 86.13%
  coverage, PostgreSQL integration 4 passed, and one Vitest test per workspace
  passed on Ubuntu 24.04 x64. Item 5's second-person README check remains pending.
  Local verification: Python 36 passed, 86.13% coverage; PostgreSQL integration
  4 passed; one Vitest test per workspace; lint/types, package/fresh-wheel,
  isolated Compose service checks, schema drift, doctor, and container UID passed.
- 2026-09-17: Phase 0 item 3 verified: Alembic `0001_initial` adds five
  foundation tables using SQLAlchemy Core and async psycopg, UUID identities,
  household-scoped account links, and per-household audit pointers. Explicit
  initialization preserves or creates the local P-256 key in `.env`, refusing
  missing-key generation over audit rows, partial schema, or failed database checks.
  Added read-only `hirz doctor`: four independent results, bounded waits, and
  credential-safe failures. Clean source snapshot/fresh-volume doctor: four PASS;
  Python: 36 passed, 86.13% runtime coverage; PostgreSQL integration: 4 passed.
  Migration round trips, key/credential preservation, live negative probes,
  lint/types, locked install, package build/fresh-wheel CLI, container liveness,
  and authenticated HA demo checks passed. Updated architecture, ADR-002, setup,
  and matching agent guidance. Graph history, seeds, audit writing, and application
  behavior remain deferred; no threat-model protection status changed.
- 2026-09-17: Phase 0 item 2 verified: localhost-only Compose with pinned
  PostgreSQL 16.15, Home Assistant 2026.9.2 demo entities, a non-root Hirz
  `/health` container, and optional Jaeger 2.21.0. Explicit initialization
  provisions local passwords and an HA token into ignored `.env`; reruns reuse
  credentials and inconsistent state fails without resetting data. Added live
  checks, recovery/reset instructions, and bootstrap tests. Python: 19 passed;
  Ruff, strict mypy, locked sync, and package build passed. Authenticated HA curl
  returned 123 entities; isolated checks proved credential failure handling,
  database/HA persistence across down/up, and disposable Jaeger trace retrieval.
  Runtime coverage is 100% over five statements, not a household guarantee.
  Verified on macOS ARM64 with Docker Desktop 4.87.0; upstream HA does not support
  Docker Desktop for its general Container installation. No physical-device
  support, MCP, worker, application schema, or readiness endpoint is claimed.
- 2026-09-17: Phase 0 item 1 verified: installable Python 3.12 `hirz` package,
  uv lockfile, private pnpm `web` and `mcp-app` workspaces, exact dependency pins,
  shared TypeScript/ESLint configuration, Ruff, strict mypy, and import smoke tests.
  Replaced the empty-suite requirement with smoke checks by author approval;
  the Python 80% line-coverage gate is active. Python: 1 passed; TypeScript:
  1 passed per workspace. Lint, types, locked installs, package build, fresh-wheel
  import, and deliberate test/coverage failure probes verified. Scaffold coverage
  is 100% over zero executable statements. README setup and agent instructions
  updated; application behavior, Compose, migrations, and CI remain unbuilt.
- 2026-09-15: Project architecture, threat model, roadmap, constitution spec, tool
  catalog, twin and scenario spec, demo script, submission checklist, and ADRs 001–008.
  No code yet; Phase 0 is next.
- 2026-09-16: Identity on a shared device: roles bind to linked accounts, never to voices;
  `security.*` classes are never approvable by voice (`ask_channels` must exclude `alexa`,
  validator-enforced); `requester.surface` condition attribute; reserved `requested_by.speaker`
  hook that can only lower authority; demo and scenario approve the unlock in the companion app.
- 2026-09-16: Positioning relative to the field: README "Why" and "What Hirz adds" (constitution
  compiled to Cedar and enforced twice, planner over real prices, multi-member provenance,
  verification from the household's records) replace the "four innovations" table; the Devpost
  description draft and the demo thesis line lead with the same four. No build scope changed.
- 2026-09-16: Ring framing and gate: Ring is an event and media source only (its Partner API has no
  lock capability); the unlock is the devices adapter's lock, said so in the demo script, the Devpost
  draft, and the architecture. Roadmap item 34 now starts with a sandbox access gate (signed synthetic
  `button_press` received without a physical device); the Ring track entry is kept only if it passes,
  and dropping it leaves the Alexa+ entry and the twin doorbell untouched. Linking wording corrected
  from OAuth to Ring-driven app-integration linking.
- 2026-09-16: Boundary enforcement made literally true: the local stage-7 evaluator and the
  conformance test use the open-source Dogwood CLI (one evaluator, real temporal semantics; no
  hand-written shim; `cedarpy` kept only as a documented fallback); the compiler emits one generic
  temporal permit per approval TTL instead of one per `ask` class, so the 25-policy quota no longer
  limits constitution size; automated-reasoning analysis is stated as AWS-mode (AgentCore
  `validationMode`) with local activation recording "not analyzed"; the threat-model row for
  boundary divergence and ADR-003 now say the boundary is independent about policy, not context
  facts. Roadmap item 7 gains an early Dogwood gate; item 37 verifies analysis refusal.
- 2026-09-16: Core split into two roles of one image (ADR-008): `mcp` on AgentCore Runtime (MCP
  server, pipeline stages 1–6, never calls the Gateway or an adapter) and `worker` on one small
  always-on App Runner service (scheduler, pollers, HA WebSocket, Executor with stage 7 via the
  Gateway, companion API, Ring webhooks, web push), approved by the author. "Act" tools now return
  `status: executing` and the worker executes within seconds, so no tool call waits on the Gateway
  or a third-party network. The tick Lambda targets the worker. Runtime cold start is measured and
  reported separately from the warm latency budget. Roadmap items 19, 36, 38 and `hirz doctor
  --aws` updated; friction-log candidate added.
- 2026-09-16: Savings numbers made defensible (option A: stay on ComEd real-time pricing). The
  demo assertion range is now provisional ($0.50–$3.00) until roadmap item 17 derives it from at
  least two weeks of recorded ComEd data run through the planner, with the derivation kept in
  `scripts/`; `peak_kwh_avoided` leads the scorecard and the plan summary; README dialogue, the
  Plan example, and the demo script no longer carry typed dollar figures; item 40 requires every
  figure in the video, README, and Devpost text to come from the cited run. The budget worked
  example now describes spend, not savings.
- 2026-09-16: Smaller-things batch. Threat model: every unearned row now reads Planned with its
  phase and eventual value. Constitution: overrides may only tighten (validator rule). Tool catalog
  merged from twenty-three to eleven tools with no capability dropped; all cross-references updated;
  a tool-selection test added to roadmap item 25. Emulator default is Claude Haiku 4.5 with Nova
  Lite selectable and the banner naming the model (ADR-007 revised). One web app (`apps/web`) with
  the simulator as a route replaces two apps; the MCP App bundle stays separate. Source labels are
  now `real`, `real API, demo devices`, `twin`; one physical energy-monitoring smart plug is the
  living-room light (bound via `asset_bindings`, twin fallback), lit at 18:55 for Mom's arrival and
  asserted in the scenario. Submission enters both mini-challenges with an upstream PR planned.
- 2026-09-16: Demo script restructured so each beat proves one thing. The scam beat is now the
  household's own request to send money, refused under `finance.transfer_money: never` and then
  verified through Dad's app (no relayed phone call). The overnight dishwasher, which the household's
  `appliance_start` rule makes an ASK after 22:00, is approved by voice at 23:30 and becomes the spine
  of the video (rule shown at 0:45, asks at 1:55, Cedar at 2:20); this also fixes the script
  contradicting the constitution. Wearable line and AWS console tour cut from the video only;
  console screenshots move to the Devpost gallery. Scenario timeline and assertions updated.

- 2026-09-17: **Design revision after a full critique against the hackathon rules** (four equally
  weighted criteria; judges may score from the video and description alone). Eleven points were
  walked one by one with the author and applied in one pass. No code existed, so no code changed.
  - **Renamed from "Haven" to "Hirz".** Collisions in the project's own category: HAVEN Lock (a
    smart door-lock company with a published Alexa Skill) and havenos.us (an "intelligent space
    platform" with a hub and smart locks), while the repository was named HavenOS. "Kahf" was
    checked and ruled out (Kahf Guard, a family-protection product). For "Hirz" no smart-home,
    security, or Alexa collision was found; npm and PyPI are free; hirz.ai is a recruiting
    product in another industry; the author's USPTO search in classes 9 and 42 came back clear on 2026-09-17.
    Package, CLI, scopes (`hirz:*`), card URIs (`ui://hirz/`), and environment variables
    (`HIRZ_*`) follow. The GitHub repository (`BashaarJavaid/Hirz`) and the local folder were renamed the same day.
  - **Pitch and customer.** Tagline "House rules for the AI in your home, and your parents'."
    Named customer: the family's household manager, responsible for two homes; "rules, not
    care". README gains "Who it's for" with FTC and AARP figures checked against the primary
    sources. "Bounded autonomy" stays as the architecture's name for the idea.
  - **Demo: three beats and a close.** Cold open at the parents' home: Mom asks whether the
    "Malik" who called for money is real; the check-in lands on Malik's phone. The earlier beat
    (the owner asking Alexa to send money, refused under a `never` rule) was dropped because it
    refused something Hirz cannot do. Then one rule proposed by voice, activated on a phone as
    constitution v8, and enforced an hour later on an unexpected visitor; then the door for Mom.
    The loop animation, the Dad/dishwasher beat, the standalone Echo Dot beat, the morning beat,
    and the Cedar thread leave the video only. New scenario `parents-scam-check.yaml`; second
    seed `constitutions/quinn-parents.yaml`; the demo seed starts without
    `never_for: [unknown_visitor]`.
  - **Money.** No money action is offered to the orchestrator; money requests route to
    `assess_request_risk`. The finance classes stay in the risk table and the constitution for
    the scam-pattern factor. "Forbid them provably" became "no way to move money, by design".
  - **Twelfth tool, `propose_household_rule`.** Records the sentence, no model in the call;
    the worker drafts; activation is passkey-gated in the app. New event `CONSTITUTION_PROPOSED`.
    A voice proposes, a phone activates.
  - **Flat action tool.** `execute_household_action` and `evaluate_permission` take a
    consumer-language `action` enum with flat parameters; internal class names never appear in
    an input schema. The tool-selection test is the arbiter.
  - **Energy.** The demo household moves to ComEd's published Time-of-Day rate (reverses the
    2026-09-16 "stay on real-time pricing" decision); ComEd Hourly stays as the second profile;
    prices are all-in (supply plus delivery); the backtest pulls a year of hourly history (the
    feed's date-range parameters were verified on 2026-09-17) and produces every published
    figure; the scorecard leads with dollars and an annualized figure. Rate values are
    transcribed from ComEd's own documents when the tariff file is written; none are typed here.
  - **Design.** New `docs/design.md`: Amazon's add-on design tokens and display modes verbatim,
    a 768×480 base canvas, one job per card, seven hand-designed screens, three CSS motions,
    spoken headlines of about 20 words or fewer, two badge states on cards (`live`,
    `simulated`) with the three-way source kept in data. Tailwind + shadcn/ui for the web app;
    plain CSS tokens for the cards. The custom `presentation` hint became a simulator switch.
  - **Hirz Link and signed commands (ADR-009).** The worker no longer holds a Home Assistant
    token. A home-side agent keeps the token in the house, dials out, and executes only commands
    signed by a KMS key that only the Gateway's Lambda role may use; write-capable cloud
    credentials are readable by that role only. New event `LINK_REJECTED`. The lead claim was
    reworded to exactly this, and local mode is labeled `dogwood-local`, a second evaluator in
    the same trust domain. ADR-003 and ADR-008 amended.
  - **ADR-007 corrected.** The Skill bridge does not require an Echo (the developer-console
    simulator works); the real reasons it is not the primary surface are recorded (no account
    linking, no visuals, a different model, Skill-style invocation). One five-second read-only
    clip with a `hirz:read` token, a second-host screenshot, and a forum question to the
    organizers about toolkit access.
  - **Ring.** Both tracks entered if the item 34 gate passes (the rules say "Primary
    Track(s)"). Four event types used instead of one (vehicle/human motion into the visitor
    context; doorbell offline raising `state_stale` on unlock); a courier-pickup correlation
    (recent CRITICAL case plus an unexpected visitor → warn and notify the verified contact);
    the submission text framed in the track's priority categories. A Ring doorbell is bought
    only if the sandbox gate requires a device.
  - **Open Source.** `docs/submission.md` had misread the rule: the project must be
    *additional* to the primary submission. The entry is now a separate repository: an add-on
    conformance checker first, then the simulator's generic host harness. Dogwood Python
    bindings are decided after the item 7 gate; the bridge OAuth pull request was skipped.
  - **Audit anchors.** Chain head to S3 Object Lock (governance mode, worker put-only), hourly
    and on every constitution activation; `hirz verify-audit --anchors`; new event
    `AUDIT_ANCHORED`. The threat-model row now says what the chain alone does and does not stop.
  - **Hosted demo.** A public "Start demo" path seeds a throwaway household restricted to twin
    adapters, rate-limited, 24-hour lifetime.
  - **Friction log.** The 2026-09-15 entry about unreachable design-guide links was removed
    (the pages load; the entry had no URL or status). Candidates added: Home Assistant tokens
    cannot be scoped; the Skill bridge's missing account linking and visuals.
  - **Roadmap.** New items 25a, 29a, 33a, 38a, 38b, 38c, 41a; a rewritten cut line with the
    order in which below-the-line items are let go; Phase 9 gains the caregiver view across
    homes, the activity-signal idea, and trademark clearance. Approved spend: one KMS key, one
    S3 bucket, the bridge stack for the recording, and rate-limited Bedrock use by the hosted demo.
- 2026-09-17: **Second design revision, after an external fifteen-point critique.** Each point was
  accepted or rejected on merit with the author and applied in one pass. No code existed, so no
  code changed. The author said build time is not the constraint, so nothing was cut.
  - **Authorization chain (ADR-009 amended, ADR-003's permit tightened).** The signing Lambda
    recomputes the action hash instead of trusting the worker's; the command envelope carries
    `home_id`; Hirz Link refuses an operation it already executed, so one approval yields one
    operation; temporal permits match on class, household, and TTL group, because Cedar permits
    are alternatives and a ten-minute approval could otherwise ride the thirty-minute permit;
    every policy is scoped to its household, and hosted-demo households stay on the local
    evaluator. The worker calls the Gateway with a machine token, so the requester's role is
    now described as an input Hirz supplies, not as independently evaluated.
  - **The lead claim is scoped.** "Nothing to act with" covers a bug or a bypass path, not a
    compromised worker, which can still claim an approval happened. New threat-model row says
    No. **ADR-010** and roadmap item 38d (below the cut line) close it for `security.*`: the
    member's passkey assertion over the action hash is verified inside the signer, with keys
    enrolled through a separate `hirz-passkeys` Lambda the worker never touches (approved
    pay-per-use resource). It will be Partial, because Hirz still serves the approval page.
  - **Safety after the action.** A bounded operation is authorized whole: the signed command
    carries its revert, and Hirz Link stores it and runs the relock from its own clock, offline
    and across restarts. A real device is never replaced by its twin outside a scenario or demo
    household, and a twin read-back never verifies a real device.
  - **What the rules cover.** Hirz governs the actions Hirz takes. New threat-model row for
    parallel control paths (No); a deployment rule; *managed through Hirz* / *not managed* on
    the Household page; new event `OUT_OF_BAND_CHANGE`; a manual thermostat change becomes a
    two-hour hold the planner works around. The tagline is unchanged.
  - **Visitor semantics.** A schedule is context, not identity. Approval text is "Someone is at
    the front door. Mom is expected now.", never "Unlock for Mom"; `unknown_visitor` is renamed
    `unexpected_visitor` and defined as a press matching no arrival window; the drafter must say
    when a sentence ("someone I don't know") cannot be expressed; new scenario
    `stranger-in-window`.
  - **Scam check.** Hirz no longer says "That number isn't one of Malik's": it cannot see the
    call and Mom never read the number out. A number is compared only when given, and a match is
    never proof. The check-in asks about the specific request, with three answers; new status
    `will_call`; `genuine` is never advice to pay; model signals are unioned with keyword
    signals; the check is offered at every band; new scenarios for no answer and an ordinary
    request.
  - **Honest asynchronous conversation.** Alexa cannot speak unprompted, so Mom asks again
    before hearing Malik's answer, and the card updates on its own. `revise_household_plan`
    keeps the no-solver rule: it speaks the constraint, marks the plan `refreshing`, and the
    card re-fetches; `approve_action` refuses a `refreshing` plan; "Starting the charge now"
    no longer promises an outcome the boundary has not allowed. The worker is driven by a
    one-minute tick because App Runner throttles idle CPU (the rule's spend was approved by the author
    on 2026-09-17). Whole-interaction times are measured, not only the acknowledgment.
  - **Energy experiment.** The headline saving is against a timer schedule, with "do everything
    now" and the cheapest-slots heuristic beside it, all held to equal comfort, delivered EV
    energy, and final battery state. The backtest has no hindsight (plan on knowable prices,
    bill at realized ones), carries state between days, reports a distribution, runs three
    households including one with no solar or battery, and labels the Time-of-Day replay before
    2026-07-23 a counterfactual. Whether ComEd serves day-ahead history is checked in item 17.
    An infeasible problem keeps the last feasible plan and names the constraint to relax.
  - **Contradictions resolved.** Un-accepted memory is never planner input. Provenance is the
    linked account and surface, with `claimed_author` for a name in a sentence. "No model
    participates in any decision" became "no model makes a decision". "Every action has a voice
    equivalent" became "can be started by voice". Dad's sentence no longer says "tonight". A
    property-based test compares the YAML evaluator with the compiled policy.
  - **Novelty claims.** "Nothing plans across…" and "every entrant… none is faithful" removed;
    EMHASS and Home Assistant's entity exposure are named; ADR-005 records EMHASS as the
    benchmark, not a component.
  - **Additions.** The rule preview's situation lines are derived by evaluating both versions,
    never written by a model; a household pause (voice may pause, only the app resumes; events
    `AUTONOMY_PAUSED`, `AUTONOMY_RESUMED`); more than one passkey per member and a recovery
    code; a tamper playground (38e); hallway tests with five to eight people (40a).
  - **Demo.** The video's close is the accepted unlock command replayed and refused; the
    Skill-bridge clip moves to the gallery. The demo lock is Home Assistant's demo lock so the
    unlock rides the signed path.
  - **Rejected on merit:** changing the tagline; a positive-rule beat in the video; EMHASS as a
    component; a read-and-disclosure constitution domain (Phase 9); separate "receipt" and
    "effort metric" features (the audit tool and the scorecard already are those).
