# ADR-015: Local household tools, durable requests and a headless host

Date: 2026-09-23. Status: accepted; item 25 completed within the amended author-approved scope.

## Decision

Expose twelve flat, strictly validated tools through the existing authenticated
stateless JSON MCP server. Use canonical Action, Decision and Plan objects and
define VerificationCase once in `hirz/pipeline/models.py`. Inputs cannot select a
household, role, trusted observation, surface or passkey authority. The linked
account selects the household and member; a claimed speaker can only reduce authority.

Follow Amazon's [Tools, Schema, Data Design](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-tools-schema-data-design.html)
and [display modes](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-addon-display-modes.html):
described scalar parameters, meaningful enums, strict schemas, typed structured
results and bounded consumer speech. This subset supports voice and native
rendering through structured data; it advertises no nonexistent card resources.
Missing values and ambiguous targets produce a clarification for another call.

Migration `0010_household_tools` stores rule proposals, first-plan requests,
private verification cases and request receipts. A household transaction binds a
request key to principal, tool and normalized arguments. It records the effect
and response atomically, replays identical retries, and refuses conflicting reuse.
Four narrow internal governance actions use Pipeline decisions and signed audit
evidence. Permission previews write only their prescribed DRY_RUN evidence and
receipt, with no approval or execution authority.

Policies compile and validate at server startup. Calls reuse local Dogwood for
bookkeeping and refuse changed policy bundles under the household transaction
lock. Device calls enqueue work; the existing worker owns boundary checks,
adapters, bounded endings and verification. No model, solver, compiler, Gateway
or adapter network operation belongs inside a tool call.

First-plan requests are durable and use explicitly configured twin scenario
inputs in the worker. Missing or incomplete inputs and infeasibility fail
honestly. Tonight, overnight and tomorrow morning end at the next household-local
08:00; next_24h ends after 24 hours. Existing plans keep their fixed endings.
Cancel before changing an approved plan's horizon. Coordinator accepts validated
ConstraintSpec values; MCP text is provenance, while existing scenario sentence
parsing remains supported. Revisions and refresh invalidation share a transaction.
Approval names the exact plan version and refuses refreshing or changed plans.
Security approvals on Alexa remain unresolved and report unavailable phone approval.
Pause tightens permissions; resume stays app-only. Rule proposals record a sentence
with CONSTITUTION_PROPOSED, without drafting, delivery or activation.

Only evidence-backed figures are exposed: timer, immediate and greedy comparisons
share the existing comparison validity rules. Do not sum revisions, call forecasts
realized savings, or annualize an evening. Annualized reporting requires a matching,
separately labeled retained backtest. Audit windows use household-local time and
return safe newest-first summaries, withholding private verification contents.

## Trust contract approved during implementation

Assessment is separate from contact initiation: verification is null until an
explicit start succeeds. Each phrase group contributes its weight once, with
case-insensitive word boundaries:

| Group | Weight | Bounded vocabulary |
|---|---:|---|
| Financial/access | 2 | send money, pay money, transfer money, wire money, dollars, gift cards, bank details, password, verification code, unlock the door, open the door |
| Unfamiliar channel | 2 | strange number, new number, unknown number, different number |
| Secrecy | 2 | keep this secret, don't tell anyone |
| Third-party recipient | 2 | courier, someone collecting money, another person's account |
| Urgency | 1 | urgent, immediately, right now |
| Claimed authority | 1 | police, government, bank, IRS |

Suppress a match when no/not/never appears in the preceding three words of the
same punctuation-delimited clause, except “don't tell anyone.” LOW is 0, MEDIUM
1–2, HIGH 3–4 and CRITICAL at least 5. Offer checking at every band. Advisory
signals never provide the trusted scam flag used by execution risk.

