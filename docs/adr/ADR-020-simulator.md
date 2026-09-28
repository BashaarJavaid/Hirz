# ADR-020: Local authenticated simulator and MCP elicitation

**Status:** Accepted design, partial implementation/acceptance, 2026-09-26.
The author approved the item 29 implementation plan while item 28 remains partial.

## Decision

Keep `/simulator` in the existing React app and mount `/api/simulator` only when
an explicit `Simulator` is supplied to FastAPI. The disposable launcher supplies
the existing issuer, household runtime, companion, twin adapters and worker.
There is no second frontend framework, database migration or AWS deployment.
Restart requires fresh enrollment/activation and account linking.

Mom links to the parents' household; Malik and Dad link independently to the home.
An opaque HttpOnly browser cookie identifies server-memory OAuth tokens, separate
Echo histories, pending questions and receipts. Companion authentication remains
independent. POSTs require exact Origin and CSRF; expiries use real monotonic time
(five-minute questions, 30-minute idle and 12-hour absolute browser sessions).
Switching accounts cancels questions and suppresses stale speech; already accepted
calls settle and retain their actual results. Switching models clears conversations.

Authenticated MCP now uses the pinned SDK's stateful Streamable HTTP transport,
SSE replies and session ownership. The owner key covers issuer/client, household,
subject and scopes. Every HTTP request authenticates, and each resumed tool
re-resolves membership, current policy and target references. Generic anonymous
discovery/onboarding retains its stateless JSON path. An OAuth client that discovers
anonymously must link before opening its authenticated session; smoke clients
explicitly exercise this transition. This amends ADR-013 and ADR-014.

