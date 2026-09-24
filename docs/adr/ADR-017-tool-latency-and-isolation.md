# ADR-017: Local tool latency and household isolation

Date: 2026-09-23. Status: accepted protocol; isolation verified; latency deferred as item 26b.

## Decision

Measure the authenticated Python MCP client SDK over loopback HTTP against real
disposable PostgreSQL and native Dogwood. Time the awaited `call_tool` with
`perf_counter_ns`, including transport, authentication, persistence, serialization
and SDK decoding. Setup, assertions, token refresh and worker preparation are
outside each warm-call measurement. Use normal token lifetimes and real SDK PKCE
linking. Keep Bedrock off and devices simulated; no paid calls or development
database migrations belong to this gate.

Each case has five warmups and 100 measured sequential calls. Nearest-rank p95
must be at most 250 ms for **every case and every tool**. Unexpected outcomes,
timeouts and missing cases fail; retain every sample without trimming outliers or
retrying a failed gate into a pass. Report sample counts, minimum, median, p95,
maximum, commit, toolchain/platform and database row counts.

Map the three repository scenarios and the existing 31 selection cases to
explicit deterministic SDK inputs. Include fresh writes, durable retries, exact
consent, stale/security refusals, profiles, audit pagination and private contact
checks through pending, completed and no-answer states. Later-item integrations
remain deferred. Valid plan approval precedes the guest-room revision that can
hold refresh; test the refusal while updating, then cancel explicitly.

Reuse disposable databases across audited lifecycle rounds. Advance the explicit
simulation clock monotonically between calls; wall-clock measurements never use
simulated elapsed time. Every runtime mutation, including cleanup of constraints,
cancellation and app-side resume, uses a real Pipeline decision. Do not reset
tables, fabricate audit records, loosen policy or time cached retries as writes.
Worker services run in separate processes with restored twin state and the same
explicit fixture clock.

Report 100 local request-to-acknowledgment and request-to-verified-twin-light
samples, plus request-to-understandable missing-input planning failure. Include
worker launch/sweep and 100 ms polling in outcome/failure times. Report ten local
process-to-health and first-authenticated-context observations separately. These
have no additional threshold and establish neither AWS cold-start nor Alexa
voice-response latency; AWS measurements remain item 38.

## Isolation and author-approved fixture amendment

One MCP process serves independently linked home and parents accounts. Exercise
all twelve tools, both directions, concurrent requests and process restart. Check
foreign references, input authority injection, shared names/request keys, private
member cases, returned fields and complete scoped persisted rows. Legitimate
trusted-contact names are not leaks; UUID scope and authorized records decide.
Independently verify private signed exports for every fixture household.

The parents scenario cannot produce an energy plan or EV constraint. During
implementation the author explicitly approved an **additional initial disposable
copy of the existing home fixture under distinct household/account identities**
for symmetric plan, constraint and approval probes. Retain the actual home/parents
checks. This copy is explicitly labeled, test-only, and never relaxes the normal
two-household bootstrap restriction. Its runtime plans, constraints, approvals
and actions must still be created through Pipeline. Its synthetic token uses the
local test issuer's key and normal claim validation; it is not production login.

## CI and evidence

A dedicated latency marker excludes expensive measurements from ordinary tests
and coverage instrumentation. Isolation belongs to the integration suite. Replace
the CI latency placeholder with a 60-minute real gate. Keep addon-check's generic
contract checks unchanged, existing locked dependencies/actions and the no-upload
policy. Private evidence goes in a new mode-0700 directory, files mode 0600;
public summaries contain no tokens, claims, household payloads or signed exports.

Completion requires local checks and passing CI on `phase-4`. Minimal root-cause
fixes are authorized; dependencies, migrations, API changes and architecture
changes require a new author decision. Evidence belongs in the verification log;
procedures belong in development documentation. The cross-household threat-model
claim can advance only for the verified local authenticated MCP surface.

## Performance amendment — 2026-09-23

The author approved batching plan scheduling/cancellation database writes while
retaining every individually signed audit row, and reusing a household snapshot
within one locked transaction. Graph writes and transaction boundaries invalidate
the snapshot; callers receive independent data. Bounded-operation overlap checks
cover both persisted work and earlier openings in the same batch. Scheduling
still grants no device authority. Regression checks cover rollback, signed chains,
overlap refusal, mutable snapshot isolation and invalidation. No migration,
dependency, public contract or decision-policy change is authorized by this amendment.

## CI duration amendment — 2026-09-23

