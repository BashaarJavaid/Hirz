# ADR-012: Validated narration outside decision transactions

**Status:** Accepted, 2026-09-22. The item 21 implementation plan records the
household author's approval of these choices. Live Bedrock verification is item 38.

## Decision

Canonical `Plan` and `Decision` objects retain their `speakable` JSON shape and gain
optional `narration` metadata: input hash, version, provider, model ID, screen
summary and safe fallback reason. Absent metadata is omitted, preserving legacy
wire documents and signed history. No migration or backfill is needed.

The pure planner and immediate pipeline paths use validated deterministic
templates. `Coordinator.plan` and `RefreshWorker` accept an `Explainer`; ordinary
callers default to templates. The local worker selects it using `HIRZ_LLM=off`
(default) or `bedrock`; other values are configuration errors. Enrichment occurs
outside pipeline transactions. Refresh generation and fingerprint checks still
run after enrichment; obsolete results are discarded before publication.

`PlanService`'s shared audited publication path validates prepared narration or
supplies templates. Existing Plan/Decision writes persist it. Reads validate and
reuse stored output, including provider fallback, without calling a model or
persisting replacement narration. Changed status, selected facts, household,
locale, timezone or narration/provider version invalidate reuse. Held and
historical plans receive current templates without savings claims. Signed audit
payloads are never rewritten.

Only code-selected facts reach the provider: formatted valid figures and
comparisons, normalized explicit constraints, bounded display names, linked
account/surface and explicitly claimed authorship, constitution mode and risk
reasons. Raw utterances, free-form explanation strings, private memory,
contact channels, credentials, graph documents and internal object IDs are
excluded. Accepted graph preference records are also omitted from model input.
Names are optional bounded data. Prompts put selected data in a JSON field separate
from system instructions. This is containment, not a proof against prompt injection.

Code owns the status headline, options and source labels. Model output contains
only explanatory details and screen text, never authorization or schedule fields.
Headlines have at most 20 words and two sentences; spoken turns have fewer than
75 words (30 seconds at 150 words/minute), at most three details and five options.
Screen text including the code-owned source label is at most 500 characters.
Templates and provider output go through the same validation. Invalid output falls
back without truncation, repairs or retries.

USD/kWh use two decimals; temperature/percentages use at most one. Decimal
`ROUND_HALF_UP` preserves negative values and normalizes rounded negative zero.
Times use the household timezone and 12-hour display. The regex-and-set guard
accepts complete code-formatted numeric tokens only, preserving signs, units,
currency and times; numbers in arbitrary text never authorize output numbers.
Spelled-out quantities and formatting/internal identifier artifacts are rejected.
Invalid comparisons do not supply a timer saving, and nonpositive savings cannot
be narrated as savings by the model.

**Limit:** membership in the approved figure set does not prove narrative truth.
A model can associate an approved figure with the wrong fact or distort prose.
Status-claim and attribution checks are conservative guards, not semantic proof.
Narration cannot change the canonical decision, action, risk, consent or schedule.

## Bedrock contract

Boto3 is an explicitly approved exception to the async SDK convention: lazy client
creation and synchronous Converse work run in `asyncio.to_thread`. Offline mode
initializes neither AWS clients nor credentials. Cancellation propagates; cancelling
the coroutine does not kill an already-running SDK thread, whose SDK timeouts bound
network work. No provider result publishes after cancellation.

Use `us-east-1`, the standard credential chain, and the approved US cross-region
profile `us.anthropic.claude-haiku-4-5-20251001-v1:0`. Request Converse native
`outputConfig.textFormat` JSON schema, temperature 0 and 512 output tokens.
Connect/read timeouts are 2/5 seconds; `total_max_attempts` is 1. SDK/provider errors,
unsupported structured output, incomplete/malformed output and Hirz validation
failures yield templates with `provider_error` or `invalid_response`. Raw prompts,
responses and AWS error bodies are never logged by Hirz.

Contracts checked 2026-09-22:
[Converse](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html),
[Haiku 4.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html).
Offline botocore stubs validate the actual request shape; live model availability,
permissions and native schema acceptance remain item 38.

## Rejected alternatives

- A new cache table or narration endpoint: existing audited JSON documents provide
  persistence and household scoping without a new mutation surface.
- Calling a model during pipeline evaluation or on reads: adds latency and provider
  availability to an authorization path and defeats restart-safe reuse.
- Letting the model write headlines, options, source labels or decision fields:
  permission, pending execution and verified results need deterministic wording.
- Scanning raw prose for allowed numbers: would let injected text and IDs authorize
  invented figures. Only typed, formatted fact fields contribute to the set.
- Repair prompts, truncation and retries: add provider calls and can discard source
  or attribution qualifiers. A validated template is the bounded failure path.
- A second asynchronous AWS dependency or configurable model/timeouts: unnecessary
  for the approved offline-tested SDK bridge and fixed item 21 contract.

Evidence lives in [item 21](../verification-log.md#item-21--2026-09-22).
