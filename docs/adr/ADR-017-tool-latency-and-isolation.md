# ADR-017: Local tool latency and household isolation

Date: 2026-09-23. Status: accepted protocol; verification pending item 26.

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
