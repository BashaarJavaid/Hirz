# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases use
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- 2026-10-20: Adopt the approved Simulator submission scope, defer unfinished cloud gates without marking them complete, and prioritize demo, human and release checks ([decision](docs/adr/ADR-007-alexa-surface-strategy.md#simulator-submission-scope--2026-10-20-author-approved), [roadmap](ROADMAP.md#cut-line-and-fallbacks)). Record the final policy acceptance failure and independently verified teardown ([evidence](docs/verification-log.md#final-acceptance-stopped-at-gateway-evidence-teardown-verified--2026-10-20)).

- 2026-10-20: Add the local Link signature/replay journal, durable endings and recorded HA transport; production relay and device acceptance remain pending ([decision](docs/adr/ADR-009-signed-commands-home-agent.md#item-38a-local-command-foundation--2026-10-20)).

- 2026-10-20: Move setup, recovery and CI procedures into the development guide, correct the README topology/scope and prepare evidence-based tool feedback for submission ([evidence](docs/verification-log.md#item-41)).

- 2026-10-19: Prepare a private, read-only Runtime discovery and linked-household smoke for item 38; live invocation and the full AWS doctor remain pending ([procedure](docs/development.md#runtime-discovery-and-read-smoke)).

- 2026-10-19: Prepare Cognito Simulator login with pinned endpoints, current member binding and a derived callback; preserve PKCE despite Cognito's omitted discovery field ([decision](docs/adr/ADR-014-local-oauth.md#item-38-cognito-simulator-composition--2026-10-19)).

- 2026-10-19: Connect Simulator temperature suggestions to source-checked, subject-only consent through its existing model selection; paid inference remains disabled ([decision](docs/adr/ADR-002-postgres-over-dynamodb.md#item-38-simulator-temperature-suggestions--2026-10-19)).

- 2026-10-19: Record approved Simulator conversations under the freshly verified linked account through existing private, audited memory storage ([decision](docs/adr/ADR-002-postgres-over-dynamodb.md#item-38-approved-simulator-conversation-capture--2026-10-19)).

- 2026-10-19: Correct Bedrock schema compatibility without relaxing local narration or rule validation, and resolve the account-link test module collision ([evidence](docs/verification-log.md#provider-schema-compatibility-and-broad-collection--2026-10-19)).

- 2026-10-19: Keep drafting ownership until an in-flight model call settles on cancellation, preserving the queued proposal for safe retry ([evidence](docs/verification-log.md#drafting-cancellation-ownership--2026-10-19)).

- 2026-10-19: Connect Household's login button to session-bound browser PKCE and fresh passkey confirmation, with explicit callback configuration; live Cognito acceptance remains pending ([decision](docs/adr/ADR-019-companion.md#browser-self-link-flow-locally-verified--2026-10-19)).

- 2026-10-19: Add the approved self-link backend with exact Cognito proof/passkey binding and atomic, non-reassignable account mapping; browser flow and live acceptance remain pending ([decision](docs/adr/ADR-019-companion.md#item-38-self-linked-cognito-login--2026-10-19)).

- 2026-10-19: Add authenticated, subject-only temperature-preference review in Household, preserving atomic Pipeline consent and audit; production transcript capture and live extraction remain pending ([decision](docs/adr/ADR-002-postgres-over-dynamodb.md#item-38-authenticated-preference-consent--2026-10-19)).

- 2026-10-19: Connect initial and refreshed worker plans to the configured explainer, retain stale-result checks and settle in-flight SDK narration before cancellation releases ownership; AWS inference remains disabled ([decision](docs/adr/ADR-012-explainer.md#item-38-worker-narration-preparation--2026-10-19)).

- 2026-10-19: Add an optional AgentCore Memory mirror and scoped strategy configuration while retaining durable PostgreSQL turns and explicit preference consent; locally verified, not deployed ([decision](docs/adr/ADR-002-postgres-over-dynamodb.md#item-38-advisory-memory-provider--2026-10-19)).

- 2026-10-19: Wire the full authenticated MCP application into the Runtime entrypoint, preserve explicit household boundary assignments and prepare private RDS access with scoped infrastructure secrets; locally verified, not deployed ([decision](docs/adr/ADR-008-agentcore-topology.md#item-38-runtime-composition-locally-verified--2026-10-19)).

- 2026-10-19: Start item 38 with locally tested resource-bound Cognito verification, current account lookup and issuer-correct permission discovery ([decision](docs/adr/ADR-014-local-oauth.md#item-38-cognito-verification-foundation--2026-10-19)); Runtime wiring remains pending.

- 2026-10-19: Align the publication audit-export regression assertion with the corrected failure message; prelaunch CI prevented AWS deployment while it was stale ([evidence](docs/verification-log.md#prelaunch-ci-assertion-correction--2026-10-19)).

- 2026-10-19: Record the approved final policy retry and review remaining submission gates, current rules, source claims and human-test instructions ([readiness](docs/submission.md#readiness-review--2026-10-19)).

- 2026-10-19: Bound retries for the observed operator sign-in connection failure, retain fail-closed authentication, and pace throttled policy cleanup; document the recovered teardown and awake-run procedure ([evidence](docs/verification-log.md#sleep-correlated-credential-failure-and-recovered-teardown--2026-10-19)).

- 2026-10-19: Record passing repair CI/latency and the approved third, bounded item 37 acceptance window ([decision](docs/adr/ADR-008-agentcore-topology.md#additional-item-37-run-after-session-repair--2026-10-19)).

- 2026-10-19: Renew expired acceptance companion sessions through the existing passkey login before drafting; retain both households’ successful publication and the still-pending live agreement gates ([evidence](docs/verification-log.md#both-households-published-companion-session-interrupted-acceptance--2026-10-19)).
- 2026-10-19: Give the AWS worker integration fixture a fixed daytime clock so overnight CI does not accidentally test quiet-hours consent ([evidence](docs/verification-log.md#repair-ci-exposed-a-wall-clock-dependent-worker-test--2026-10-19)).

- 2026-10-18: Record credential-interrupted publication, independently verified signed exports and recovered teardown; retain the pending live acceptance gate ([evidence](docs/verification-log.md#credential-interruption-and-verified-recovery-cleanup--2026-10-18)).

- 2026-10-18: Record the first household's verified AWS activation and passing repository gates; retain incomplete live acceptance and the approved conditional continuation after teardown ([evidence](docs/verification-log.md#first-household-activation-during-full-acceptance--2026-10-18), [decision](docs/adr/ADR-008-agentcore-topology.md#conditional-additional-item-37-acceptance-window--2026-10-18)).

- 2026-10-18: Follow bounded CloudWatch trace pagination and allow measured delivery delay; batch independent acceptance sessions while retaining sequential publication, audit and aggregate limits ([evidence](docs/verification-log.md#trace-pagination-preflight-and-controlled-interruption--2026-10-18)).

- 2026-10-18: Scope the live session-invalidation fixture to one class's TTL while retaining conflict, fresh-session denial and full restoration checks; avoid republishing unrelated rules.

- 2026-10-18: Bound full policy acceptance publication by elapsed time while preserving the original global cutoff; the previous polling count expired during successful AWS analysis ([evidence](docs/verification-log.md#full-inventory-exceeded-the-acceptance-polling-bound--2026-10-18)).

- 2026-10-18: Require the faulty-compiler rejection proof to name its failed policy and recognize AWS’s documented “Overly Permissive” category; strict publisher validation is unchanged.

- 2026-10-18: Verify the minimal ordered AWS publication, signed hard-deny exception and restoration; retain the full live acceptance gate and narrow the documented analysis claim ([evidence](docs/verification-log.md#minimal-ordered-publication-and-hard-deny-exception-verified--2026-10-18)).

- 2026-10-18: Order policy publication deterministically and require signed, exact AWS rejection evidence before the approved all-roles hard-deny exception; disclose schema-only validation and retain strict checks for every permit and conditional forbid ([decision](docs/adr/ADR-003-constitution-yaml-to-cedar.md#approved-publication-ordering-and-narrow-hard-deny-exception--2026-10-18)).

- 2026-10-18: Record passing item 37 repository/latency gates, strict AWS rejection of partial publication, verified restoration and complete teardown; keep live acceptance blocked pending a revised decision ([evidence](docs/verification-log.md#exact-action-acceptance-rejected-after-passing-repository-gates--2026-10-18)).

- 2026-10-18: Apply the approved exact-action temporal compiler repair, omitting redundant unconditional-auto history permits while preserving all guards and correlations; full AWS acceptance remains pending ([decision](docs/adr/ADR-003-constitution-yaml-to-cedar.md#approved-exact-action-repair--2026-10-18)).

- 2026-10-18: Record the strict target-group rejection, native reproduction of its AWS context mismatch, and verified cleanup; keep the compiler unchanged and item 37 incomplete ([evidence](docs/verification-log.md#target-group-probe-rejected--2026-10-18)).

- 2026-10-18: Record rejected conditional policy controls, verified cleanup, and the newly approved target-group probe; correct deployment versus billing login instructions ([evidence](docs/verification-log.md#item-37), [decision](docs/adr/ADR-003-constitution-yaml-to-cedar.md#conditional-target-group-scope--2026-10-18)).

- 2026-10-17: Add item 37's shared AgentCore publisher, queued passkey activation, durable
  sessions, generated inert Gateway contract and companion publication status.
  Live acceptance is blocked by repeated AWS temporal-policy creation errors; see [the evidence](docs/verification-log.md#item-37)
  and the [ADR-003 amendment](docs/adr/ADR-003-constitution-yaml-to-cedar.md).

- 2026-10-17: Complete item 36 AWS acceptance and teardown; fix first-poll cancellation setup and restrict governance-bypass cleanup to Object Lock buckets. Physical-passkey, durable twin execution, IAM and CI evidence are retained ([verification](./docs/verification-log.md#item-36-closure--2026-10-17)); full AWS application integration remains later work.

- 2026-10-16: Verify the operator's MFA browser login and temporary `HirzDeploy` credentials through both CLI and Python SDK; direct operator EC2 access is denied ([evidence](./docs/verification-log.md#operator-login-verified--2026-10-16)).

- 2026-10-16: Add IAM-only operator setup, require MFA for the deployment role, and document temporary browser-login profiles; actual human login verification remains pending ([procedure](./docs/development.md#item-36-aws-acceptance), [evidence](./docs/verification-log.md#non-root-deployment-access-setup--2026-10-16)).

- 2026-10-16: Record the accepted item 36 tax exception and account billing/access preflight; service-charge clearance and non-root deployment setup remain required ([ADR-008](./docs/adr/ADR-008-agentcore-topology.md#tax-exception--2026-10-16), [evidence](./docs/verification-log.md#billing-and-deployment-access-preflight--2026-10-16)).

- 2026-10-16: Add item 36 CDK, twin-only AWS companion/tick composition, explicit setup, schedule reconciliation and manual acceptance/cleanup tooling. Native solver work settles on cancellation. Deployment remains blocked by the zero-out-of-pocket prerequisite; no AWS enforcement or completion claim ([ADR-008](./docs/adr/ADR-008-agentcore-topology.md#item-36-acceptance-amendment--2026-10-16), [evidence](./docs/verification-log.md#item-36)).

- 2026-10-16: The companion keyboard sweep resolves the expected and focused control together on each Tab instead of indexing a list taken before the sweep, which Household's late `/contacts` load could shift; Playwright keeps a trace on failure, and the `companion` CI job uploads only the error context ([evidence](./docs/verification-log.md#companion-focus-sweep--2026-10-16), [PR #11](https://github.com/BashaarJavaid/Hirz/pull/11)).

- 2026-10-15: Promote Phase 6 and its review fixes to `main` through PR #10 after ordinary CI and one passing normal latency dispatch ([evidence](./docs/verification-log.md#promotion-ci--2026-10-15)).

- 2026-10-15: Correct documentation drift from the Phase 6 review: Ring remnants after the failed item 34 gate, the demo courier line, the README `hirz/` layout and contact-key note, dated 2026-10-07 changelog lines, and the scam threat-model row now Partial ([evidence](./docs/verification-log.md#documentation-drift-corrected)).

- 2026-10-15: The stranger scenario now checks that the unlock result's spoken text never says who the visitor is. A unit test checks that no verification reply, real or twin, is spoken as advice to pay, and pins the genuine-reply advice sentence. The real no-answer headline drops to two sentences (`Do not send anything; call…`), so it now renders under the Speakable limit instead of failing validation ([evidence](./docs/verification-log.md#stranger-wording-guard-and-genuine-reply-negative-test)).

- 2026-10-15: The evening scenario now checks each of the five plan revisions, the guest room at 72°F, the idle dishwasher before 23:31, and the ordered 23:31 consent, nighttime votes and verified dishwasher start; the evening goes from 62 to 76 checks, with no runtime change ([evidence](./docs/verification-log.md#demo-evening-asserts-revisions-and-the-dishwasher-window)).

- 2026-10-15: Review nits: a shared `LINK_DEFERRAL` constant with a mismatch reason on the full-sequence check, intent comments on `contact_time`, the `send_allowed` scan, the `scam_pattern` evidence label and organization `trusted`, and organization cases now explain why they cannot start a person check ([evidence](./docs/verification-log.md#review-nits-deferral-constant-wall-clock-comment-scan-ceiling-evidence-label-organization-wording)).

- 2026-10-15: Record `reason: contact_removed` when a contact is removed during a twin check-in and branch on that reason instead of the stored headline text; spoken wording and the `twin` label are unchanged ([evidence](./docs/verification-log.md#twin-contact-removal-uses-the-canonical-reason)).

- 2026-10-15: Add a unit test that fails when the reserved `governance.contacts` rule and `Command.operation` name different contact operations (with `save_organization`, `guess` and `process` listed as explicit exceptions); the rule text is unchanged ([evidence](./docs/verification-log.md#contact-operation-vocabulary-cross-checked)).

- 2026-10-15: Add a unit test that fails when the Protect signal names in scoring, both advice label maps, the companion check-ins page or the card schema disagree; no signal renamed ([evidence](./docs/verification-log.md#signal-names-cross-checked-across-python-and-typescript)).

- 2026-10-15: Load the Protect worker's policy bundle only when a household has a pending or running extraction; an idle household now costs one small existence query per second instead of a policy load ([evidence](./docs/verification-log.md#protect-worker-loads-policy-only-when-work-is-pending)).

- 2026-10-15: Check the Protect budget ledger before CountTokens so a missing, foreign or exhausted ledger makes no provider call; the counted reservation and $2 ceiling are unchanged ([ADR-015](./docs/adr/ADR-015-household-tools.md), [evidence](./docs/verification-log.md#ledger-gate-precedes-every-provider-call)).

- 2026-10-15: Let the contact worker advance and time out app check-ins without `HIRZ_CONTACT_ENCRYPTION_KEY`; email check-ins and enrollment stay untouched until the key is set, and `hirz worker` says so at startup ([ADR-022](./docs/adr/ADR-022-trusted-checkins.md#app-check-ins-without-the-contact-key--2026-10-15), [evidence](./docs/verification-log.md#app-check-ins-advance-without-the-contact-key)).

- 2026-10-15: Close a self-contradictory check-in job or pending enrollment link through a Pipeline decision and audit row (reason `inconsistent_record`) and continue the worker tick; database, audit and policy failures still stop the worker ([ADR-022](./docs/adr/ADR-022-trusted-checkins.md#inconsistent-stored-records--2026-10-15), [evidence](./docs/verification-log.md#corrupt-check-in-jobs-close-themselves)).

- 2026-10-14: Complete item 35 full local scenario assertions through companion HTTP and software passkeys, persisted policy and exact request references; enforce strict completion while retaining the approved Link deferral and existing planning inputs ([ADR-006](./docs/adr/ADR-006-twin-first-adapters.md#full-local-scenario-sequences--2026-10-14-author-approved), [evidence](./docs/verification-log.md#item-35--2026-10-14)).

- 2026-10-14: Build companion assets before full scenario CI and align the existing live card browser with its scenario fixture clock, preserving production expiry behavior ([evidence](./docs/verification-log.md#live-card-fixture-clock-correction)).

- 2026-10-11: Complete item 33a: correlate fresh unexpected doorbell presses with reported CRITICAL cases, independently authorize member/contact warnings, and publish private app warnings through the shared worker; preserve check-in results and explicit simulated provenance ([ADR-024](./docs/adr/ADR-024-courier-correlation.md), [evidence](./docs/verification-log.md#item-33a--2026-10-11)).

- 2026-10-11: Complete item 33: owner-saved ComEd contacts and deterministic advisory number comparisons, preserving person workflows and historical evidence ([ADR-023](./docs/adr/ADR-023-organization-verification.md), [evidence](./docs/verification-log.md#item-33--2026-10-11)).

- 2026-10-11: Implement immediate Protect advice, private hypothetical decisions, budgeted background signal extraction and card/phone updates; complete item 32 acceptance ([ADR-015](./docs/adr/ADR-015-household-tools.md#protect-assessment-and-enrichment-amendment--2026-10-11), [evidence](./docs/verification-log.md#item-32--2026-10-11)).

- 2026-10-11: Drain simulator periodic database work before stopping its servers so acceptance cleanup can close connections safely; retain failure storage ([evidence](./docs/verification-log.md#simulator-cleanup-follow-up)).

- 2026-10-07: Record successful item 31 CI, including both latency gates, while retaining Partial status for deferred real email and iPhone push acceptance ([evidence](./docs/verification-log.md#final-ci-gates-and-retained-partial-status--2026-10-07)).

- 2026-10-07: Verify Mom’s real app check-in and Malik’s passkey reply across households, with both signed chains independently verified; email/push remain deferred ([evidence](./docs/verification-log.md#real-cross-household-app-reply--2026-10-07)).

- 2026-10-07: Verify accepted receipts in a fresh worker process and record deferred real email/push acceptance; clarify shared-Echo visibility of an initiating member’s case results ([evidence](./docs/verification-log.md#card-state-acceptance-follow-up--2026-10-07)).

- 2026-10-07: Show mailbox delivery failures and verify explicit retries on scripted Show/Dot, concurrent replies and independent channel revocation ([evidence](./docs/verification-log.md#concurrent-replies-browser-retries-and-real-delivery-limitation--2026-10-07)).

- 2026-10-07: Tighten contact retry caps and verify signed receipt rollback; let the acceptance host decline unrelated clarification forms ([evidence](./docs/verification-log.md#follow-up-checks-and-phone-pairing--2026-10-07)).

- 2026-10-07: Implement item 31 contact enrollment, real check-in jobs/receipts, private safe words and companion views; acceptance remains partial ([ADR-022](./docs/adr/ADR-022-trusted-checkins.md), [evidence](./docs/verification-log.md#item-31--2026-10-07)).

- 2026-10-07: Apply the no-credentials Ring gate fallback before Phase 6: retain the twin doorbell and remove the Ring track ([evidence](./docs/verification-log.md#item-34--ring-access-gate--2026-10-07)).

- 2026-10-07: Scope the recording credential guard to the checkout path so retained runs from another checkout no longer block initialization ([evidence](./docs/verification-log.md#per-checkout-recording-guard--2026-10-07)).

- 2026-10-06: Pass the normal latency gate for the frozen startup generation on the single approved promotion re-dispatch ([evidence](./docs/verification-log.md#promotion-dispatch--2026-10-06)).

- 2026-10-06: Verify the localhost Compose quickstart and Twin page after approved retained-run disposal, document manual recovery and successful wrapper-driven shutdown ([evidence](./docs/verification-log.md#localhost-compose-quickstart-verified--2026-10-06)).

- 2026-10-06: Cache validated companion policy bundles only within the native helper lifespan ([ADR-019](./docs/adr/ADR-019-companion.md#lifespan-scoped-policy-cache--2026-10-06)).

- 2026-10-06: Run Twin replay and push delivery in the simulator launcher and propagate database host/port overrides ([evidence](./docs/verification-log.md#b8eaf85--simulator-twin-replay-and-push-delivery)).

- 2026-10-06: Include pinned Strands and jsonschema in installed runtime dependencies ([evidence](./docs/verification-log.md#bf72ec0--runtime-dependencies)).

- 2026-10-06: Split companion pages and shared primitives/types into separate files without changing behavior ([evidence](./docs/verification-log.md#3318a41--companion-page-split)).

- 2026-10-06: Isolate the companion browser smoke in its own CI job; issue #7 remains open ([evidence](./docs/verification-log.md#d9a7dfc--separate-companion-ci-job)).

- 2026-10-06: Accept the localhost HTTP companion origin for single-machine enrollment while retaining HTTPS for phones ([evidence](./docs/verification-log.md#3495260--localhost-companion-origin)).

- 2026-10-06: Freeze the MCP startup generation under the precommitted diagnostic rule to reduce full-collection pauses ([ADR-017](./docs/adr/ADR-017-tool-latency-and-isolation.md#frozen-startup-generation--2026-10-06)).

- 2026-10-06: Record the failed Hourly latency dispatch on the promotion candidate and promote Phase 5 to main on the ordinary jobs ([evidence](./docs/verification-log.md#phase-5-promotion-dispatch--2026-10-06)).

- 2026-10-03: Complete item 30 after fresh Compose acceptance, real-phone rehearsal, independently verified shutdown, failure retention and required regression/latency CI ([evidence](./docs/verification-log.md#item-30-closure--2026-10-03)).

- 2026-10-03: Persist bounded endings with validated opening attempts so a refused opening cannot leave an orphan ending; preserve pre-dispatch durability and strict verification ([ADR-020](./docs/adr/ADR-020-simulator.md#commit-bounded-endings-with-the-opening-claim--2026-10-03)).

- 2026-10-03: Add the isolated scripted recording launcher and Compose packaging, with private credential preservation and cleanup gated on signed exports; acceptance remains in progress ([ADR-020](./docs/adr/ADR-020-simulator.md#recording-packaging-and-lifecycle--2026-10-03), [evidence](./docs/verification-log.md#item-30)).

- 2026-10-01: Close item 29a with author-approved shutdown-defect follow-up and restore the ordinary single companion CI session ([decision](./docs/adr/ADR-021-extracted-host-harness.md#closure-and-shutdown-deferral--2026-10-01), [evidence](./docs/verification-log.md#item-29a-closure-with-shutdown-follow-up--2026-10-01)).

- 2026-10-01: Run the approved bounded three-session companion CI probe to investigate intermittent teardown failure, stopping on the first error ([evidence](./docs/verification-log.md#instrumented-ordinary-ci-completed-without-reproduction--2026-10-01)).

- 2026-10-01: Capture payload-free coroutine locations when the companion smoke times out during shutdown, retaining the failure and signed-export requirements ([evidence](./docs/verification-log.md#companion-shutdown-diagnosis-authorized--2026-10-01)).

- 2026-10-01: Let the local executor recover on a later sweep when concurrent rule activation invalidates a plan before dispatch, preserving fresh authorization and fatal handling of audit/database errors ([ADR-020](./docs/adr/ADR-020-simulator.md#recover-a-refused-stale-plan-dispatch--2026-10-01)).

- 2026-10-01: Correct the plan tool's narrow MCP output contract so pending device-action approval cards reach the simulator instead of an unavailable-data error ([ADR-018](./docs/adr/ADR-018-mcp-app-cards.md#pending-action-mcp-contract-correction--2026-10-01)).

- 2026-10-01: Add opt-in, payload-free CI timing diagnostics to investigate the outstanding Hourly gate without changing acceptance criteria ([ADR-017](./docs/adr/ADR-017-tool-latency-and-isolation.md#opt-in-timing-diagnosis--2026-10-01)).

- 2026-10-01: Show the pending device-action approval card when a plan waits for consent, bind its controls to the matching plan version, and remove misleading whole-plan approval in that state ([ADR-018](./docs/adr/ADR-018-mcp-app-cards.md#pending-plan-action-presentation-correction--2026-10-01)).

- 2026-10-01: Let simulator plan-consent steps recognize audited phone approval, including consent preserved by a refresh, so a valid companion approval does not strand the walkthrough ([ADR-020](./docs/adr/ADR-020-simulator.md#recognize-audited-phone-plan-consent--2026-10-01)).

- 2026-10-01: Extract the simulator's OAuth/MCP client, card bridge, transcript and voice primitives into independent `addon-host` packages while retaining Hirz's household and consent boundaries; publish exact 0.1.0 packages on npm/PyPI and retain physical-device/final-CI acceptance gates ([ADR-021](./docs/adr/ADR-021-extracted-host-harness.md), [evidence](./docs/verification-log.md#item-29a)).

- 2026-09-27: Close item 29 for Haiku and scripted mode after regression and latency gates passed; defer optional Nova acceptance to item 29b by author approval ([decision](./docs/adr/ADR-020-simulator.md#approved-nova-deferral-and-item-29-closure--2026-09-27), [closure evidence](./docs/verification-log.md#item-29-closure-with-nova-deferred--2026-09-27)).

- 2026-09-27: Complete Haiku evening Show/Dot acceptance with verified twin end states and reviewed cards, within the approved aggregate ledger; item 29 remains partial for Nova evening and final CI ([evidence](./docs/verification-log.md#haiku-20-verification-extension--2026-09-27)).

- 2026-09-27: Reject model-selected tools absent from the current tool list and request fresh reads for the morning briefing; retain the failed final-turn acceptance evidence ([evidence](./docs/verification-log.md#haiku-20-verification-extension--2026-09-27)).

- 2026-09-27: Preserve household priorities during generic Haiku optimization, use current-plan reads for pending approvals, and reduce redundant selection context; apply the approved Haiku-only $20 aggregate verification ceiling ([decision](./docs/adr/ADR-020-simulator.md#second-haiku-only-verification-extension--2026-09-27), [evidence](./docs/verification-log.md#haiku-20-verification-extension--2026-09-27)).

- 2026-09-27: Resolve light/lamp aliases in the shared household action path; retain the failed, single authorized Nova diagnostic with the runtime still capped at 512 output tokens ([decision](./docs/adr/ADR-020-simulator.md#single-diagnostic-and-device-name-correction--2026-09-27), [evidence](./docs/verification-log.md#one-off-nova-diagnostic-and-shared-light-resolver--2026-09-27)).

- 2026-09-27: Apply the approved aggregate $10/Nova reservation amendment, make host steps explicit, and recognize combined risk/contact verification in playback ([ADR-020](./docs/adr/ADR-020-simulator.md#approved-spending-and-nova-counting-amendment--2026-09-27), [evidence](./docs/verification-log.md#approved-inference-amendment-and-nova-parents-acceptance--2026-09-27)).

- 2026-09-27: Extend simulator acceptance for real prompt expiry, late replies, authority changes, accepted-action reconciliation and fail-closed inference budgeting; reconfirm the Nova counting blocker without inference spend ([evidence](./docs/verification-log.md#remaining-acceptance-probes--2026-09-27)).

- 2026-09-27: Report blocked planning honestly, require accepted consent before advancing scenario approval beats, and retain the successful real-phone twin unlock/relock ([ADR-020](./docs/adr/ADR-020-simulator.md#rejected-consent-and-blocked-planning-amendment--2026-09-27), [evidence](./docs/verification-log.md#blocked-planning-and-stale-approval-regression--2026-09-27)).

- 2026-09-27: Share executor/dispatch expiry checks so phone-approval waiting does not consume a bounded unlock's duration; render actual phone-approval availability and retain the failed manual run ([ADR-020](./docs/adr/ADR-020-simulator.md#delayed-phone-approval-amendment--2026-09-27), [evidence](./docs/verification-log.md#manual-approval-crash-and-dispatch-regression--2026-09-27)).

- 2026-09-27: Accept omitted apostrophes consistently in recorded simulator requests and playback matching ([evidence](./docs/verification-log.md#recorded-utterance-apostrophes--2026-09-27)).

- 2026-09-27: Record green simulator regression CI and both timing gates; preserve the outstanding model and manual acceptance limits ([evidence](./docs/verification-log.md#final-source-ci-and-resumed-manual-acceptance--2026-09-27)).

- 2026-09-26: Keep fullscreen cards within the actual browser height and explain recorded-patch version conflicts ([evidence](./docs/verification-log.md#fullscreen-sizing-and-first-completed-latency-gate--2026-09-26)).

- 2026-09-26: Recheck membership for MCP stream reconnects and elicitation replies; keep installed-app simulator navigation within its existing companion session and report specific playback blockers ([ADR-020](./docs/adr/ADR-020-simulator.md), [evidence](./docs/verification-log.md#final-painted-capture-and-current-membership-probes--2026-09-26)).

- 2026-09-26: Preserve MCP session headers and SSE media types in the reference-host test relay; retain explicit model fallback and partial acceptance findings ([evidence](./docs/verification-log.md#acceptance-checkpoint-and-reference-host-regression--2026-09-26)).

- 2026-09-26: Restore the previously verified iOS 15 companion after importing the MCP bridge by targeting Safari 15.4; make recorded requests focus their populated input ([evidence](./docs/verification-log.md#physical-acceptance-found-and-corrected-a-phone-regression--2026-09-26)).

- 2026-09-26: Harden simulator compound selections, time clarification, cancellation receipts and scenario consent pauses; verify full evening twin end states and retain Nova’s fail-closed counting limitation ([ADR-020](./docs/adr/ADR-020-simulator.md), [evidence](./docs/verification-log.md#simulator-acceptance-continuation--2026-09-26)).

- 2026-09-26: Add the local authenticated simulator, SDK-managed MCP sessions and scalar elicitation, reusable card bridge, independent Echo histories and bounded host inference; retain item 29 as partial pending its full acceptance matrix ([ADR-020](./docs/adr/ADR-020-simulator.md), [evidence](./docs/verification-log.md#item-29)).

- 2026-09-25: Build the authenticated companion, fix portrait navigation, and pass UI, adversarial security, browser and CI acceptance; item 28 remains incomplete only for compatible-iPhone push reception and approval ([ADR-019](./docs/adr/ADR-019-companion.md), [evidence](./docs/verification-log.md#item-28-ci-acceptance--2026-09-25)).

- 2026-09-24: Add five authenticated local MCP App cards, deterministic presentation and retained-evidence scorecards, packaged static resources, and reference-host browser checks; close item 27 after author-approved visuals and passing packaging, conformance, isolation and authenticated CI latency gates ([ADR-018](./docs/adr/ADR-018-mcp-app-cards.md), [evidence](./docs/verification-log.md#item-27--2026-09-24)).

- 2026-09-24: Close item 26b after author review of the CI runner’s local authenticated MCP raw JSON-RPC round-trip gate; require manual latency dispatch before relevant item closures and submission, with AWS ingress, cold start and Alexa host overhead remaining item 38 ([closure](./docs/verification-log.md#closure--2026-09-24), [ADR-017](./docs/adr/ADR-017-tool-latency-and-isolation.md#closure-amendment--2026-09-24)).

- 2026-09-24: Measure authenticated server round trips with separate SDK references and byte-identity checks; both scenarios passed the single [CI latency run](https://github.com/BashaarJavaid/Hirz/actions/runs/36059341623), with item 26b still Deferred pending author review ([ADR amendment](./docs/adr/ADR-017-tool-latency-and-isolation.md#server-round-trip-amendment--2026-09-24), [evidence and tables](./docs/verification-log.md#completed-ci-measurements--both-scenarios-pass-author-review-pending)).

- 2026-09-24: Raise benchmark harness keep-alive, measure the SDK client floor, and defer approved-plan scheduling to the worker while preserving signed per-action events; item 26b remains Deferred after the complete single local gate failed ([ADR amendment](./docs/adr/ADR-017-tool-latency-and-isolation.md#scheduling-and-harness-amendment--2026-09-24), [evidence](./docs/verification-log.md#scheduling-and-harness--2026-09-24)).

- 2026-09-24: Bound verified-control and active-plan reads with migration 0013, and close withdrawn/expired constraints into audited graph history; retain item 26b as Deferred after an interrupted single latency measurement ([ADR amendment](./docs/adr/ADR-017-tool-latency-and-isolation.md#bounded-reads-amendment--2026-09-24), [evidence](./docs/verification-log.md#item-26b--2026-09-24)).

- 2026-09-24: Close item 26 isolation and defer item 26b latency until after submission, preserving the gate on manual dispatch only ([ADR amendment](./docs/adr/ADR-017-tool-latency-and-isolation.md#deferral-amendment--2026-09-24), [evidence](./docs/verification-log.md#deferral-checkpoint--2026-09-24), [CI](https://github.com/BashaarJavaid/Hirz/actions/runs/36021610833)).

- 2026-09-23: Add authenticated tool latency and concurrent household-isolation gates, signed per-action batching, transaction-scoped JSON snapshot reuse, combined budget/audit reads, budget-query indexes (migration 0012) and a private native helper that reuses compiled policies with fresh replay history; pause item 26 as partial after local/CI latency failures, retaining experiments and remaining work in the [handoff](./docs/verification-log.md#paused-handoff--2026-09-23) ([ADR-017](./docs/adr/ADR-017-tool-latency-and-isolation.md)).

- 2026-09-23: Publish [addon-check v0.1.0](https://www.npmjs.com/package/addon-check/v/0.1.0) and replace the conformance CI placeholder with full-SHA-pinned twelve-tool checks after restart, retaining Hirz-specific validators and signed audit verification ([ADR-016](./docs/adr/ADR-016-add-on-conformance-checker.md), [evidence](./docs/verification-log.md#item-25a--2026-09-23)).

### Changed

- 2026-09-24: Publish strict per-tool MCP output schemas and omit generated schema titles, preserving canonical objects and validating every response at the boundary ([ADR-015 amendment](./docs/adr/ADR-015-household-tools.md#per-tool-output-schemas--2026-09-24), [verification](./docs/verification-log.md#phase-4-review-batch-2--2026-09-24)).

- 2026-09-23: Complete the approved twelve-tool household scope with durable retries, simulated trust, per-device profiles, deterministic objectives and a confirmation-gated host; clarify approval argument combinations and verify all 31 live selection cases within the approved $2 ceiling. Later UI/app/trust integrations retain their assigned roadmap items ([ADR-015](./docs/adr/ADR-015-household-tools.md), [evidence](./docs/verification-log.md#item-25-completion-within-approved-scope--2026-09-23)).

- 2026-09-23: Add simulated local OAuth consent, SDK PKCE linking, resource-bound JWTs, scope enforcement and current household/member resolution while preserving anonymous onboarding; verify SDK/browser flows and add OAuth smoke to CI ([ADR-014](./docs/adr/ADR-014-local-oauth.md), [item 24 evidence](./docs/verification-log.md#item-24--2026-09-23)).

- 2026-09-22: Remove solver-known refresh triggers, preserve freshness across verified dispatches, explain plan-authority denials, and recover expired openings while retaining consent ([C2 verification](./docs/verification-log.md#phase-3-review-batch-c2--2026-09-22)).
- 2026-09-22: Make plan freshness change-based while preserving observation polling and staleness limits ([ADR amendment](./docs/adr/ADR-005-deterministic-planner.md#change-based-freshness--2026-09-22-author-approved), [partial Batch C verification](./docs/verification-log.md#phase-3-review-batch-c--2026-09-22)).

- 2026-09-22: Aggregate budget usage in SQL and scope graph advisory locks per household; retain in-transaction view refresh and accept exact totals without an index ([batch B measurements and verification](./docs/verification-log.md#phase-3-review-batch-b--2026-09-22)).

- 2026-09-22: Gate Python coverage over service-free and integration tests combined; move four threat rows to their earned local scopes and document Pipeline ownership and existing tool paths ([batch A evidence](./docs/verification-log.md#phase-3-review-batch-a--2026-09-22)).

- 2026-09-22: Execute the evening through existing services with separate plan/device approvals, exact bounded endings, private signed evidence and verified overnight outcomes; add the approved early guest-room and overnight dishwasher requests ([item 22 evidence](./docs/verification-log.md#item-22--2026-09-22), [ADR-005](./docs/adr/ADR-005-deterministic-planner.md), [ADR-006](./docs/adr/ADR-006-twin-first-adapters.md)).

- 2026-09-22: Add validated Plan/Decision narration, fixed offline-tested Bedrock Converse enrichment and audited restart-safe reuse with truthful status templates; retain live Bedrock verification for item 38 ([ADR-012](./docs/adr/ADR-012-explainer.md), [item 21 evidence](./docs/verification-log.md#item-21--2026-09-22)).

- 2026-09-21: Add private Postgres sessions, consent-gated temperature preferences and acceptance-driven plan refresh with native policy enforcement; verify the local backend while keeping companion authentication and AWS Memory outside scope ([item 20 evidence](./docs/verification-log.md#item-20--2026-09-21), [memory contract](./ARCHITECTURE.md#59-memory)).

- 2026-09-21: Add durable local plan refresh, remaining-work recovery, inherited consent with fresh device checks, append-only reservation transfers and truthful held reads; verify twin/HA restart and restoration without migrating development data ([item 19a evidence](./docs/verification-log.md#item-19a--2026-09-21), [refresh contract](./ARCHITECTURE.md#54-planner)).

- 2026-09-21: Add durable local execution, explicit plan consent/revisions, signed bounded endings and recoverable twin checkpoints; retain automatic refresh as item 19a ([item 19 evidence](./docs/verification-log.md#item-19--2026-09-21), [execution contracts](./docs/development.md#item-19-durable-local-execution)).

- 2026-09-21: Add audited, account-attributed coordinator intake, explicit conflict resolution, comfort precedence and two-hour twin thermostat holds ([ADR-005](./docs/adr/ADR-005-deterministic-planner.md#coordinator-amendment--2026-09-21), [item 18 evidence](./docs/verification-log.md#item-18--2026-09-21)); keep plan persistence and execution deferred.

- 2026-09-21: Add read-only MILP proposals, strict twin-replayed baseline comparisons, archived historical replay and planning snapshots; publish partial coverage rather than unsupported annual claims ([item 17 evidence](./docs/verification-log.md#item-17--partial-2026-09-21), [ADR-005 amendment](./docs/adr/ADR-005-deterministic-planner.md#read-only-planner-and-historical-experiment--2026-09-21)).

- 2026-09-21: Record [terminal HA dispatch attempts and fresh-action retries](./docs/adr/ADR-006-twin-first-adapters.md#terminal-ha-dispatch-attempts--2026-09-21-author-approved) and the Phase 2 review's [Phase 3 carry-overs and ordered-plug follow-up](./ROADMAP.md).

### Fixed

- 2026-09-25: Bring a newly requested twin unlock approval into view and explain the next passkey step inside the phone app ([item 28 evidence](./docs/verification-log.md#item-28--in-progress--2026-09-25)).

- 2026-09-25: Preserve companion sessions through the policy-change worker fix, show door-request outcomes, correct portrait panel spacing and export retained audit evidence independently of the stopped policy helper ([item 28 evidence](./docs/verification-log.md#item-28--in-progress--2026-09-25)).

- 2026-09-24: Add shared test/smoke checks for identifiers and braces in speech, and distinguish the unmeasured AWS latency budget from local CI results ([evidence](./docs/verification-log.md#phase-4-review-batch-1--2026-09-24)).
- 2026-09-24: Set the separate addon-check repository's Node requirement to 22 or later and update its GitHub About metadata; retain the tested CI pin and published version ([evidence](./docs/verification-log.md#phase-4-review-batch-1--2026-09-24)).

- 2026-09-23: Update the CI fresh-wheel catalog assertion for item 25's four added governance classes ([verification](./docs/verification-log.md#item-25-ci-catalog-count-fix--2026-09-23)).

- 2026-09-22: Let the live HA scenario smoke answer quiet-hour approval requests explicitly before the bounded lamp operation ([verification](./docs/verification-log.md#ha-smoke-explicit-consent-fix--2026-09-22), [ADR amendment](./docs/adr/ADR-006-twin-first-adapters.md#ha-smoke-quiet-hours-consent--2026-09-22)).

- 2026-09-22: Expose HA smoke errors, unsuccessful checks and refused lamp decision factors in CI output ([diagnostic verification](./docs/verification-log.md#ha-smoke-ci-diagnostics--2026-09-22)).

- 2026-09-22: Require adult lineage for app-only automation resume in Python and compiled Cedar/Dogwood; preserve linked-member pause ([batch A evidence](./docs/verification-log.md#phase-3-review-batch-a--2026-09-22)).

- 2026-09-21: Update the installed-wheel CI assertion to the 25 catalog classes introduced by item 18; reproduce the failure and verify the corrected check outside the checkout ([evidence](./docs/verification-log.md#installed-wheel-ci-count-correction--2026-09-21)).

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

- 2026-09-25: Record real iPhone passkey approval with signed twin unlock/relock evidence; item 28 remains incomplete pending its other gates ([evidence](./docs/verification-log.md#item-28-physical-iphone-approval-and-bounded-twin-relock--2026-09-25)).

- 2026-09-25: Build the authenticated companion foundation, policy lifecycle, encrypted push delivery and isolated Twin controls; item 28 remains in progress pending its complete acceptance gates ([ADR-019](./docs/adr/ADR-019-companion.md), [partial evidence](./docs/verification-log.md#item-28--in-progress--2026-09-25)).

- 2026-09-23: Add the local stateless JSON MCP endpoint and typed generic onboarding tool,
  with fixed loopback guards and real SDK/Inspector checks; OAuth and household
  tools remain later work ([ADR-013](./docs/adr/ADR-013-mcp-transport.md),
  [item 23 evidence](./docs/verification-log.md#item-23--2026-09-23)).

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