Supplied phone numbers strip spaces, parentheses, hyphens and periods. US ten
digits become +1; eleven beginning with 1 gain +; international numbers require
an explicit + and 8–15 digits. Reject extensions, letters and other characters.
Compare SHA-256 of the normalized value only with verified stored phone hashes.
A match never establishes identity. Without a supplied number, speech mentions
neither the caller's number nor a comparison. Organization verification reports
insufficient information.

The only executable method is explicitly simulated app_confirmation, requiring
both policy permission for communication.contact_trusted_contact and a verified
twin app channel. Worker-only replies use existing twin scripts; two minutes
without a reply expires to no_answer. Outcomes are pending, genuine, not_genuine,
will_call and no_answer, always labeled simulated. Follow-ups use a case reference,
a unique pending case, or the latest completed case for the initiating member and
optional contact; multiple pending cases require clarification. Cases are private
to that initiating linked member and household.

**Approved bootstrap exception:** initial, explicitly labeled verified-channel
fixtures may be installed only in disposable twin databases before runtime work.
All later case changes require Pipeline decisions; this is not a channel-editing API.

## Host and live gate

Use pinned Strands 1.57.0 with the documented Haiku 4.5 default, genuine MCP
tools/list, conversation context, injected request keys and explicit confirmation
before commitments. The reusable host follows the [Strands MCP integration](https://strandsagents.com/docs/user-guide/sdk/tools/mcp-tools/).
Selection-only tests cancel tool execution and assert the chosen tool and key
arguments; they do not substitute for the SDK execution smoke.

The author approved a total **$1 Bedrock ceiling**. Before every inference wire
attempt, native [CountTokens](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_CountTokens.html)
counts the complete conversation and tools; a locked durable ledger reserves the
input plus maximum 512 output tokens. No heuristic counting fallback or refund on
failed attempts. Conservative US cross-region Haiku 4.5 rates of $1.10/M input and
$5.50/M output were checked against [AWS's published example](https://aws.amazon.com/blogs/machine-learning/live-meeting-assistant-with-amazon-transcribe-amazon-bedrock-and-strands-agents/).
Reuse the same ledger across retries. Missing access, budget exhaustion or any
selection failure leaves the live gate pending; scripted evidence cannot pass it.

### Access/counting amendment — 2026-09-23

The initial authenticated preflight used the US inference profile ID and returned
`The provided model doesn't support counting tokens.` A later free probe with
the underlying foundation model ID succeeded. The host now uses that ID for
CountTokens and retains the US inference profile for Converse; a paid diagnostic
then succeeded without changing account settings or explicitly creating an
agreement. Keep the same ledger, model and ceiling; do not substitute estimates
or bypass counting. The separate Mantle counter still denies this account access
but is unnecessary for this route. The [AWS access procedure](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
documents automatic subscription on first invocation; an agreement status of
`NOT_AVAILABLE` before that invocation was not sufficient evidence of a hard
runtime access block. The prior broad claim of unsupported model counting was
incorrect: the failing identifier was the inference profile.
Exact results are appended to the [item 25 evidence](../verification-log.md#item-25--partial-2026-09-23).

## Rejected alternatives and remaining work

- In-memory deduplication loses guarantees on restart; persist receipts with effects.
- Parsing MCP prose into authority or constraints makes structured calls ambiguous;
  retain prose as provenance and require the relevant scalar values.
- Approving the latest replacement silently transfers unseen consent; require exact versions.
- Compiling or solving in calls violates the tool boundary; startup and worker own them.
- Treating a phone hash match as identity, or an assessment as permission to contact,
  overstates evidence; keep these separate.
- Inventing UI references, phone deliveries or successful plans misrepresents this preview.
- Replacing a failed live selection run with deterministic tests would not test a host.

### Completion-scope amendment — 2026-09-23, author approved

Finish item 25's routing failures, household profiles and objective tilts in this
item. The author subsequently approved explicit household-configured thermostat/
light bundles and deterministic objective ordering. No default device settings
or durations were approved; missing configuration is unavailable.

`apply_profile` selects `recovery_morning`, `guests_arriving`, `night` or `away`
from the authenticated household's startup-loaded `HIRZ_PROFILES_FILE`. Each
bundle contains 1–20 explicit room settings, restricted to lights and thermostat
changes. Resolve all targets before effects; reject ambiguity and duplicate
targets. Record the profile through Pipeline, then check/queue every device
separately in the same transaction. A blocked device does not grant authority
to itself or prevent another independently permitted setting. Return each canonical
Decision; never claim all devices changed. Profile approval binds the stored
concrete settings even after restart/config changes, and each child still needs
its own permission. Pause and claimed-identity reductions remain effective.
These are immediate setting changes; later authorized automation may change them.
No doors, guessed settings, new adapter, persistent hold or runtime profile editor.

`get_household_plan.objective` requires a request key. Approved ordering is
lexicographic: cheapest = electricity plus battery wear, then occupied comfort;
most_comfortable = occupied temperature deviation, then cost; greenest = grid
import kWh, then comfort, then cost. Comfort uses known occupied targets/preferences;
all existing hard constraints remain. Greenest means reduce grid electricity,
never measured emissions. Ordered solver passes share the existing five-second
budget and retain only validated incumbents, labeling unfinished refinements.
Omitting the objective preserves the existing default behavior and any stored
choice. Explicit changes persist through the existing refresh-input transaction,
invalidate exact old consent and yield a replacement requiring new consent. The
worker can change goals only to the explicitly requested durable objective;
automatic refresh still cannot invent different goals. Migration 0011 stores
first-plan objectives, and publication checks for changes during computation.

Rejected: guessing presets; applying a bundle with one permission check; silently
turning profiles into holds; weighted blends that obscure the approved priority;
carbon claims without a feed; reusing old consent after an objective change.

MCP elicitation moves explicitly to item 29, where the interactive host must
verify completed, refused and canceled elicitation against authenticated MCP;
the current typed/spoken clarification flow remains in item 25. Cards belong to
27; rule drafting, phone activation and approval notifications to 28; the full
simulator to 29; real check-ins and additional trust methods to 31; organization
verification to 33. These are later-item integrations, not unassigned item 25
work. Item 26's full latency/isolation gate remains separate. No threat-model
claim advances here.

Rejected: leaving profiles, tilts and elicitation in an unassigned "deferred"
list, or pulling all companion-app, card and trust functionality into item 25.

### Live gate budget amendment — 2026-09-23, author approved

The author approved raising the aggregate Bedrock ceiling from $1 to **$1.50**
for one additional full selection run after reviewing its estimated cost. Keep
the original ledger and all reservations; never reset or refund earlier attempts.
The host still reserves counted input plus maximum output before each wire attempt.
Pricing was rechecked against the AWS source above before invocation. Rejected
resetting the ledger, substituting scripted selections, or treating a passing
local test as live evidence.

Selection precedes the host's explicit confirmation gate. The prompt now makes
that order clear so the model does not request confirmation before proposing a
tool call. Supplied plan references/version can be checked by the server without
a preliminary fetch. Each new money request requires deterministic tool advice;
a model cannot substitute its own advice merely because an earlier assessment
was selected. The original corpus and expected selections are unchanged.

### Exact-approval follow-up — 2026-09-23, author approved

The author explicitly approved **$2.00 total** for a targeted approval diagnostic
and a full 31-case rerun, retaining all prior reservations. The tool description
now spells out its two input combinations: plan ID/version versus action/approval
references. The host includes a generic extraction example with a different
reference/version from the evaluation corpus. Server validation, exact consent,
confirmation gating and the unchanged evaluation expectations remain authoritative.
A targeted diagnostic alone never satisfies the full live gate.

The full 31-case live gate subsequently passed; retained failures, tokens, budget
and signed-audit evidence are recorded in the [completion entry](../verification-log.md#item-25-completion-within-approved-scope--2026-09-23). Later-item boundaries above remain unchanged.
