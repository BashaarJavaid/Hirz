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
