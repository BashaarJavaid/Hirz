# ADR-003 — YAML constitution, constrained grammar, compiled to Cedar, enforced twice

**Status:** Accepted (2026-09-15); amended 2026-09-17 (local mode labeled as a second evaluator; a permit is what gets a command signed, ADR-009)

**Decision:** The household constitution is authored as YAML (via form, YAML, or plain English) with a small non-Turing-complete condition grammar, validated by a Pydantic schema and a tighten-only rule against the risk floors, and compiled to a Cedar/Dogwood policy set. It is enforced in-process by Hirz's evaluator (pipeline stages 2, 4, 6) and again at the AWS tool boundary by AgentCore Policy (stage 7), with the open-source Dogwood CLI standing in locally so both engines run the same language, temporal rules included. Disagreement fails closed.

**Reasoning:**

- Households need a document they can read, diff, and roll back. YAML with a sentence rendered per rule satisfies that; Cedar alone does not (it is precise but not a household-facing format).
- The grammar is deliberately tiny so every rule is decidable, auditable, and safe to evaluate on every action without a sandbox. The missing-attribute rule (whole condition not satisfied before negation) is inherited from the author's ABAC evaluator, where the `not(...)` inversion bug was found and fixed.
- Cedar is the right target: default-deny, forbid-wins, schema validation against the tool definitions, automated-reasoning analysis for always-allow and never-satisfiable policies (available through AgentCore Policy in AWS mode; no local library provides it), and temporal (Dogwood) rules that express "approval must precede action within the TTL" without custom code. AgentCore Policy evaluates it at the Gateway, outside Hirz's process. That enforcement point is independent about policy (action, role, parameter bounds, action hash, approval history are all in the request) and not about context facts, which Hirz supplies from its snapshot, hash-bound; the docs say exactly that rather than "genuinely independent".
- The temporal rule is generic (any action with a matching approved `action_hash` within the TTL), emitted once per distinct TTL rather than once per `ask` class, so a household's constitution never runs into the engine's 25-temporal-policy quota. Who may approve which class is carried by stateless permits on the `approve_action` tool.
- Local evaluation uses the Dogwood CLI, not `cedarpy` plus a hand-written temporal shim. A reimplementation of `formerly within` would be the least-trusted code in the repo and the conformance test would then be testing the shim, not the compiler.
- Two engines evaluating the same policy over the same facts is redundancy that fails closed. It catches bugs in Hirz's pipeline. By itself it does not stop a path that never asks the boundary, which is why, in AWS mode, a permit is also the only way a home command gets signed and the home obeys only signed commands (ADR-009).
- Local mode is honest about what it is: the Dogwood CLI runs in the same container, so it is a second evaluator in the same trust domain and a conformance check on the compiler, recorded as `boundary.engine: dogwood-local` and shown that way in the Cedar view. "Enforced outside Hirz" is claimed for AWS mode only.

**Alternatives considered:**

- *Cedar as the authoring format.* Rejected for households; kept as the compiled and enforced form.
- *Natural language as the stored policy, interpreted by a model at decision time.* Rejected outright: non-deterministic, un-analyzable, and vulnerable to injection. Natural language is an authoring aid that produces a YAML patch a member activates.
- *OPA/Rego.* Capable, but no managed enforcement point in the AWS stack and no temporal support; Cedar's analysis and AgentCore integration won.
- *In-process evaluation only.* Simpler, but loses the independent boundary that makes "enforced at the AWS tool boundary" true rather than a slide.

**Consequences:** The class list, the risk table, the Cedar action names, and the Gateway target's tools must stay aligned; a test generates all four from `hirz/risk/classes.yaml`. Temporal quotas (25 policies per engine, 3 operators per policy, 24 h window) are still checked at compile time but are no longer a practical constraint. Activating a new temporal policy set invalidates open policy sessions, so activation starts a new plan session. The Dogwood CLI's drivability from a subprocess (schema, entities, event trace in; decision out) is verified in Phase 1 (`ROADMAP.md` item 7); the documented fallback is `cedarpy` for stateless rules plus an in-process record for the single generic temporal rule. Local activation does not run automated-reasoning analysis and records that it did not. If the item 7 gate shows the Dogwood CLI is painful to drive from a subprocess, real Python bindings over its Rust `Authorizer`, contributed upstream, become a candidate second open-source contribution and would replace the subprocess wrapper; that decision is taken after the gate, not before.

