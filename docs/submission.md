# Hackathon Submission Checklist

**Scope update — 2026-10-20:** the author approved the
[Simulator submission plan](../ROADMAP.md#cut-line-and-fallbacks), supported by
the [official Alexa+ simulation option](https://amazonappdev2026.devpost.com/rules).
It supersedes the AWS-dependent readiness plan below. Item 41 must reconcile
this checklist and the submission claims before release; deferred cloud gates
remain incomplete, and the no-credential local demo replaces a hosted URL.

Build, Ship, Shape: Amazon Developer Hackathon 2026. Submission period 2026-08-31 10:15 PT to **2026-10-23 12:00 PT**. Judging 2026-11-09 to 2026-11-20. Tracks entered: **Alexa+**. Mini-challenges entered: **AWS Builder** and **Open Source**. "A project can only win one (1) track prize and one (1) mini challenge prize"; nothing stops it entering more than one.

Two-stage judging: Stage One is a pass/fail check that the project fits the track and actually calls the required technology; Stage Two scores four equally weighted criteria (Tech Implementation, Design, Potential Impact, Quality of the Idea), with up to 10 percent bonus from friction-log entries. Judges may judge from the description, images, and video alone, so those three carry the whole case.


## Readiness review — 2026-10-19

The [official rules](https://amazonappdev2026.devpost.com/rules), rechecked on
2026-10-19, retain the deadline **2026-10-23 12:00 PDT / 15:00 EDT**. Their
October 7 update closes new promotional-credit requests; the older October 21
request date below is no longer actionable. Existing eligible account credit is
verified separately before each AWS acceptance. No form submission, recording,
publication, human test or live gate is inferred from an unchecked box.

| Work | Remaining gate / next action | Can proceed while item 37 runs? |
|---|---|---|
| 37, policy boundary | Full live agreement, refusal, expiry, signed evidence and teardown; see [roadmap](../ROADMAP.md) | Supervise its single approved retry |
| 38, AWS Runtime | Finish self-service Cognito linking, Memory intake, model budgets, AWS doctor and live latency/action gates; local work is isolated on `feat/item38-runtime-integration` | Implementation and local checks; no overlapping deployment |
| 38a, Hirz Link | Signed-command execution, replay/home/expiry refusal, durable offline ending and physical plug end to end | Local code and adversarial tests |
| 15, physical device | Actual plug state/power and absent-device behavior; author will arrange hardware | Prepare [physical smoke](development.md#home-assistant-adapter-item-15), run when connected |
| 28 and 31, delivery | Real iPhone Home Screen Web Push approval and email enrollment/reply | Use [companion](development.md#companion-app-item-28-acceptance-still-in-progress) and [contact](development.md#trusted-contact-acceptance-item-31) procedures |
| 39, cost guard | Alarm/runbook and actual judging-window cost evidence | Prepare; future usage cannot be certified now |
| 40 and 40a, video and people | Under-three-minute capture; two independent viewers; 5–8 uncoached participants including two older adults | Recruit and run verified local flows now; author arranging people |
| 41, submission | Earned-claim description, tool feedback, gallery, accessible repo/judge path and completed Devpost fields | Yes; retain links to evidence instead of copying it |
| 42, release | Final tag/release notes and another person's clean-machine quickstart reaching the plan card | Prepare instructions; final validation follows final code |

Existing fallbacks remain in the roadmap: anchors (38b), boundary passkeys
(38d), tamper playground (38e), hosted demo (38c) and credibility clips (41a)
have explicit cut/defer rules. This review does not choose a cut or change their
scope. The video close depends on Link, and the live badge on the lamp depends
on physical evidence. Do not record either as completed before its gate passes.
The no-credential local path is the current judge path; a hosted Start demo URL
is still a separate gate.

Working targets, not completion claims: finish implementation and begin physical
and delivery checks on 2026-10-20; resolve live gates and human-test findings on
2026-10-21; record, review and upload on 2026-10-22; reserve 2026-10-23 for final
form/link checks. AWS analysis time remains uncertain; report slippage and obtain
an explicit scope decision rather than silently cutting or claiming success.

---

## Required components

- [ ] **Working project** built with the required tech: a self-hosted MCP server (spec 2025-11-25 or later, Streamable HTTP) actually called by the demo.
- [ ] **Public GitHub repo** with all source, assets, run instructions, and `LICENSE` (Apache-2.0) detectable at the root.
- [ ] **Demo video** under 3 minutes, YouTube or Vimeo, public, English, showing the project functioning on the intended surface (the simulator, honestly labeled; the Alexa developer-console clip is in the gallery, not the video). No third-party trademarks or copyrighted music. See `docs/demo-script.md`.
- [ ] **Text description** of features and functionality (draft below).
- [ ] **Product feedback** for every tool/API/SDK used (template below).
- [ ] **Track selection**: Alexa+.
- [ ] **Mini-challenges**: both.
  - **AWS Builder**: the services and how they are used, in the product-feedback answer: AgentCore Runtime (hosts the MCP server), Gateway + Policy (Cedar/Dogwood compiled from the constitution, temporal approval rule), Memory, Identity (write-capable credentials readable by one Lambda role only), Bedrock (Claude for narration and drafting, the emulator), Strands, KMS, S3 Object Lock, EventBridge Scheduler, Fargate (the approved worker topology), RDS, CDK. This is the planned inventory: final feedback must distinguish provisioned resources from verified integrations; command signing, anchors and remaining item 38 live gates are not yet earned.
  - **Open Source**: the rule asks for "a new, **additional** open-source project or [a contribution] to an existing public repository during the hackathon window, **alongside** a primary track submission". Hirz is the primary submission, so Hirz itself does not qualify. The entry is the separate repository from `ROADMAP.md` items 25a and 29a: the add-on conformance checker and the host harness extracted from Hirz's simulator. The form's four fields: **contribution URL**, **project repository URL**, **GitHub username**, and a description of **what it does, how it works, and why it matters** (add-on developer access is limited to select partners, so builders test against emulated hosts; the checker tells any add-on developer in one command whether their server meets Amazon's published contract. The claim is about what the checker verifies, with its test suite as evidence, never about other entrants' simulators). The rules rate "feature addition with tests, bug fix that unblocks other developers, new integration pattern" above "README update, typo fix". The MCP Python SDK User-Agent pull request, if still open, is listed as a small extra and never leads. Dogwood Python bindings are decided after the item 7 gate.
- [ ] **Judge access**: the hosted demo URL in the testing-instructions field (one click seeds a throwaway household on simulated devices only); repo + video; a no-credential run path (`HIRZ_LLM=off`, twin adapters, `compose.demo.yml`) documented in the README; the AWS stack live for the judging window with a read-only console screenshot set in `docs/img/` in case it must be torn down.
- [ ] **Image gallery**: the seven hand-designed screens (plan, verification, doorbell, and scorecard cards; the rule diff, check-in, and unlock approval on the phone); the AWS console screenshots (AgentCore Policy engine with the compiled constitution, a CloudWatch policy decision beside the signed command the home accepted, the KMS key policy showing one role, the Runtime hosting the MCP server); a refused unsigned command and the refused replay from the video's close (`LINK_REJECTED`); the tamper playground; the rule diff with its derived situation lines; the backtest table with all three baselines and the car-only household; the hallway-test results with their sample size; the courier-correlation warning if it is not in the video; the Dad/dishwasher provenance plan; the Cedar view; the Alexa developer-console clip frame; the same cards in a second real MCP Apps host. The video does not tour the console; the gallery is where AWS Builder judges look.
- [ ] **Newly created during the period** statement: repo created 2026-09-15, all code written during the submission window.
- [ ] **AWS promotional credit record**: confirm the original request/award record; new requests closed on 2026-10-07 per the official rules. Existing enabled credit is checked before deployment.
- [x] **Forum question** to the organizers about MCP Toolkit or simulator access posted, and the dated answer recorded in `docs/friction-log.md`: no participant access exists; a self-built simulator is an accepted path (answered 2026-09-17).

## Optional, worth doing

- [ ] **Friction log entries** (up to 10 percent bonus) and **feature requests**: maintained continuously in `docs/friction-log.md` (see the rule in `CLAUDE.md`). At submission, copy the entries and requests into the Devpost form.

---

## Checked sources and repository access — 2026-10-19

Both [Hirz](https://github.com/BashaarJavaid/Hirz) and the additional
[addon-check project](https://github.com/BashaarJavaid/addon-check) are public and
GitHub detects Apache-2.0 licenses. Both default to `main`; final submission must
link the actual reviewed release revision after the local item 38 work is
integrated. Public visibility alone does not certify that unreleased local code
is available to judges. The retained [companion smoke shutdown issue #7](https://github.com/BashaarJavaid/Hirz/issues/7)
is still open; do not describe it as fixed.

The README's impact figures were rechecked against primary sources: the
[FTC imposter-scam report](https://www.ftc.gov/news-events/news/press-releases/2026/06/ftc-data-show-people-reported-losing-3-point-5-billion-imposter-scams-2025)
supports the reported 2025 losses; its
[older-adult report](https://www.ftc.gov/news-events/news/press-releases/2025/12/ftc-issues-annual-report-congress-agencys-actions-protect-older-adults)
supports the 2020–2024 comparison. The
[National Alliance for Caregiving/AARP report](https://www.caregiving.org/research/caregiving-in-the-us/)
supports the caregiver prevalence. These are population context, not a measured
Hirz impact or evidence that Hirz prevents losses. The original AARP `.html` URL
returned HTTP 403 to the review fetch; the co-publisher provides the same report.

For the Open Source form, use contribution/project URL
`https://github.com/BashaarJavaid/addon-check` and GitHub username
`BashaarJavaid`. Draft: “addon-check verifies an MCP server against the published
add-on contract, and its companion host package renders MCP Apps and handles
OAuth independently of Hirz's household logic. Tests include deliberately broken
servers and a non-Hirz reference server. It gives builders a reusable way to check
and exercise add-ons while access to the Alexa+ host is restricted.” Link the
published versions and the [item 25a/29a evidence](verification-log.md) in the
final form; no form has been submitted by this review.

## Description (draft)

> **Hirz: house rules for the AI in your home, and your parents'.**
>
> Hirz lets a family decide what Alexa may do on its own, what it must ask about, and what it may never do. It is built for the person who runs the smart home at their own place and at their parents' place. People reported losing $3.5 billion to imposter scams in 2025 (FTC), and 63 million Americans are family caregivers (AARP). Hirz is rules, not care: it does no medication or health monitoring.
>
> **Is it really him?** Mom asks her Echo whether the "Malik" who just called for money is real. Hirz checks the household's own verified records, never anything the caller said, and asks Malik through his own app. Hirz cannot see the call and says nothing about the caller's number; it asks Malik about that specific request, and he taps "No, that wasn't me." When Mom asks again, Alexa tells her. Hirz does not stop scam calls; it gives Mom one thing to do: ask first. If someone unexpected then turns up at her door, Hirz warns her and tells Malik.
>
> **The household writes the boundary.** Malik says, "From now on, never unlock the door for someone we're not expecting." Hirz drafts the rule and sends it to his phone: one English sentence, what changes in concrete situations (computed by running the old and new rules, never written by a model), the compiled policy. He activates it with a passkey. Anyone in the room can propose a rule; only a person on their own phone can activate one. An hour later the rule refuses an unexpected visitor, and the same lock opens at 7:04 after an approval on a phone that says "Mom is expected now", not "this is Mom" (a schedule is context, not identity), never by voice, because an Echo is a shared device and Alexa does not tell add-ons who is speaking.
>
> **A household-authored boundary, with explicit verification limits.** Constitutions compile to Cedar/Dogwood and govern the deterministic pipeline. AgentCore publication is implemented, but full live AWS boundary agreement remains item 37. Signed commands, home-side replay refusal and an offline relock are the Hirz Link design in item 38a; they are not verified features at this checkpoint. Update this paragraph from the acceptance evidence before recording or submission. Hirz governs the actions Hirz takes; devices controlled directly elsewhere are outside that boundary.
>
> **A real planner over real prices.** A MILP schedules the EV, home battery, HVAC, and appliances against the household's real rate plan, all-in, and live weather, and reports savings against the timer schedule a careful household already uses, with the same comfort and the same energy delivered. Every figure comes from a cited run or from a backtest over a year of price history that plans without hindsight and includes a home with no solar or battery; simulated devices are a labeled physics twin. Each member's constraint keeps its owner through the plan, the explanation, and the audit row. No model makes a decision: authorization, risk, and planning are code. Models narrate, draft rule text a person must activate, and may add warning signals to a scam check, never remove one.
>
> Built on MCP 2025-11-25 (Streamable HTTP, OAuth 2.1 PKCE, MCP Apps following Amazon's add-on design guide), Python and TypeScript, PostgreSQL, Amazon Bedrock, and Amazon Bedrock AgentCore infrastructure, with Runtime/Memory integration and signed home commands still awaiting their live gates, with an Alexa+ simulator that hosts the real MCP server through an emulated orchestrator because add-on developer access is limited to select partners. The simulator's host harness and an add-on conformance checker are published as a separate open-source project.

## Product feedback draft — 2026-10-20

These are factual draft notes for the final form, limited to retained evidence.
Each friction link owns the exact error, date, workaround and feature request;
copy from that record when completing the form. No onboarding duration was
measured consistently enough to report. The author still supplies their own
“would build with it again” answer; these notes do not invent that endorsement.

| Tool / API | What Hirz used and verified | Feedback / remaining limitation |
|---|---|---|
| Alexa+ MCP contract / Toolkit | Published contract informed the real MCP server, independent checker and emulated host. | Participant Toolkit access was unavailable; request a public test host. The organizer-approved Simulator is not a test on Alexa+ itself ([record](friction-log.md#entries)). |
| Alexa+ add-on design guide | Tokens/display modes informed the five MCP cards; item 27 retains reference-host captures and checks. | Keep implementable token/display examples alongside the contract. Actual Alexa display acceptance remains unavailable ([evidence](verification-log.md#item-27-closure--2026-09-24)). |
| MCP Apps SDK | Cards use the host bridge; the extracted harness also renders a non-Hirz reference card. | Published-package compatibility needs old-phone coverage; the retained syntax workaround is in the [friction record](friction-log.md#item-29-bridge-dependency-syntax-blanks-the-older-companion-phone--2026-09-26). |
| MCP Python SDK | Real HTTP initialization, authenticated tools, OAuth and card resources are covered by SDK/browser checks. | Per-call validation had measurable latency; keep performance attribution visible rather than bypassing validation ([record](friction-log.md#item-26b-sdk-per-call-schema-validation--2026-09-24)). |
| AgentCore Runtime | Acceptance infrastructure provisions Runtime; application composition and resource-bound auth are locally tested. | Full application warm/cold latency and action acceptance remain item 38. No Runtime performance claim is available ([evidence](verification-log.md#item-38)). |
| AgentCore Gateway + Policy | Typed private tools, publication/recovery and correlated decision-evidence collection are implemented; full live acceptance is still running. | Strict whole-engine analysis, slow publication and paginated traces need clearer operational guidance; use the exact [item 37 records](friction-log.md#item-37--login-expiry-interrupted-long-policy-analysis--2026-10-18). |
| Dogwood | Native validation/replay is the local equivalence reference; startup-prepared native policies satisfy the local latency gates. | Repeated native compilation was costly; document reuse of prepared policies without reusing authorization decisions ([record](friction-log.md#item-26-repeated-native-compilation-in-local-replay--2026-09-23)). |
| AgentCore Memory | Scoped provider/strategy composition and subject consent are locally tested; PostgreSQL remains the canonical record. | Live extraction and cost controls remain gates. Provisioning/rollback behavior deserves clearer recovery instructions ([record](friction-log.md#item-37--memory-creation-blocks-cloudformation-rollback--2026-10-17)). |
| AgentCore Identity | Item 36 verified scoped IAM denial and a signer-role positive control using a nonfunctional synthetic credential. | This is credential-boundary evidence, not a working cloud-device integration ([decision](adr/ADR-009-signed-commands-home-agent.md#item-36-infrastructure-secret-exception--2026-10-16)). |
| Bedrock: Claude / Nova | Haiku-backed tool selection and Simulator gates passed under retained ledgers; narration/drafting use validated outputs and safe fallbacks. | CountTokens and schema compatibility need model-specific guidance. Nova acceptance is deferred; do not present it as passing ([records](friction-log.md#item-29-nova-lite-cannot-satisfy-pre-inference-token-counting--2026-09-26), [schema record](friction-log.md#item-29-nova-tool-schema-restrictions--2026-09-27)). |
| Strands Agents SDK | The Simulator's orchestrator selects tools while Hirz code retains all authorization and execution decisions. | Tool-control placement needs concrete provider examples; the successful native request shape is retained ([record](friction-log.md#item-29-bedrocks-native-single-tool-control-placement--2026-09-26)). |
| AWS KMS | Item 36 provisions a P-256 signing key and verifies IAM separation; item 38a now tests the digest signer contract locally. | Actual command signing and Link acceptance are pending. Do not claim a live signed device command ([decision](adr/ADR-009-signed-commands-home-agent.md#item-38a-local-command-foundation--2026-10-20)). |
| Cognito | Resource-bound JWT verification, passkey-gated member linking and pinned Simulator PKCE are locally tested. | Explicit cross-origin endpoints and omitted discovery capabilities need documented host support; live login acceptance remains pending ([record](friction-log.md#2026-10-19--cognito-discovery-differs-from-the-pinned-hosts-single-origin-assumption)). |
| CDK / Fargate / RDS | Item 36 deployed the approved private worker/database topology and verified its teardown. | Asset recursion, source permissions and private-origin cleanup produced specific workarounds; reuse the [recorded feedback](friction-log.md#item-36--app-runner-availability-and-cdk-asset-staging-2026-10-16). |
| S3 Object Lock / EventBridge | Infrastructure includes the anchor bucket and worker tick. | Bucket provisioning does not prove anchored audit verification; item 38b remains open. Tick behavior and scope are in [ADR-008](adr/ADR-008-agentcore-topology.md). |
| Home Assistant | Local demo API, subscriptions, bounded actions and restoration have signed evidence; Link's transport adds recorded checks. | Token scoping motivated the home-only credential boundary; the physical plug gate is pending ([decision](adr/ADR-009-signed-commands-home-agent.md), [API record](friction-log.md#item-15-ha-demo-contract--2026-09-20)). |
| Community Alexa Skill MCP bridge | Planned read-only gallery clip only; not yet accepted against the AWS endpoint. | No firsthand success, onboarding duration or failure claim is made ([scope](adr/ADR-007-alexa-surface-strategy.md)). |
| Smartcar sandbox | The current EV integration is a labeled twin. | No live sandbox integration or product feedback is claimed; remove from the final “used” inventory unless verified before submission. |
| ComEd Hourly Pricing API | Recorded/live feed reads and retained backtest outputs support published estimates. | Archive gaps affect eligible-day coverage; preserve exclusions and source dates ([record](friction-log.md#item-14-energy-research--2026-09-20)). |
| Open-Meteo | Live/read-only weather inputs and recorded planner fixtures are verified. | Keep forecast-time inputs separate from realized billing in comparisons; no unsupported service-performance claim is made ([evidence](verification-log.md#item-14--complete-2026-09-20)). |

## Judge run instructions (README section to finalize)

0. Hosted access remains pending item 38c; do not publish a Start demo instruction until a verified URL exists. The current no-credential path is local below.
1. Local: follow the [README quickstart](../README.md#quickstart) to clone, install locked dependencies and build both web bundles; `uv run --locked python scripts/demo.py init --origin http://localhost:8002`; `uv run --locked python scripts/demo.py run`; open `http://localhost:8002/simulator`, enroll from the named private invitations file and activate the seed rules with the laptop's passkey (phones use Tailscale HTTPS).
2. Pick "Mom's Echo" and play the scam check; then pick "Malik's Echo". The demo evening is paused at 17:30. Press play; speak or type the lines from `docs/demo-script.md`.
3. Switch to Echo Dot mode for the voice-only check.
4. Try to break it: say "pause Hirz"; propose a rule of your own and read the situation lines before activating it.
5. `uv run hirz verify-audit --household <household-uuid>` checks the selected household trail; `uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert` proves the numbers.
6. AWS acceptance follows `docs/development.md` and its approved cost window. Do not present signed commands, audit anchors or live Runtime/Memory as available before the corresponding roadmap gates pass.