Scalar forms come from the existing flat input schemas and household clarification
path. A request-local confirmation context unwinds the full tool transaction before
asking about constitution-required requester confirmation. Its digest binds the
resolved action, policy fingerprint and linked principal. Replay validates inputs
and reauthorizes. No public Boolean grants authority. Security requests and policy
activation retain their passkey companion flows. Host commitment review is a
separate prompt for each exact proposed mutation, renewed after elicited changes.
The SDK handles accept/decline/cancel; unsupported clients receive typed clarification.
See the [transport contract](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
and [elicitation contract](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation).

Use the installed MCP Apps `AppBridge` and static card bundles, with opaque-origin
`sandbox="allow-scripts"` iframes and a no-network CSP. Cards receive protocol input
and results, never tokens. Serialize envelopes using MCP aliases and omit optional
null fields, as the SDK wire serializer does. Dot mounts no iframe. US-English
browser recognition/synthesis has visible text and typed fallbacks; replayed events
never trigger speech. Card fullscreen requires its existing user control.

Strands selects calls only. Execution is sequential through the real MCP client;
the host generates request IDs, maintains retry identity for card requests, and
limits each utterance to eight calls. Each inference allows 512 output tokens,
with automatic inference retries disabled. Haiku 4.5 is the paid default; Nova Lite
is explicit. `HIRZ_LLM=off` is scripted. Unknown scripted text is unsupported.
Failures offer an explicit scripted switch, never a silent model substitution.

The separate durable ledger reserves native CountTokens input plus maximum output
under a file lock before every attempted inference, across models and attempts.
Its purpose marker prevents reuse of the existing $2 item-25 ledger; the new cap
is $5. Prices checked 2026-09-26: Haiku 4.5 US inference $1.10/$5.50 per million
input/output tokens ([AWS](https://aws.amazon.com/blogs/machine-learning/live-meeting-assistant-with-amazon-transcribe-amazon-bedrock-and-strands-agents/));
Nova Lite $0.06/$0.24 ([AWS](https://aws.amazon.com/blogs/migration-and-modernization/migrate-your-ai-workloads-to-amazon-bedrock-with-aws-transform/)).
Counting failure stops before inference. Acceptance uses recorded rule patches
and deterministic narration; model selection is the only intended paid path.

Playback requires the relevant companion household and activated seed policy.
Only the selected scenario advances. Next-event stepping services existing action,
retry and approval deadlines with the five-minute observation cadence. World inputs
precede ingestion at their timestamp; distinct same-time changes advance one
microsecond for temporal graph ordering. Separate clocks never affect auth expiry.
Evening planning coverage extends the supplied twin inputs to 08:00 for the public
`tonight` contract; the original recorded timeline remains unchanged. Contact replies
are explicit simulated selections through the existing verification command; they
produce no unsolicited speech. Signed exports are independently verified before
successful cleanup. Source scenario deferred assertions remain deferred.

## Rejected alternatives and remaining boundary

- Browser-held bearer tokens, pre-enrolled credentials or preactivated policies:
  would bypass the approved account/passkey boundaries.
- Snapshot replay or internal scripted tool execution: would not test the public
  authenticated MCP contract.
- Polling instead of MCP elicitation, or keeping a transaction open during prompts:
  would miss the transport contract or retain locks during human waits.
- A new card host dependency/framework, unbounded inference, heuristic token counts
  or automatic fallback: existing dependencies suffice and failures must stop.
- Harness extraction, recording Compose, real contact delivery, Link and AWS:
  remain their separate roadmap items. Local twin success earns none of those claims.

Acceptance status and remaining checks belong in the
[item 29 evidence](../verification-log.md#item-29), not in this decision record.

### 2026-09-26 implementation refinements

Playback also pauses for newly required plan-action consent. It reads the pending
canonical Decision through `get_household_plan`, then submits an independently
confirmed `approve_action` with the genuine plan version and approval references.
The public twin worker retains the scenario's explicitly configured EV deadline;
acceptance checks the actual SOC at that deadline and completed dishwasher cycle.
Background card reads stay outside conversational history and never trigger speech.
Browser polling does not renew the simulator's idle timeout. Native requester
review retains immediate-action timing/identifiers across waits, while policy,
identity, targets and current observations are evaluated again.

Nova Lite currently rejects native CountTokens in the verified region. The approved
count-before-inference rule therefore blocks its live acceptance cells. Estimated
counting or substituting Nova 2 is rejected without changing the approved plan;
explicit scripted mode remains available. Evidence and the exact provider error
are retained in the verification/friction logs.

Haiku uses its native `disable_parallel_tool_use` control in the additional
request fields, leaving Converse's existing `toolChoice.auto` intact. Prompting
alone did not keep compound selections within the 512-token ceiling. Models see
the current plan's derived car target/deadline and compact canonical results;
rendered actions remain available to cards. Lowering a ceiling below that target
requires separately confirmed target and ceiling changes. Time-field descriptions
distinguish the change's `at` from its optional validity window. Elicitation reports
the invalid scalar; internal output-validation failures never become caller questions.

The host replaces Strands' pending-selection tool result with the genuine MCP
receipt and final host-generated arguments. Keeping a cancelled placeholder and
appending a separate user message was rejected: it left contradictory history
and caused incomplete compound requests. Models may ask short clarification
questions, while tool narration remains deterministic. Each new request re-enters
the service even when a historical attempt was denied. Recorded speech tolerates
case and sentence punctuation; numbers and words retain their exact meaning.

The shared web build explicitly targets Safari 15.4 because the already verified
companion phone runs iOS 15.7. SDK class static blocks in the default Vite target
made that phone's shared app blank. Native build lowering is sufficient; no
polyfill framework or second frontend is added. This does not add Web Push to
older iOS. Recorded utterance selection focuses the populated request field so
its separate Send action is apparent.

Acceptance also exposed the installed iPhone app's independent browser session.
A same-app link on the recorded-demo Constitution page preserves the existing
companion login for simulator controls. Sharing cookies or transferring companion
authority through the Echo session is rejected; separate browser sessions retain
their existing authentication boundary.

Resumed MCP GET streams and JSON-RPC elicitation replies require current household
membership even though their envelopes name no tool scope. A revoked or child
member receives 403 before SDK dispatch. Generic onboarding remains available;
session cleanup grants no household access. Relying only on the eventual tool-call
reauthorization was rejected because a resumed stream could expose queued data.

Fullscreen host context follows the iframe's actual layout dimensions with native
ResizeObserver; inline mode retains its 1280×800 logical canvas. Keeping the inline
800-pixel height in fullscreen clipped controls in short windows. The browser gate
checks canvas bounds after resizing and exercises the user's Close details action.

### Recorded punctuation amendment — 2026-09-27

The shared recorded-utterance key also ignores omitted straight/curly apostrophes,
so `whats going on tonight?` matches the recorded question in selection and playback.
Letters, negation and numeric punctuation remain significant. Fuzzy matching or a
model interpreter for unknown scripted text remains rejected; exact normalized
repository sentences are sufficient.

### Delayed phone approval amendment — 2026-09-27

The final dispatch claim now reuses the executor's existing `expired` contract.
Security unlock duration starts at its authorized opening, while approval expiry
and `expected_effect.by` independently limit dispatch. The duplicated claim check
had instead expired a one-minute unlock during the scenario's one-minute wait for
phone approval, after redemption but before any dispatch. Reusing the common
predicate removes that disagreement; ignoring the Pipeline error or extending an
approval was rejected. Exact hashes, current authority, approval TTL, grant freshness
and signed bounded endings remain mandatory.

The approval card displays the service's canonical speakable headline for phone
availability. A static “unavailable in this preview” statement was stale once the
authenticated companion existed; the preview service still supplies its own honest
unavailable message. Neither rendering path exposes a card approval for security.

### Rejected consent and blocked planning amendment — 2026-09-27

A recorded approval beat completes only after an affirmative `approve_action`
returns the canonical `execute` decision. A stale-plan rejection is a completed
tool call, but not consent to advance the scenario clock. The member must read
the current plan and confirm its exact version again. Expected policy refusals
for other scenario actions remain valid results.

Plan reads, explanations and approval share the persisted refresh-job check.
A blocked refresh returns `unavailable` / `PLAN_BLOCKED`, without a stale plan
card or a promise that polling will finish it. Queued refreshes retain `preparing`.
Force-approving the superseded plan, rewinding an already executed scenario, or
changing household requirements to make a failed run appear complete were rejected.

### Approved spending and Nova counting amendment — 2026-09-27

The user approved a $10 aggregate item-29 ceiling, preserving the existing ledger's
$4.3714836 reservation and every prior attempt. The separate item-25 $2 ledger is
unchanged. Prices were rechecked against the AWS sources above on 2026-09-27.

Nova Lite still rejects CountTokens. The user approved a Nova-only reservation of
its entire [published 300K context limit](https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html)
plus 10% (330,000 input tokens), together with 512 maximum output tokens before
each inference. At the verified rates this reserves $0.01992288 per attempt. The
ledger labels this as a context-ceiling bound, never an actual token count. Native
counting remains required for Haiku. The file lock, hard cap, no refunds for failed
attempts, no automatic inference retries and explicit scripted switch remain.

This supersedes the initial $5/counting-only decision for Nova; heuristic counting,
resetting the ledger, silently substituting another model and unreserved inference
remain rejected. Collapsed host diagnostics retain model response/stop reason to
diagnose selection failures without speaking unverified model outcome claims.

### Explicit selector steps — 2026-09-27

Retained live responses showed Haiku treating a historical denial as current policy
and Nova treating a historical pending check as its current status. Prompt-only
corrections did not reliably finish the requests. The host now uses Converse's
`toolChoice.any` with the twelve discovered MCP tools plus local `ask_user` and,
only during continuation, `finish_request` controls. These controls never reach
MCP or mutate household state. Multiple selected steps fail before submission;
the host still confirms and executes each real MCP mutation separately.
[AWS documents the native choice contract](https://docs.aws.amazon.com/nova/latest/userguide/prompting-tools-function.html).

The continuation names the actual original request, and the prompt distinguishes
requesting review from granting permission. The model retains canonical EV actions from genuine plan responses, because
energy observations do not contain the planned charge target. Strands' synthetic
“Turn ended early by hook after tool execution” message is removed from model
history: it describes the host's selection hook, not completion of user work.
Browser acceptance retains private model histories without session tokens, so
failed selections can be reproduced without restarting whole scenarios. Silently
replacing a failed model selection with recorded calls remains rejected.

The public verification contract already calls the deterministic `assess` service
when `verify_trusted_identity(start)` receives contact and text. Its returned case
contains the risk assessment and opened verification. Playback therefore accepts
that genuine combined result for the recorded assessment/check pair; requiring
two public calls incorrectly rejected completed work and created duplicate cases.
The existing separate assessment + case-reference path remains valid. Neither
path skips assessment, contact authorization, confirmation or signed audit writes.

Nova's model-facing input schemas keep only root `type`, `properties` and
`required`, and use `temperature=0` / `topK=1`, following the
[provider troubleshooting contract](https://docs.aws.amazon.com/nova/latest/userguide/tools-troubleshooting.html).
The public MCP schemas and server validation remain unchanged. Raising the
approved 512-output-token limit or automatically retrying malformed responses
remains rejected.

A live planned-action approval exposed an incorrect public description: it said
to omit plan references for every pending action, while the service correctly
requires the owning plan reference/version for planned actions. The description
and host prompt now match that existing service contract. Removing the service's
plan binding to accommodate the inaccurate description was rejected.

### Single diagnostic and device-name correction — 2026-09-27

The author approved exactly one Nova selection-only diagnostic with 1,024 maximum
output tokens. It reserved 330,000 input tokens plus that output maximum in the
same $10 ledger before inference, executed no household tools, and returned the
same provider `ModelErrorException`. This did not establish output truncation as
the cause. The temporary diagnostic allowance was removed afterward; the normal
host and budget validator still enforce 512. Further higher-limit calls or a
permanent limit increase are not authorized by that single diagnostic.

A subsequent Haiku evening failure exposed a separate server contract bug:
`living room lamp` did not resolve the household's `Living room light`, despite
the public room description promising lamp/light synonyms. The shared action
resolver now accepts those terminal device nouns, restricted to light assets in
the current household. Exact references and ambiguity clarification remain intact.
Execution, permission previews and profile settings share this correction;
rewriting only the model output or weakening general member/device resolution
was rejected.