## Item 7 amendment — 2026-09-18 (author-approved semantics)

Item 7 implements read-only schema validation, pure resolution, rendering, local
compilation, and preview. It introduces only the canonical `Action`, not a
premature `Decision`. `RuleOutcome` carries sorted attribute-path diagnostics;
there is no audit writer here. Graph-to-policy fact assembly, activation,
authenticated approval, risk, budgets, quiet-hour enforcement, and device actions
remain their scheduled items. No threat-model row is earned by this compiler alone.

The schema retains seven roles and their documented inheritance. Parent and domain
restrictions survive child entries; explicit class entries precede a wildcard in
the same role. Role tightening never replaces base conditions, hard bounds,
requester restrictions, or the first applicable override. HIGH and CRITICAL
profiles reject `auto`; **all** security rules exclude Alexa from effective
approval channels, including `never`. The corrected seed files do not update
stored versions or their hashes. Existing old seeds fail with the security-channel
validation error and must await the later activation workflow.

Conditions have `not` > `and` > `or` precedence. Every referenced attribute is
preflighted before Boolean evaluation; absence is never an explicit null.
`is not set` accepts present null only. Known-false ordinary conditions can ask
and be approved; unresolved conditions/override tests cannot authorize, even after
approval. Applicable vetoes and hard bounds remain terminal. Number parsing retains
YAML decimal text and rejects values beyond four fractional digits or Cedar's
fixed-point range; it never rounds across a bound. `context.time` is an HH:MM
household-local comparison. Occupancy predicates use the exact zone/member in the
snapshot's household-scoped identifier lists. Schedule horizons include both
endpoints; missing collections are unknown and explicit empty collections are complete.