The author approved two isolated 60-minute latency matrix jobs, one for each
energy scenario with its parents cases. Both keep five warmups and 100 measured
samples per case. Jobs do not share a database or compete on the same runner;
the default local CLI still runs both scenarios. No sample count or latency
threshold is relaxed to fit the time limit.

## Refresh-read amendment — 2026-09-23

The author additionally approved batching refresh-attribution reads per check.
Bindings come from the validated household snapshot; one household-scoped query
loads verified controls up to the latest observation time. Each observation still
applies its own dispatch-time cutoff, target/adapter match, prior mode and appliance
completion rules. The single-observation caller shares the same matching logic.
Regression coverage must reject a future control for an earlier observation.

## Pure-work amendment — 2026-09-23

The author approved bounded standard-library memoization of policy-bundle
fingerprints keyed by every immutable input value, and reuse of identical
validated narration within a scheduling batch. Policy objects remain fresh;
changed policy, compiled policy, schema or manifest values must still fail
integrity validation. Narration reuse compares the complete context and derived
facts, retaining each action's own decision and signed audit row. Mutation and
independent-output equivalence regressions accompany the changes. The 250 ms
gate and all sample counts remain unchanged.

## Transaction reuse amendment — 2026-09-23

The author approved reuse of identical refresh fingerprints and linked-member
resolutions within the same locked transaction. Fingerprints compare all snapshot,
runtime, policy and applied-control inputs, while verified-control database reads
still run on every check. Member keys include provider, subject and surface.
Graph writes and transaction boundaries invalidate both; callers receive independent
results. Mutation, input-equivalence and invalidation checks accompany this change.
No authorization check or signed row is removed, and the latency gate is unchanged.

## Budget-index and terminal-read amendment — 2026-09-23

The author approved explicit migration `0012_budget_indexes`: a partial
household/grant-sequence action index and household-scoped expression indexes for
budget reservations and adjustments. Only disposable databases and CI are upgraded
for verification; development remains on 0005. Upgrade/downgrade changes indexes
only and must preserve budget totals and every signed row. Fixed JSON paths remain
SQL literals so prepared generic plans can use the indexes; all caller values
remain bound parameters.

The author separately approved moving the existing exclusion of superseded,
completed and abandoned plans into refresh invalidation, observation ingestion
and worker-poll SQL. Active-plan checks and audit behavior remain unchanged.
Regression coverage checks fetched row counts and retained terminal evidence.

## Native-helper amendment — 2026-09-23

