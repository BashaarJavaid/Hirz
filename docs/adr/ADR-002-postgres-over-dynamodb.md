# ADR-002 — PostgreSQL as the graph of record

**Status:** Accepted (2026-09-15); amended 2026-09-17 (Phase 0 foundation)

**Decision:** PostgreSQL 16 stores the household graph, constitution versions, plans, actions, approvals, verification cases, memory proposals, and the audit chain. AgentCore Memory stores conversational short-term memory and extracted long-term preferences. A dedicated graph database is not used.

**Reasoning:**

- The audit ledger is a hash chain per household, with one pointer row per household updated in the same transaction as the insert. That needs transactions and row locks; DynamoDB's conditional writes can approximate it but make the verifier and exports harder and were the wrong fit in the author's earlier gateway work for the same reason.
- The household graph is small (tens of members and assets per household) with a handful of relationship types. Tables plus JSONB attributes and a materialized `household_context` view answer every query the pipeline needs in one round trip. A graph database would add an operational system for expressiveness nothing here requires.
- Row versioning (`valid_from`/`valid_to`) gives "what did Hirz believe at 18:16?" cheaply, which is central to explainability.
- Local development with Docker Compose needs a database that runs identically on a laptop and in AWS. RDS Postgres is that; DynamoDB Local is a weaker mirror.

**Alternatives considered:**

- *DynamoDB single-table.* AWS-native and serverless, attractive for the AWS Builder story. Rejected for the audit chain, the relational plan/approval/action lifecycle, and local-dev fidelity. The AWS story is carried by AgentCore, not by the database.
- *Postgres + Neo4j.* Rejected: no query in the design needs traversal depth beyond two hops.
- *AgentCore Memory as the graph of record.* Rejected: memory is model-extracted and unstructured; the graph must be typed, versioned, and never written by a model. Memory feeds *proposals* that a member accepts into the graph.

**Consequences:** RDS is the one always-on AWS cost, so it is deployed only for the judging window. `household_id` scoping on every table is a convention enforced by a test.


**Phase 0 implementation decisions (author-approved 2026-09-17):** SQLAlchemy Core
with async psycopg and Alembic; no ORM. The initial migration contains only
`households`, `members`, `member_accounts`, `audit_log`, and `audit_pointer` (exact
schema in `ARCHITECTURE.md` §6.1). Household/member identifiers are UUIDs; member
links use composite household-scoped foreign keys. Provider/sub uniqueness is
within each household, allowing the same account to link to both homes.

The single-pointer wording means one pointer **per household**, with a local
sequence and a zero-hash genesis. A global chain was rejected because verification
and exports must be household-scoped. Audit execution remains item 10. Graph
history columns, repositories, and seeds remain item 6; this migration does not
claim historical graph reads. Migrations are explicitly invoked and have a
reversible, destructive downgrade tested only against disposable databases.

## Item 6 amendment — 2026-09-18 (author-approved)

The graph uses current tables under stable identity keys plus matching history
tables, with UTC half-open `valid_from`/`valid_to` intervals. Separate identity
and version tables were rejected because the foundation already supplies the
foreign keys. History describes what was recorded then, not retroactive effective
time: backdated household changes are refused, expected `valid_from` tokens
prevent lost updates, unchanged writes are no-ops, and changed versions of one
entity cannot share an instant. Deletion/tombstones and bitemporal corrections
were explicitly deferred. Existing rows begin history at migration time; unknown
rate plans and location remain unknown rather than invented.