Approved defaults: TTL 1–1440 integer minutes, rule overrides default; quorum
`any_adult`; omitted requester lists permit roles whose effective rule is not
`never`. Adult-derived approval participation respects domain restrictions.
Budgets and quiet hours are rendered configuration, with item 9's contracts in
[the spec](../constitution.md#24-budgets-and-bounds).

The native engine remains **dogwood-local**, pinned to
[`996d756de1013b7ae209a14f566a80375a59f2f0`](https://github.com/dogwood-policy/dogwood/tree/996d756de1013b7ae209a14f566a80375a59f2f0).
The complete home constitution validates, and the gate exercises genuine history
matching. The default CLI event schema's resource correlation is `callerResource:
resource` (and `callerPrincipal: principal`), followed by `input.household`,
`input.action_class`, `input.action_hash`, `input.session_id`, `input.ttl_minutes`,
`output.ttl_minutes`, and `output.approved`. These are field matches within **one**
`formerly` operator. Generic permits additionally constrain the actual action,
class input, household, and current TTL group; governance approval is excluded.
Per-class approval permits check separate requester/approver facts, channel and
quorum. Current hard guards and vetoes still forbid the action after approval.

The CLI does not authenticate a supplied historical response. Hirz's local wrapper
therefore authorizes each approval request under the compiled policy before adding
its response to the trace. The supplied approval/quorum fields are **not** proof of
a person or passkey. A local trace is replayed from scratch, with session/resource/
principal correlation; this is not a durable approval store or consumption mechanism.
Malformed output, engine errors, timeout, or a crash fail closed. The 10-second
subprocess deadline kills and reaps a timed-out child. No runtime fallback is used.

The [CLI contract](https://github.com/dogwood-policy/dogwood/blob/996d756de1013b7ae209a14f566a80375a59f2f0/dogwood-docs/guide/12-cli.md)
was usable without upstream changes. Native replay takes plain decimal literals
in its trace, while Cedar policies use `decimal("...")`. The AWS documentation's
`eventResource` spelling is not asserted to be the native default schema spelling;
AWS service-schema integration and comparison remain item 37. Python bindings are
not needed for this implementation; an upstream contribution remains a separate
decision if measured session size makes replay expensive.

Rejected alternatives: executable expressions or a parser dependency; treating
missing facts as false before negation; silently rounding numeric bounds; treating
an empty collection as missing; allowing role entries to replace base safeguards;
removing class/household matching in anticipation of a future signer; one temporal
policy per class; accepting arbitrary response events without checking their
approval request; switching engines because the binary was not installed. The
approved cedarpy fallback was unnecessary because the real Dogwood gate passed.
Evidence lives only in [the verification log](../verification-log.md#item-7--complete-2026-09-18).

## Item 9 amendment — 2026-09-18

The pipeline takes an explicitly validated/compiled, household-bound policy bundle;
automatically treating stored seed versions as active was rejected. Identity is
resolved from household provider/sub links, and linked and explicitly claimed roles
are intersected in both evaluators. Caller-supplied Action authority is not trusted.
Fresh graph facts feed both policy and risk; unresolved ordinary conditions cannot
be approved, while known-false conditions can. Details and precedence are in
[architecture §3.4](../../ARCHITECTURE.md#34-internal-pipeline-contract-item-9).

Approval bindings include the full policy/artifact identity and initial soft gates,
not just the content hash. Current quorum and new/stricter gates are checked again at
redemption; cleared gates do not manufacture a new approval requirement. The native
wrapper accepts approval-before-action trace order within a single second, retaining
the Python ASK-creation deadline. Artificially advancing the clock to satisfy the
old wrapper inequality was rejected: native Dogwood already supports ordered events.

Pause/resume are reserved system permissions with matching local boundary rules,
so a household override cannot prevent a linked member from pausing or resuming in
the app. They introduce no grammar expansion. Dollar budgets and quiet hours now
run in the internal pipeline; per-class counts remain deferred. AWS enforcement,
authentication and policy activation remain with their original roadmap items.

## Item 11 amendment — 2026-09-18 (author-approved)

The CLI previews the stored policy referenced by the selected demo household,
validating its stored hash/name/version and compiling in memory. It explicitly
labels that policy unactivated and leaves stored status unvalidated. This resolves
item 11's former “active constitution” wording without pulling activation forward.
The existing pipeline evaluation and canonical Decision remain the only decision
path. Full command semantics are in [architecture §3.5](../../ARCHITECTURE.md#35-local-decision-preview-item-11).

The author selected explicit household UUID, demo-account subject, surface and
target flags; typed twin evidence; optional preview time and exact cost; explicit
hypothetical requester confirmation; canonical JSON stdout and 0/1/2 exit codes.
The existing signing-key prerequisite remains, avoiding a change to the mutation
interface. Nine initial action-request decisions replace the ambiguous “eight
worked examples”; later approval events are outside this CLI.

Rejected alternatives: silently activating or repairing stored seeds; requiring a
policy-file override; adding activation in Phase 1; defaulting a household or
inferring targets; pretending a supplied name authenticates a person; historical
replay; real-labeled caller evidence; interactive approval; custom response shapes
or outcome-specific exit codes; optional audit writers; new dependencies or
migrations. Existing invalid stored policies fail without repository-file fallback.
Local verification uses disposable fixtures, including unactivated v8; no new
remote CI run is required. [Evidence and local prerequisite limitation](../verification-log.md#item-11--2026-09-18).

## Constraint intake permissions amendment — 2026-09-21

`governance.record_constraint` and `governance.withdraw_constraint` are reserved
LOW-risk internal operations. The existing compiler emits linked-member permits
and unknown-member forbids; they cannot be redefined by a household and never
change pause state. Pipeline additionally enforces record ownership: members may
withdraw their own requests, owners may withdraw others', and any linked member
may release or renew a manual hold. A lower claimed role cannot acquire the
owner-only withdrawal privilege. Neither operation enters the future consumer
device-action enum. No condition grammar, approval quorum or temporal-policy
mechanism changes; the catalog now contains 25 classes.