The author approved a narrowly scoped Rust helper and a pinned native-library
patch after the remaining Dogwood cost was measured. `scripts/build_dogwood.py`
builds the unmodified pinned CLI first, then adds `Clone` to `Lowered` and
`LoweredPolicySet` and builds `dogwood-helper` with the same Cargo lock. No parser,
policy evaluator, temporal semantics or dependency version changes. The helper
uses the same [`Authorizer::new` and replay loop](https://github.com/dogwood-policy/dogwood/blob/996d756de1013b7ae209a14f566a80375a59f2f0/dogwood-cli/src/ops.rs)
as the reference CLI.

One private pipe process belongs to the MCP lifespan. Startup validates and
prepares each policy; replay refuses an unprepared policy/schema pair, so no
compilation enters a warm tool call. Exact source strings key the compiled cache.
Every replay constructs a fresh Authorizer from cloned artifacts, including each
approval prefix: no approval history or authorization result is cached. The pipe
is serialized; concurrent calls cannot exchange responses. Failure, malformed
output, timeout or cancellation kills/reaps the helper and denies authorization;
there is no automatic CLI fallback. Standalone CLI and worker callers retain the
existing reference path. Native equivalence, cross-household, concurrency,
history-reset, mutation and cleanup regressions are required, alongside the
unchanged full 250 ms gate.

Rejected a Python temporal reimplementation, cached boundary decisions, skipped
native checks and an always-on network service. A private pipe reuses the existing
Rust build and dependencies without a new network or AWS resource. Python bindings
and an upstream contribution remain separate work; this patch adds artifact
cloning only and does not change the reference CLI used for comparison.

## Recordset and canonicalization amendment — 2026-09-23

The author approved replacing the variable-width scheduling `VALUES` update with
one typed PostgreSQL `jsonb_to_recordset` parameter. Its derived column types come
from the existing action table; the update remains household-scoped and atomic.
Dates use the existing wire normalization, and PostgreSQL converts JSON null to
SQL NULL, including the retained lifecycle of an expired action
([PostgreSQL contract](https://www.postgresql.org/docs/16/functions-json.html),
[SQLAlchemy derived columns](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#table-valued-functions)).
Whole-row and late-consent regressions check values, nulls and rollback.

Audit payloads are already normalized before the signed envelope is constructed.
The writer now applies the same RFC 8785 encoder and SHA-256 directly to that
envelope, removing only its second normalization walk. The independent verifier
retains the original digest path and must reproduce every hash and verify every
signature. No canonical encoding rule, audit payload, signed row or failure
guarantee changes. Rejected shortening audit evidence or changing the serializer
to meet the latency gate.

## Combined-read amendment — 2026-09-23

The author approved combining each budget's reservation and adjustment aggregates
into one statement, and each audit pointer/head check into one statement. Both
budget aggregates retain their household, class and date predicates and Decimal
arithmetic. Audit append still holds the household transaction lock first; a
`FOR UPDATE` CTE locks the pointer before the append. A singleton left-joins the
pointer and latest head so either missing-row case remains distinguishable.
Sequence, hash, signing-key and timestamp checks remain unchanged. Neither result
is cached: every check reads PostgreSQL afresh.

Signed-ledger totals before and after cancellation, missing/corrupt pointer/head
states, rollback and concurrent Pipeline appends verify equivalence. Rejected
caching either ledger state or dropping the pointer lock. This amendment changes
no schema, dependency, public response, signed row or latency threshold.

## CI completion-time amendment — 2026-09-23

After Time-of-Day CI completed all 105 home lifecycle rounds but reached its
60-minute limit before the remaining verification finished, the author approved
75 minutes for each of the same two isolated jobs. Hourly had already completed
within 60 minutes. Sample counts, signed-audit verification, private evidence
handling and the 250 ms case/tool gate are unchanged; this extends only the time
available to finish the measurement. It supersedes the earlier 60-minute limit.

## JSON snapshot-cache amendment — 2026-09-23

The author approved storing the validated transaction snapshot's data as a JSON
string and decoding an independent dictionary on reuse. The existing standard
library encoder/decoder preserves the full data, including withdrawn constraints;
the cached metadata holds no caller-owned mutable data. Household ownership,
graph-revision and transaction boundaries, backward-time refusal and refreshed
read timestamps retain their existing behavior. Fresh reads still validate the
database snapshot. No public context shape, history, authorization, audit row or
250 ms threshold changes.

Regressions compare fresh and cached values in both households, including nested
mutable values, booleans, integers, floats, nulls, Unicode and a withdrawn
constraint; PostgreSQL tests check write/transaction invalidation and rollback.
Rejected dropping withdrawn constraints from context or sharing mutable cached
objects with callers. Measurements and limits belong in the verification log.

## Rejected alternatives

- Timing only onboarding/context, only handler functions, or only cached receipts
  would miss real tool persistence and authentication costs.
- Pooling cases alone could hide a slow fresh-write path behind fast retries.
- Recreating every database for every sample costs setup time and hides growing
  history; deleting runtime rows would bypass the audit guarantee.
- Sequential-only isolation cannot exercise request-local identity separation.
- Expanding parents' product capabilities just for a test would pull later scope
  forward; the separately labeled fixture exercises the existing implementation.
- Adding a load-test framework or a new production endpoint is unnecessary.
- Calling local startup an AWS cold start or marking the threat row from code
  inspection alone would overstate the evidence.


## Deferral amendment — 2026-09-24

The author defers the latency gate until after the 2026-10-23 submission and
closes item 26's isolation clause on its existing verified evidence. Latency is
tracked separately as item 26b and runs in CI only on `workflow_dispatch`.
Keep the gate, corpus, sample counts and 250 ms threshold unchanged. Completion
of the latency gate no longer blocks the isolation claim, which is limited to
the local authenticated MCP surface: independently linked accounts, both
household directions, concurrent requests and restart. The AWS token path remains
item 38; the cross-household threat row is Partial, not Yes.

The [hackathon rules](https://amazonappdev2026.devpost.com/rules) specify no
latency, performance or response-time requirement. Stage One is pass/fail on
track fit and application of required APIs/SDKs; Stage Two scores Tech
Implementation, Design, Potential Impact and Quality of the Idea. The
[partner-only MCP Toolkit quickstart, Performance](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html#performance)
says: “Your MCP server must meet a round-trip query response latency of less than
500 ms.” Participants cannot access the toolkit (friction log entry 1); the rules
do not reference this sentence. Hirz's 250 ms local gate is its own derived proxy.
The budget table remains target state; measured failures and the rules check are
retained in the [evidence entry](../verification-log.md#deferral-checkpoint--2026-09-24).

Rejected alternatives: `continue-on-error` still burns 75 minutes per push;
deleting the gate loses a reproducible check; loosening the threshold or corpus
would hide the outstanding performance work. The fix is scheduled after
submission, without authorizing the pending indexes/projection or any other
runtime change in this records-and-CI checkpoint.


## Bounded reads amendment — 2026-09-24

The author approved three runtime changes and the index-only migration
`0013_bounded_reads`. Upgrade and downgrade create/drop only the verified-target
and active-plan indexes; metadata mirrors them using the fixed nested JSON SQL
expressions established by 0012. Development stays on 0005; verification upgrades
only disposable databases. The original retained benchmark database is read-only.

**A — latest verified control per bound device.** Every attribution check still
reads PostgreSQL. One household-scoped statement selects asset bindings and uses
a LATERAL join to find the latest verified action for each binding's adapter and
entity, ordered by execution-attempt sequence descending, with the joined audit
timestamp at or before the supplied observation cutoff. The partial action index
supports one ordered probe per binding, and the returned set is bounded by the
number of bindings. This deliberately changes semantics: an older control that a
newer verified control on the same device has superseded no longer attributes
state, even when the older control matches the observation. The matching code's
`since`, dispatch-time, previous-mode and appliance-cycle checks stay unchanged;
lineage-scoped `applied_controls` is unchanged. No verified-control decision is
cached and no lower time bound is introduced.

**B — close inactive constraints through graph history.** The repository's close
operation validates scope/model/version as put does, archives the final version
(including withdrawal metadata) with `valid_to` equal to the graph transaction's
write time, deletes its current row, and changes the graph revision and change
flag. The existing materialized-view refresh remains in that transaction.
Withdrawal uses close; as-of reads before closing retain the constraint and reads
at or after closing do not. Successful constraint record and withdraw commits
also close that household's one-time constraints whose spec end has passed.
Every existing `CONSTRAINT_RECORDED` / `CONSTRAINT_WITHDRAWN` payload includes
`expired_constraint_ids`, including `[]`, linked to the triggering grant by
`decision_seq`. The field sits under the existing signature; canonical Decision
and public tool shapes do not change. Any failure rolls back closure and audit
writes together. No migration backfills or rewrites existing history.

The existing `active()` rule is unchanged: a withdrawn constraint still applies
to a window starting before its withdrawal. For closed rows that earlier-window
case is reachable only through an as-of snapshot; a re-plan starting after
withdrawal is unchanged. The JSON snapshot-cache amendment's rejection of dropping
withdrawn rows concerned fidelity to its then-current source snapshot, not a
product promise to return inactive constraints forever. The catalog's current
constraints scope continues to mean active constraints.

**C — indexed active-plan lookup.** `hirz/db.py` defines one fixed-literal
terminal-status predicate, shared by the active-plan lookup in
`hirz/mcp/household.py`, refresh invalidation, observation ingestion, worker reads
and the metadata partial index over household and descending audit sequence.
The migration freezes the same predicate. PostgreSQL can therefore prove the
partial index applies, including for prepared queries. Result-equivalence,
index roundtrip and metadata-reflection checks preserve all retained rows.

Rejected a fixed time window and a per-observation time window: both forget a
days-old setpoint and can trigger needless re-plans. Rejected filtering withdrawn
rows in SQL, which leaves the current table growing; a new expire action class;
and an unaudited worker sweep. Expiry belongs to the already-authorized constraint
commit and its signed evidence. The corpus, sample counts, 250 ms threshold and
manual-only CI latency gate remain unchanged. The single local measurement and
its incomplete transport-failure evidence are recorded in
[item 26b](../verification-log.md#item-26b--2026-09-24); this amendment does not
complete the latency gate.

## Scheduling and harness amendment — 2026-09-24

The author approved a harness-only Uvicorn `timeout_keep_alive=120` so worker
idle gaps do not cross the server's default five-second keep-alive boundary.
Production/local runtime entry points are unchanged. The prescribed 200-call
six-second-idle probe was run before and after the change; neither run reproduced
the previously observed race. Counts and the retained reproduction are in the
[item 26b evidence](../verification-log.md#scheduling-and-harness--2026-09-24).

A private same-process, same-database comparison measured authenticated SDK calls,
raw HTTPX POSTs with the captured identical JSON-RPC body and bearer token, and
handlers alone. The large difference is on the SDK client path: raw HTTP through
the same stateless server is much closer to handler time. No SDK, server-session,
measurement-protocol, corpus, sample-count or 250 ms threshold change is authorized
by this finding; investigation stops at that layer. Measurements and the private
probe's post-measurement cleanup error are retained in the evidence entry.

Plan approval now commits the existing electricity-plus-wear budget grant and
`PLAN_APPROVED` governance decision, allocation and `approved` plan state, without
materializing scheduling rows. The response says the approved plan is being queued
and returns the canonical approved plan, whose action references come from its
stored document. A second fresh approval is refused before the worker runs;
identical request receipts retain their existing retry semantics.

The worker finishes that recorded consent under the household writer lock using
the existing scheduling commit. It recovers the original Decision through the
signed `PLAN_APPROVED` reference, preserves every individually signed `SCHEDULED`
or `EXECUTION_CANCELLED` event and the overlap, missed-opening and late-consent
logic, and commits the whole batch atomically. Approved plans with unscheduled
proposals are durable pending work; no cached rows, new queue or migration is
needed. A crash before commit leaves the batch pending, and a committed batch is
not scheduled twice. Cancellation and revision before the tick retain their
existing signed transitions and prevent the superseded plan from scheduling.
Inherited consent uses the same deferred path; consent naming an already replaced
plan remains refused.

Pending consent is scheduled before the worker's refresh batch so missed openings
queue and process their replacement in that tick; the final executor sweep also
schedules consent inherited by a replacement published during the batch.

Scheduling failure now leaves the already committed consent and budget allocation
intact for worker retry or member cancellation/revision; it cannot return a failed
approval retroactively. Overlap checks still refuse the entire scheduling batch.
Due bounded endings are processed before scheduling, and every opening still
requires execution-time Pipeline authorization, current context and boundary
agreement. This changes when scheduling evidence appears, not device authority or
the fail-closed guarantees in architecture §9 and the threat model.

Rejected caching scheduled rows (duplicates durable source state), skipping signed
per-action events (loses individually verifiable lifecycle evidence), and a
synchronous partial schedule (makes the approval contract depend on batch size and
splits an atomic scheduling operation). Hourly latency, a second local measurement
and a manual CI dispatch remain outside this step.

## Server round-trip amendment — 2026-09-24

The author changes the gate's measurement boundary to the raw authenticated
JSON-RPC `tools/call` POST an add-on host sends, using the existing pooled HTTPX
client, URL, bearer token and negotiated MCP protocol version. `perf_counter_ns`
starts immediately before the awaited send and stops after the full response body
has arrived. Transport, server authentication, persistence and server serialization
remain measured; client-side JSON/MCP decoding and the SDK's structured-content
validation no longer contribute to the gate. HTTPX request construction is outside
the timer. This supersedes the SDK timing decision above, not the corpus, five
warmups, 100 samples per case, nearest-rank p95 or 250 ms threshold.

The established floor probe measured onboarding at 58 ms through SDK `call_tool`
versus 4 ms for the identical raw POST (54 ms difference), and context at 70 versus
13 ms. MCP Python SDK 1.30.0
[`src/mcp/client/session.py:417–441`](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/client/session.py#L417-L441),
`ClientSession._validate_tool_result`, calls
`validate(result.structuredContent, output_schema, registry=registry)` on every
successful result. `jsonschema.validate` checks the schema against its metaschema
and constructs a validator each time. This is client-library cost, not server
cost; the finding is accepted from the retained floor probe, not remeasured here.

The SDK still links accounts through PKCE, refreshes tokens before the timer, and
validates each successful raw `CallToolResult` through its unchanged schema
validator after timing. `Result` validation, error checks and every corpus
assertion still run. Onboarding and context-all additionally call SDK `call_tool`
once each round, including warmups, for separate reference columns; these samples
never enter the gate or pooled-tool statistics. No mutation corpus is duplicated.

The server is configured with `stateless_http=True` and `json_response=True`;
these ordinary tool requests require no SDK session observation. Initialization
asserts that no session ID exists. A unit test captures SDK and raw requests via
the same HTTPX transport, aligns independent request IDs, and compares exact
method, path, authorization/accept/content-type/protocol header values and body
bytes. It uses the SDK OAuth provider and fails on wire drift or lost validation.
No session messages or responses are fabricated in the benchmark.

Linux CI is the measurement instrument: the established Docker Desktop/macOS
outliers are not used to judge this step. After ordinary CI, one manual dispatch
runs both existing latency matrix jobs, without reruns. Item 26b remains Deferred
pending the author's review even if both pass; no local full latency run, Bedrock,
ledger access, development migration or AWS measurement is authorized.

Rejected keeping SDK timing because it charges client schema work to the server;
loosening the threshold because the server budget is unchanged; and patching or
forking the SDK because the host-specific optimization is outside this server gate
and would weaken the independent reference. Validator caching is suggested
upstream in the [friction log](../friction-log.md#item-26b-sdk-per-call-schema-validation--2026-09-24).
