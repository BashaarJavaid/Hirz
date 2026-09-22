# AGENTS.md

Project-specific context and instructions for Hirz (this file mirrors `CLAUDE.md` for Codex and other coding agents), merged with a set of general behavioral guidelines (sections 1–5 below, adapted from [andrej-karpathy-skills/CLAUDE.md](https://github.com/multica-ai/andrej-karpathy-skills/blob/main/CLAUDE.md) and from the author's PortunusMCP conventions) aimed at reducing common LLM coding mistakes: unstated assumptions, speculative complexity, unrelated edits, vague success criteria, and unverified claims of completion.

**Tradeoff:** these guidelines bias toward caution over speed. For trivial tasks, use judgment. When in doubt, ask.

---

## Project

Hirz — house rules for the AI in your home, and your parents': a permissioned household agent for Alexa+ (MCP add-on) that lets a family decide what Alexa may do on its own, what it must ask about, and what it may never do ("bounded autonomy" in the architecture docs). The customer is the family's household manager, responsible for their own home and their parents'; Hirz is rules, not care. It has a household graph, a household-authored constitution (proposed by voice, activated on a phone) enforced in-process, via AgentCore Policy, and by a home agent that obeys only signed commands (Hirz Link), a deterministic risk engine, a MILP planner over real ComEd rate plans, a protect layer, a digital twin, and a companion web app plus an Alexa+ simulator. Full pitch in `README.md`. Built for the Build, Ship, Shape: Amazon Developer Hackathon 2026 (submission deadline **2026-10-23 12:00 PT**): Alexa+ track, Ring track if the item 34 gate passes, both mini-challenges (AWS Builder; Open Source through a separate repository holding an add-on conformance checker and the simulator's host harness), and designed as a startup beyond it. The project was renamed from its first name on 2026-09-17 (`CHANGELOG.md`).

## Where things live

- `README.md` — what this is, the demo story, tech stack, repo layout, quickstart. Read this first.
- `ARCHITECTURE.md` — layers, the Hirz loop and the decision pipeline (§3), canonical objects (§4), every component (§5), data model, identity, latency budget, failure modes, hardening, observability, testing, CI, deployment. Load the section relevant to the component being touched, not the whole file.
- `THREAT_MODEL.md` — what's protected, what isn't, assumptions. Load for anything touching the pipeline, constitution, risk, protect, auth, audit, or adapters that act on the world.
- `docs/constitution.md` — the constitution spec, grammar, Cedar compilation. Load for constitution or policy work.
- `docs/tool-catalog.md` — the MCP tool surface and its contract. Load for MCP server or tool work.
- `docs/twin-and-scenarios.md` — twin models, rate-plan profiles, and the scenario DSL (two demo scenarios). Load for adapter, twin, or scenario work.
- `docs/design.md` — Amazon's design tokens and display modes, per-card specs, the seven hand-designed screens, spoken-line limits. Load for any card, companion-app, simulator, or `speakable` work.
- `docs/demo-script.md`, `docs/submission.md` — the video and the hackathon checklist. Load for Phase 8 work.
- `docs/friction-log.md` — every friction point hit with a third-party tool, in Devpost's format, plus feature requests. Append to it as friction happens (see Conventions).
- `docs/adr/` — one file per decision with rejected alternatives. Load the specific ADR for the component being touched.
- `ROADMAP.md` — phased build order as a living checklist with `verify:` checks. Check at the start of a session to see what's next; update it as items complete, one sentence per item (see Where records go).
- `docs/verification-log.md` — the full evidence behind every completed roadmap item. Append to it when closing an item; read it only when the numbers matter.

## Keeping the instruction files in sync

This project ships the same guidance as `CLAUDE.md` (Claude Code) and `AGENTS.md` (Codex and other agents). They are **not** auto-generated. They are near-identical (only the top heading differs). Whenever you change one — Commands, Current phase, Conventions, or any substantive guidance — mirror the change into the other in the **same commit**.

## Where records go

Each kind of record has one home. Write it there once and link to it; never paste the same facts into a second file. This keeps `ROADMAP.md` and the instruction files (loaded every session) short without losing anything.

| Record | Home | Size | Never |
|---|---|---|---|
| What an item must build and its `verify:` check | `ROADMAP.md`, the item itself | The item's spec sentence plus the `verify:` clause | Don't rewrite the spec when it is done |
| That an item is done, and the headline evidence | `ROADMAP.md`, appended to the item | `**Complete (date).**` in front, and after the `verify:` clause **one sentence**: the two or three numbers that prove it, the CI run link if there is one, and a link to the evidence entry. A partial result says exactly what is still owed | No paragraphs, no environment details, no list of probes |
| The full evidence: commands run, every number, environment, run links, what was deliberately not claimed | `docs/verification-log.md`, one `## Item N` heading per item, newest run appended under it | As long as the truth needs; nothing is trimmed | Never edited after the fact except to append a later run |
| What changed in the repo and why, dated | `CHANGELOG.md`, `[Unreleased]` | A few lines per change; link to the ADR, item, or evidence entry instead of repeating them | Not a copy of the verification log |
| A decision with its rejected alternatives | `docs/adr/`, one file, listed in `docs/adr/README.md`; a later change is an amendment in the same file, dated | | Not in `CHANGELOG.md` alone, not only in a commit message |
| Third-party tool friction and feature requests | `docs/friction-log.md` (see Conventions) | Devpost's format, with URL and exact error text | Nothing invented or padded |
| How a component works | `ARCHITECTURE.md` section, `docs/*.md` spec | | Not in the README, not in the roadmap |
| Development and operations procedure (setup, recovery, reset, CI mechanics) | `docs/development.md` (the Phase 0 sections now in `README.md` move there before submission) | | Not in the README beyond the quickstart |
| Where the project stands right now | `CLAUDE.md`/`AGENTS.md` "Current phase" | Under about 80 words: what is done, what is next, one caveat. Details live in the roadmap and the evidence log | Not a second verification log |
| Pitch, demo story, tech stack, quickstart, pointers | `README.md` | | Not procedures, not evidence |

When closing an item: append the evidence entry first, then the one-sentence roadmap line linking to it, then the changelog line, then shorten "Current phase". If a fact is already recorded somewhere, link to it.

## Conventions

- **Python 3.12, `uv`, FastAPI, official `mcp` SDK, async throughout** for `hirz/`. **TypeScript strict, React, pnpm workspaces** for `apps/`: Tailwind + shadcn/ui for `apps/web`; plain CSS custom properties carrying Amazon's design tokens, and no component library, for the MCP App cards. **CDK in TypeScript** for `infra/`. Ruff and mypy strict for Python; eslint and `tsc --noEmit` for TypeScript. Don't introduce another language or a second web framework.
- **No LLM in any decision.** The pipeline, risk engine, constitution evaluator, planner, executor, and protect weighting are code. Models narrate (Explainer), draft (constitution English → YAML patch), and extract structured signals (Protect) behind schema validation. A model's Protect signals are unioned with the keyword extractor's, so it can add a warning and never remove one, and they feed advice only. The rule preview's situation lines are computed by evaluating both constitution versions, never written by a model. If a change routes a decision through a model, it is wrong. See `ARCHITECTURE.md` §5.3, §5.4, §5.7, §5.8.
- **No ML risk scoring.** The risk table and factors are the deliberate design (ADR-004), not a gap to fill.
- **The constitution grammar is non-Turing-complete.** No loops, functions, recursion, arithmetic beyond literal comparison. Don't "helpfully" extend it.
- **One canonical shape per object.** `Action`, `Decision`, `Plan`, `AuditEvent`, `VerificationCase` are defined once in `ARCHITECTURE.md` §4 and `hirz/pipeline/models.py`. Don't invent a new response shape for a new endpoint or tool.
- **Every state change goes through the pipeline** and produces an audit row. There is no admin path, script, or test helper that executes an action without a `Decision`. **Approved item 6 bootstrap exception (2026-09-18):** initial synthetic data for the two demo households and repository tests may write graph rows before items 9–10; this never authorizes a device action, policy activation, runtime mutation surface, or fabricated audit event (ADR-002). **Approved item 15 test bootstrap (2026-09-20):** initial HA bindings, explicit synthetic room metadata and one-time input observations may be installed in uniquely named disposable smoke/test databases before execution; every device write, including restoration, still requires a real Pipeline grant (ADR-006).
- **Fail closed** for anything whose failure would weaken a guarantee (Postgres, audit write, boundary evaluation, risk exception). If unsure whether something fails open or closed, it's closed. `ARCHITECTURE.md` §9.
- **Twin is labeled.** Every observation carries `source: real | real API, demo devices | twin`; tool outputs and detail views show it. Cards show two states, `live` and `simulated` (anything not plainly `real` shows as simulated). A published rate table is `real (published ComEd rate)`, never "live". Never present twin data as real. Hosted-demo households bind `twin` adapters only. Falling back from a real device to its twin is a scenario and demo feature: in a real household an unreachable device is `unavailable; actual state unknown`, and a twin read-back never verifies a real device.
- **No Hirz process outside the home holds a device credential in AWS mode.** The Home Assistant token stays with Hirz Link in the house; the home obeys only commands signed by the KMS key that only the `hirz-actions` Lambda role may use; write-capable cloud credentials are readable by that role only. A change that hands the worker or the `mcp` role something it can act with is wrong (ADR-009). Local mode has no outside boundary and is labeled `dogwood-local`. The claim covers bugs and bypass paths, not a compromised worker (`THREAT_MODEL.md`; ADR-010 and item 38d narrow that for `security.*`). The signer recomputes the action hash and never trusts the worker's; a command names one home and runs once; and Link owns the ending of a bounded operation, so a relock never depends on the cloud. Hirz governs the actions Hirz takes: never write that it controls everything Alexa can do.
- **A voice proposes, a phone activates.** Rule changes spoken to Alexa are proposals (`propose_household_rule`); activation is passkey-gated in the companion app. Same principle as security approvals.
- **A fair comparison, without hindsight.** The headline saving is against the timer schedule a careful household already uses, with "do everything now" and the cheapest-slots heuristic beside it, all held to the same comfort, delivered EV energy, and final battery state. The backtest plans only from what was knowable at the time and bills at realized prices, and it includes a home with no solar or battery.
- **Numbers are derived, never typed.** Every dollar and kWh figure in the product, the README, the video, and the Devpost text comes from a cited scenario run or the backtest in `scripts/`; rate tables carry their source URL and effective date.
- **Roles bind to linked accounts, never to voices.** Alexa gives add-ons no speaker identity, so an Echo is a shared device. `security.*` classes are never approvable by voice (approval is in the companion app under a passkey; the validator rejects `alexa` in their `ask_channels`), claimed identity and any speaker hint only lower authority, and Hirz never does its own speaker or face recognition. Provenance is the linked account and the surface; a name inside a sentence is `claimed_author`, shown as claimed. A schedule is context, never identity: no string says who is at the door ("Someone is at the front door. Mom is expected now."). See `ARCHITECTURE.md` §7 and `docs/constitution.md` §2.5.
- **Every tool input is flat** (enums and scalars in consumer language; no free-form objects, no internal class names). **Every tool output has `speakable`** with a headline of about 20 words or fewer, ≤ 5 options, and no internal IDs or JSON in consumer strings. A `speakable` never states what Hirz was not told (a caller's number), never promises an outcome the boundary has not yet allowed, and never assumes Alexa can speak later: a delayed result (a contact's reply, a re-plan) reaches the card and the phone, and is spoken only when the member asks again. Every tool stays under the latency budget (`ARCHITECTURE.md` §8) by never calling a model, a solver, or a third-party network inside the call.
- **Real API contracts, verbatim.** Alexa+ (MCP 2025-11-25, Streamable HTTP, OAuth 2.1 PKCE S256, PRM; the add-on design guide's tokens and display modes, `docs/design.md`), AgentCore (Runtime `/mcp` on 8000, CUSTOM_JWT, Gateway policy session header, Cedar/Dogwood quotas), Ring (HMAC-SHA256 webhooks), ComEd, Open-Meteo. When a doc is unclear, fetch it and cite it in the ADR or the code comment; don't guess an API shape.
- **Secrets** only in `.env` (local) or AgentCore Identity (AWS); the audit key uses a mounted secret in deployment. Locally, `AUDIT_SIGNING_KEY` is quoted multiline unencrypted PKCS#8 P-256 PEM in regular, nonsymlink `.env` mode `0600`, generated by explicit initialization only after confirming no audit history and a consistent or completely unmigrated schema. Never replace a malformed key or regenerate over audit history; restore the original. Never put secrets in the graph, the constitution, audit payloads, tests, or docs.
- **AWS spend is bounded.** Pay-per-use services plus exactly two always-on ones, RDS and the worker service (ADR-008, approved 2026-09-16), all deployed for the judging window and destroyed after. Approved pay-per-use additions (2026-09-17): one KMS signing key, one S3 Object Lock anchor bucket, the community Skill bridge's stack for the recording only, Bedrock usage by the rate-limited hosted demo, the `hirz-passkeys` Lambda with its Parameter Store entries (item 38d), and the one-minute EventBridge rule that drives the worker's tick. Don't add another always-on AWS resource without asking.
- **`THREAT_MODEL.md` rows move only when earned.** A row becomes "Yes" when the item that earns it is built and its `verify:` check passes. Claims never outrun code.
- Relative dates in docs are absolute (`2026-10-23`), never "next week".
- **Friction log, from day one.** Devpost gives up to a 10 percent bonus for it, so it is the cheapest score in the project. Anyone, human or agent, appends an entry to `docs/friction-log.md` at the moment a third-party tool, API, SDK, doc, or CLI did not do what its docs said, cost more than about 15 minutes, or forced a workaround. Log it then, not at the end of the session, because sessions end without warning. At the end of any task that touched a third-party tool, check whether an entry was earned and add it if missed. Entries are facts from the session with the doc URL and the exact error text; never invented, never padded. Severity: `Blocker`, `Major`, `Minor`.

## Commands

Available after Phase 0 items 1–3: dependency installs, Python and TypeScript
tests, lint/type checks, `uv build`, and the local Compose stack with explicit
initialization and service checks, Alembic migrations, and the local doctor.
Item 6 also supplies explicit demo seeding and redacted context reads. Item 7 adds
read-only constitution validation, compilation, and preview; native Dogwood setup
is in `docs/development.md`. Item 8 adds standalone Python risk scoring; its API
smoke procedure is also in `docs/development.md`. Item 9 adds the internal pipeline API and disposable `scripts/smoke_pipeline.py`
example; signed append is internal only. Item 10 adds audit verification/export and
the smoke's `--audit` option; anchors remain item 38b. Item 11 adds read-only `hirz decide` with explicit hypothetical inputs; its development-database invocation is verified. Item 12 adds the adapter contract smoke and explicit observation/room/scam preview files; schema upgrade remains manual (docs/development.md). Item 13 adds credential-free in-memory twin physics and eight read adapters via `scripts/smoke_twin.py`; general execution remains later work. Item 14 adds credential-free ComEd/Open-Meteo reads and `scripts/smoke_energy.py` (recorded by default, `--live --history-month 2026-08` for network verification); ingestion remains later work. Item 15 adds local HA reads/subscriptions and single-attempt Pipeline writes via `scripts/smoke_ha.py` (recorded by default, `--live-demo` or explicitly mapped `--live-plug`); live checks use disposable databases and retain audit exports. The physical plug gate remains pending; migrations stay explicit. Item 16 adds offline `hirz scenario run|step`, recorded simulated policy patches, observation assertions and redacted JSON reports; native Dogwood is required for simulated activation. Tool execution, persistence and full-demo assertions remain deferred. Item 17 adds read-only `scripts/smoke_planner.py` (`--live-weather` is separate), offline `scripts/backtest.py` (`--fetch` downloads; `--verify` reproduces retained outputs), and two planning-scenario snapshots. Historical completion and billing coverage are reported separately. Item 18 adds the internal Coordinator service, audited constraint intake/history and `--scope constraints` reads, plus `scripts/smoke_coordinator.py` with explicit twin holds and signed audit export. Item 19 adds durable local plan consent/revision/cancellation, queued Pipeline actions, bounded endings, twin checkpoints and `hirz worker`; `scripts/smoke_executor.py` verifies a separate twin worker or `--live-demo` HA restoration. Migrations `0006_coordinator_constraints` and `0007_execution_lifecycle` remain manual; item 19a adds durable refresh inputs/jobs, automatic local refresh, inherited consent, held reads and reservation transfers. `scripts/smoke_refresh.py` verifies separate-worker twin or live HA demo restart, restoration and signed exports in disposable databases. Migration `0008_plan_refresh` also remains manual. Item 20 adds internal private session memory, a recorded-only provider interface and subject-app consent for temperature preferences; `scripts/smoke_memory.py` verifies twin planning, a fresh worker and signed exports in a disposable database. Migration `0009_memory` remains manual; no public memory CLI, companion authentication or AWS integration is added. The other commands below remain target state.
The verified toolchain and scaffold setup are in `README.md`; use Node 24.

- `uv sync` — install Python deps; `pnpm install` — install workspaces.
- `uv sync --locked` / `pnpm install --frozen-lockfile` — reproduce locked dependencies; `uv build` — build the Python sdist and wheel.
- `uv run python scripts/init_dev.py` — initialize local credentials and HA demo onboarding; preserves existing state.
- `docker compose -f compose.dev.yml up -d` — Postgres 16 + Home Assistant (demo integration) + Hirz liveness server.
- `uv run python scripts/check_dev.py` — authenticated database/HA checks and `/health`; `--observability` also checks a disposable trace after starting the optional Jaeger profile.
- `docker compose -f compose.dev.yml --profile observability down` — stop services, preserving named volumes; README documents recovery and the separate destructive reset.
- `uv run alembic upgrade head` — explicit local migrations; never applied at startup. `downgrade base` destroys the application tables and graph history and is for disposable data only.
- `uv run hirz seed constitutions/quinn-home.yaml constitutions/quinn-parents.yaml` — explicit synthetic bootstrap; unchanged seeds are no-ops, evolved households are refused.
- `uv run hirz context <household-uuid> --scope all` — redacted graph reads; `--scope member --member <uuid>` and timezone-aware `--as-of` are supported. Procedures in `docs/development.md`.
- `uv run hirz doctor` — four read-only local checks: Postgres, HA demo entities, P-256 signing probe, migration head/table/materialized-view presence. Exit 0 only if all pass; no `--aws` or constitution check yet. Those checks remain target state.
- `uv run hirz decide --household <uuid> --as malik --surface alexa --action energy.hvac_adjust --adapter twin --entity hvac.living_room --zone <zone-uuid> --params '{"target_f":72}'` — hypothetical preview of a stored, unactivated policy; optional `--cost`, `--at`, `--evidence`, and `--requester-confirmed`. Required observation/evidence setup and exit codes: `docs/development.md`.
- `uv run python scripts/smoke_twin.py` — verify in-memory twin physics, eight read adapters and source labels; no database or device actions.
- `uv run python scripts/smoke_energy.py` — recorded energy-feed reads; `--live --history-month 2026-08` opts into public APIs, `--tariff-file PATH` supplies a reviewed tariff explicitly. No database or device actions.
- `uv run python scripts/smoke_ha.py` — credential-free recorded HA smoke; `--live-demo --audit-output <new-file>` verifies/restores demo devices through native Dogwood and signed audit; `--live-plug --config <mapping.yaml> --audit-output <new-file>` requires the physical mapping. Procedures: `docs/development.md`.
- `uv run python scripts/smoke_coordinator.py --audit-output <new-file>` — five coordinator gates in a disposable database, native Dogwood and offline signed-audit verification; no device actions or development-database upgrade. Procedures: `docs/development.md`.
- `uv run hirz worker --household <uuid> [--once]` — local durable execution; requires an explicitly migrated database and configured adapters. `uv run python scripts/smoke_executor.py --audit-output <new-file>` uses a disposable twin database and a separate worker; `--live-demo` verifies/restores HA demo devices. Procedures: `docs/development.md`.
- `uv run python scripts/smoke_refresh.py --audit-output <new-file>` — durable refresh and separate-worker restart with signed offline audit verification; `--live-demo` verifies/restores HA demo settings. Both use disposable databases; development stays unmigrated. Procedures: `docs/development.md`.
- `uv run python scripts/smoke_memory.py --audit-output <new-file>` — consent-gated temperature preferences, private session persistence and fresh-worker twin refresh with an independently verified signed export; disposable database only. Procedures: `docs/development.md`.
- `uv run hirz scenario run scenarios/demo-evening.yaml --speed 60` — paced simulated trace; `--headless --assert` verifies item 16 observations; `--output <new-file>` exports a report. `hirz scenario step <file> --to "18:40"` (or `run --step`) replays and exits before target-time events; later checks are not reached. Procedures: `docs/development.md`.
- `uv run hirz verify-audit --household <uuid>` / `uv run hirz audit export --household <uuid> [--range START:END] --output <new-file>` — full-chain verification and private exports. Offline: `hirz verify-audit --household <uuid> --file <export> --public-key <pem>` (or `--trusted-fingerprint <hex>`). `--anchors` remains item 38b; procedures in `docs/development.md`.
- `docker compose -f compose.link.yml up -d` — Hirz Link beside Home Assistant, in the home (AWS mode).
- `uv run python scripts/backtest.py` — the year-long rate-plan backtest every published savings figure comes from.
- `uv run python scripts/build_dogwood.py` — build the pinned native CLI (Rust/Cargo required); `export HIRZ_DOGWOOD="$PWD/.tools/dogwood"` enables local checks.
- `uv run hirz constitution validate|compile constitutions/quinn-home.yaml [--gateway-resource hirz-local]` — database-free JSON output, native policy validation; reports `not analyzed: local mode`.
- `uv run hirz constitution preview OLD NEW` — deterministic situation differences; no activation. `analyze`/`activate` remain later work.
- `uv run pytest` — service-free tests (80% coverage gate); `uv run pytest -m integration --no-cov` — live PostgreSQL tests in uniquely named disposable databases; `uv run pytest tests/latency` — budget; `uv run pytest tests/cedar_conformance` — YAML/native Dogwood agreement; AWS comparison remains item 37.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy hirz/ scripts/ alembic/`.
- The add-on conformance checker (separate open-source repository, name to be chosen) run against the local MCP server.
- `pnpm -r lint && pnpm -r typecheck && pnpm -r test`; `pnpm --filter web dev` (companion pages + simulator route), `pnpm --filter mcp-app build`.
- `cd infra/cdk && pnpm cdk deploy` / `pnpm cdk destroy` — the AWS stack for the judging window.
- `HIRZ_LLM=off|bedrock`, `HIRZ_ADAPTERS=devices:ha,ev:twin,energy:real,...` — runtime configuration.

## Current phase

**Phase 3 item 20 is locally verified; item 21 is next.** Private Postgres sessions and consent-gated temperature preferences now feed coordinated plans through atomic refresh. Item 15's physical plug/absence checks remain pending. Evidence: `docs/verification-log.md`; procedures: `docs/development.md`. Development remains on `0005_execution_attempt`; migrations 0006–0009 are manual. Companion authentication/UI, AWS Memory, automatic extraction and remote CI remain unverified.

---

## 1. Ask before deciding

**Don't assume. Don't hide confusion. Surface tradeoffs. Ask.**

The author's standing instruction for this project: **when a question comes up, ask rather than decide, assume, or guess.** That includes product choices, naming, scope, API shapes not covered by a doc, which adapter to make real, what to cut, and anything about money (AWS spend) or the hackathon submission.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them; don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

This project's design has been reviewed and most ambiguity is resolved in writing in `ARCHITECTURE.md`, `THREAT_MODEL.md`, `docs/`, and `docs/adr/`. Check there first; if it's genuinely not covered, that's exactly what to surface. Batch questions when you can, so the author answers once.

## 2. Simplicity first

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked and what the current `ROADMAP.md` phase calls for. Don't pull forward a Phase 5 feature while working on Phase 2.
- No abstractions for single-use code. No plugin systems where a function list will do (the adapter registry and the risk table are deliberately plain).
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios; do implement the fail-closed handling `ARCHITECTURE.md` §9 explicitly calls for.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical changes

**Touch only what you must. Clean up only your own mess.**

- Don't "improve" adjacent code, comments, or formatting. Don't refactor what isn't broken. Match existing style.
- If you notice unrelated dead code, mention it; don't delete it.
- Remove imports/variables/functions that *your* change made unused. Leave pre-existing dead code unless asked.

The test: every changed line traces to the current task or `ROADMAP.md` item.

## 4. Goal-driven execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add the TOCTOU guard" → "Write a test that mutates params between approval and redemption and asserts `DENY_APPROVAL_MISMATCH`, then make it pass."
- "Add the EV twin" → "Write a test that 34→50% at 7.4 kW takes 100–110 minutes, then make it pass."
- "Wire the planner" → "The demo scenario's headless assertion passes with savings in range."

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
```
`ROADMAP.md` already carries a `verify:` per item and `ARCHITECTURE.md` §12 defines the test strategy; use them as the source of success criteria instead of inventing new ones per task.

## 5. Run it and show it

**Nothing is done until it has been run and the output is shown.**

The author's second standing instruction: **after building a feature, run and verify it, and report what you saw.** Concretely:
- Run the relevant tests and paste the summary line (passed/failed/coverage).
- Run the format check last, after the evidence log is written, because ruff formats fenced Python in Markdown.
- Run the feature the way a user would: the CLI command, the scenario, the tool through MCP Inspector or the client SDK, the page in the browser via Playwright or a screenshot. Paste the output or describe exactly what rendered.
- If something could not be verified (no AWS credentials, no Bedrock access, a service down), say so first and plainly, and mark the item as not done in `ROADMAP.md`.
- Never write "should work", "is now complete", or tick a roadmap item on the strength of code alone.
- Report failures faithfully with the output. A failing test reported honestly is progress; a green claim that isn't is a regression.
- If the task touched a third-party tool, check `docs/friction-log.md`: was an entry earned? Add it before reporting done.

---

**These guidelines are working if:** clarifying questions come before implementation rather than after mistakes; diffs are small and traceable to a roadmap item; every completed item has a pasted verification; `THREAT_MODEL.md` never claims more than the code does; and the phase boundaries in `ROADMAP.md` hold.