Current context reads use `household_context`; historical reads reconstruct from
current/history tables in one query. Materializing every historical snapshot was
rejected to avoid duplicated snapshots and repeated history rebuilds. Writers
serialize before mutation and refresh once in the same transaction. A plain
refresh was chosen over concurrent refresh for this small graph; it replaces the
whole view and can block readers ([PostgreSQL 16 refresh contract](https://www.postgresql.org/docs/16/sql-refreshmaterializedview.html)).
The global lock and refresh are a documented ceiling, not a claim of scaled
throughput. Daily observation-history partitions are deferred until ingestion
volume warrants their maintenance, rather than adding a partition scheduler now.

Item 6 has an explicit **synthetic bootstrap exception** before the pipeline and
signed audit writer exist. The local seed command initializes only `quinn-home`
and `quinn-parents`, with `demo` account links and twin asset bindings; repository
writes are otherwise exercised only in tests. No device action, policy activation,
runtime mutation endpoint, or fabricated audit event is authorized by this
exception. Existing/evolved households are never reset. Constitution versions
are persisted unvalidated, with no compiled policy or activation timestamp;
item 7 owns semantic validation. Multi-document YAML preserves the constitution's
specified top-level shape; nested wrappers and separate graph files were rejected.

The complete graph entity set is implemented now, including `shade` to reconcile
§5.1 with the existing device/context specs. Five graph-backed context scopes ship;
planner/constraint/security summaries, passkeys, adapters, and rule evaluation
remain with their owning items. Public snapshots exclude account subjects,
channel values/hashes, and safe-word hashes at the SQL projection; private reads
stay in explicitly household-scoped repositories. Only availability failures may
serve a process-local cached current snapshot, with an explicit read-only opt-in
and stale labeling. Historical reads and decision callers fail closed.

The approved synthetic contents and loader contract are documented in
[the constitution spec](../constitution.md#21-action-classes) and
[development procedures](../development.md). They grant Malik no membership or
login in his parents' home. The decisions in this amendment supersede only the
corresponding graph target-state details; threat-model rows remain unearned.

## Item 9 amendment — 2026-09-18

The approved internal pipeline uses three additional household-scoped tables:
`actions` (immutable proposal/requester/cost and grant reference), `approvals`, and
`approval_votes`. Decisions and dollar reservations stay in the signed audit ledger;
separate decision, budget-counter and execution-queue tables were rejected as
unnecessary. The existing graph transaction lock precedes approval and audit pointer
row locks, so single redemption, budget reservation and graph changes commit together.
The global serialization ceiling remains intentional pending measured contention.

The signed append primitive is pulled forward from item 10 because an item 9 grant
cannot safely commit without its audit row. The verifier, export and 100-concurrent-
decision gate stay in item 10. “One execution” in item 9's existing verification
sentence means **one durable execution authorization**, not device actuation; the
executor remains item 19. Dollar estimates reserve on grant; settlement/refunds and
per-class action-count limits are explicitly deferred. A second counter subsystem
or pretending that an ASK reserved spend was rejected.

Canonicalization uses the approved [Trail of Bits RFC 8785 implementation](https://github.com/trailofbits/rfc8785.py),
not `canonicaljson` (which was incorrectly named as RFC 8785). Exact envelope and
hashing contracts are in [architecture §3.4 and §5.10](../../ARCHITECTURE.md#34-internal-pipeline-contract-item-9).
Neither migrations nor the pipeline initialize or replace signing credentials.

## Item 10 amendment — 2026-09-18 (author-approved)

Keep the item 9 writer in place and implement the independent read path under
`hirz.audit`, sharing the canonical AuditEvent and existing RFC 8785 hashing.
Verification never re-runs policy. A read-only `REPEATABLE READ` transaction keeps
the household, pointer and streamed rows in one snapshot while appends continue;
PostgreSQL documents that successive reads see the same snapshot and read-only
transactions at this isolation level do not incur serialization conflicts
([PostgreSQL 16](https://www.postgresql.org/docs/16/transaction-iso.html#XACT-REPEATABLE-READ)).
No migration, dependency or writer-lock change is needed.

Commands select one explicit household. Exports first verify the full chain, then
include only an inclusive sequence interval in a versioned JSON file. The caller
supplies an independent public key or fingerprint for offline verification; an
embedded key alone is not a trust root. Database commands may derive the public
key from the existing validated local key. The exact format and verification
contract live in [architecture §5.10](../../ARCHITECTURE.md#510-audit-ledger).

Alternatives rejected:

- All-household defaults and time-range selectors: explicit household and sequence
  numbers directly match the existing chain and avoid additional selection modes.
- Prefix-inclusive exports: disclose history outside the requested interval. A
  selected-range export instead states precisely which links it can verify.
- File-only trust or automatic acceptance of an embedded key: could accept an
  attacker's replacement key and rewritten history. PEM-only verification was
  rejected in favor of also accepting an independently obtained fingerprint.
- Selected-range-only database checks: could export evidence from a household
  whose wider chain is already known to be corrupted.
- JSON Lines, stdout exports and fully streamed JSON publication: not needed for
  the current household workload. Selected rows occupy memory; stream publication
  if measured export sizes outgrow RAM. Exclusive private file creation avoids
  overwriting another file or relying on shell redirection permissions.
- Moving the writer or adding key rotation, signed export manifests, or anchors:
  unnecessary to this item. The current one-key chain contract stays unchanged;
  S3 anchors remain item 38b.

The concurrency gate launches 100 distinct pipeline proposals with a 20-connection
pool cap; the existing global transaction lock remains intentional. This tests
contiguity under concurrent requests, not 100 simultaneous database writers or a
throughput target. Signature/link checks earn only a Partial tampering claim:
tail-and-pointer rollback, complete erasure and a compromised worker re-signing
history remain undetectable without independently held evidence.

## Constraint history amendment — 2026-09-21

Migration `0006_coordinator_constraints` adds household-scoped `constraints` and
`constraints_history` using the existing graph versioning and materialized-view
pattern. Each record contains its canonical `PlanConstraint`, an explicitly typed
half-open validity window, submitting member, replacement identity and signed
Decision/record/withdrawal sequence references. Expiration is derived from time;
expired and withdrawn evidence remains readable through the `constraints` context
scope. Migration downgrade refuses current rows, archived rows, or constraint audit
events. Development upgrades remain explicit and manual.

Intake runs through the existing Pipeline transaction and native boundary. Grant,
recording, replacement/withdrawal, observation version (for a manual event), signed
append and context refresh commit together. Identical `action_id` delivery returns
the original Decision; mismatched content or principal cannot reuse it. A failed
signed append rolls back the entire mutation. No second transaction manager,
cleanup process, unaudited write endpoint or plan persistence is introduced.

## Durable local execution amendment — 2026-09-21

Item 19 extends `actions` with due time, lifecycle state and signed evidence
references. `0007_execution_lifecycle` adds canonical Plan JSON, household-scoped
plan/action links, member-addressed pending notices and twin checkpoints. Every
transition uses the existing graph transaction and audit writer. Migration is
explicit; downgrade refuses lifecycle evidence, including orphaned audit events.

A session advisory lock serializes each household sweep across processes, while
transactions close before HA network calls. A committed claim is never cleared,
including after a crash. Twin state and its configuration/position hash commit
with signed effect/checkpoint evidence; restart validates that evidence and resumes
from the committed simulated instant, excluding downtime. Rejected an in-memory
queue, a second job service, database locks held during device calls, and resending
an uncertain Action ID. Local recovery requires the worker and database to return;
this does not implement Hirz Link's offline ending guarantee.

## Durable refresh amendment — 2026-09-21

`0008_plan_refresh` extends plans with explicit runtime/prediction inputs, requester,
acceptance time and reservation lineage. A household/lineage primary key coalesces
`queued`, `running`, `blocked`, `idle` and `cancelled` jobs with requested/running
generations, reasons, attempts, retry time, fingerprints and signed audit references.
Downgrade refuses retained refresh evidence. Pipeline-guarded lifecycle operations
and the existing graph transaction make triggering mutations and opening holds
atomic; there is no job-history table because the signed audit already records it.

A separate session advisory lock permits one solver per household; transactions
close during polling/computation. A second connection services authorized endings.
Generation and input checks precede publication. Lost ownership permits restart
recovery; cancellation waits for the solver thread before releasing ownership.
Twin restore resumes the latest signed simulated instant, including lifecycle rows
newer than the physical checkpoint, then advances physics from that checkpoint.
Rejected process-local jobs, a second queue service, transactions held through
network/solver calls, and backdating restart writes to an older checkpoint.
