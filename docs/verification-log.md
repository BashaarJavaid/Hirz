# Verification log

The full evidence behind every `ROADMAP.md` item marked complete (or partially verified): the commands run, the numbers seen, the environment, and the CI run links. `ROADMAP.md` keeps one line per item and links here; `CHANGELOG.md` records what changed. Entries are appended verbatim from the verification that was run, never edited afterwards except to add a later run. See `CLAUDE.md` § Where records go.

---

## Item 1 — Complete (2026-09-17)

Verified: Python **1 passed**; TypeScript **1 passed per workspace**; all lint/type checks and dependency peer checks passed; locked installs left both lockfiles unchanged; `uv build` produced an sdist and wheel, and the wheel imported from a fresh environment outside the checkout. Temporary probes confirmed failing tests return failure in Python and both workspaces, and uncovered Python code fails the 80% gate. Initial Python coverage is 100% over **zero executable statements**, not an application guarantee. Items 2–5 were pending at item 1's completion.

## Item 2 — Complete (2026-09-17)

Verified on Docker Desktop **4.87.0**, Engine **29.7.2**, Compose **5.4.0**, macOS ARM64: authenticated curl returned **123 entities**, including `climate.ecobee`, `cover.garage_door`, `light.bed_light`, and `sensor.outside_temperature`; unauthenticated reads returned **401**; Hirz returned **200 {"status":"ok"}**; Postgres accepted the password-authenticated TCP query. A disposable Compose project passed fresh provisioning, unchanged credentials on rerun, bad/missing token rejection, wrong database password rejection, missing persisted-credential refusal, database-row/onboarding/token persistence across down/up, Jaeger absent by default, and optional-profile trace ingestion/retrieval. Temporary test volumes were removed; development volumes retained. Image manifests include ARM64 and AMD64; only ARM64 was executed. The Hirz image runs non-root without local credentials or dev dependencies. Python **19 passed**, **100% coverage over five runtime statements**; Ruff, strict mypy (including scripts), locked sync, and sdist/wheel build passed. No physical-device or household-action behavior is claimed; items 3–5 remain pending.

## Item 3 — Complete (2026-09-17)

Verified against a clean source snapshot of the implemented checkout, with a separate Compose project, newly generated credentials, and fresh volumes: doctor first reported three PASS and migrations FAIL, then **four PASS / exit 0** after `uv run alembic upgrade head`. Python **36 passed, 86.13% runtime coverage**; PostgreSQL integration **4 passed** in disposable databases (upgrade/repeated upgrade/downgrade/re-upgrade, no seeds, household-scoped account uniqueness and foreign keys, audit shape/default constraints, partial-schema/unknown-revision refusal, and refusal to generate a missing key over audit rows). Reinitialization preserved `.env` byte-for-byte; `alembic check` reported no new upgrade operations. Live invalid database password, invalid HA token, and missing/malformed key probes each returned four results and exit 1 without echoing credentials. Rebuilt non-root container returned `200 {"status":"ok"}`; authenticated HA returned 123 simulated-device entities and unauthenticated reads returned 401. Ruff, strict mypy including migrations, locked sync, sdist/wheel build, and a fresh-wheel CLI check passed. This is schema and diagnostics only: no history, seeds, repositories, pipeline, audit writer, or earned threat-model protection; items 4–5 remain pending.

## Item 4 — Complete (2026-09-17)

Verified: [main push run 35310102678](https://github.com/BashaarJavaid/Hirz/actions/runs/35310102678) passed all **11 jobs** on Ubuntu 24.04 x64 at merge commit `fdc06fca4499794b55a84ffcae6e8203654b2a9b` after PR #1. Python **36 passed, 86.13% coverage**; PostgreSQL integration **4 passed**; TypeScript **1 passed per workspace**. Lint/types, schema drift, four doctor checks, authenticated HA with 123 simulated entities and unauthenticated 401, Hirz liveness 200, package/fresh-wheel checks, non-root UID 10001, and disposable Compose cleanup passed. Five jobs explicitly defer scenario, add-on conformance, latency, Cedar, and release checks; browser tests and frontend bundles also remain deferred. This earns scaffold CI only, not an application or threat-model guarantee. Item 5 retains its separate second-person check.

Manual dispatch on the same main commit also passed all **11 jobs**: [run 35310359507](https://github.com/BashaarJavaid/Hirz/actions/runs/35310359507).

Local verification (2026-09-17): Python **36 passed, 86.13% coverage**; PostgreSQL integration **4 passed** in an isolated source copy with fresh Compose volumes; TypeScript **1 passed per workspace**. Ruff, strict mypy, ESLint, TypeScript, locked installs with unchanged lockfiles, package build/fresh-wheel import and CLI help, workflow YAML and shell syntax, schema-drift check, four doctor PASS results, authenticated HA with 123 simulated entities and unauthenticated 401, Hirz liveness 200, and container UID 10001 passed. Disposable resources were removed and development `.env` remained unchanged.

## Item 5 — Complete (2026-09-18)

Partially verified (2026-09-18): every command in the README's "Scaffold setup" and "Local development stack" sections was executed, on the existing development machine (not a clean one, and not by a second person), and matched the numbers already claimed above — Python **36 passed, 86.13% coverage**; TypeScript **1 passed per workspace**; ruff/mypy/eslint/tsc clean; `uv build` produced sdist+wheel; `hirz doctor` **4/4 PASS**; `check_dev.py` returned **123 HA entities** including all four required entities, unauthenticated 401, liveness 200; the documented stdin `curl --header @-` token check worked; the optional Jaeger profile check passed; PostgreSQL integration **4 passed**; shutdown preserved volumes and `.env`, and `git status` was clean afterward. The README's "## Quickstart" section is unaffected by this and remains unrun target state (`hirz scenario run` and the port-3000 app don't exist yet). This is execution evidence on a non-clean machine by the same person who built it, not the second-person/clean-machine check the verify line calls for — item 5 is not yet complete.

Completed 2026-09-18: a second person followed the README on a clean machine, as the `verify:` line requires, and the author reported that it worked. The author reported the outcome in conversation; the second person's machine, OS, and command output were not captured in this repository. If that output is still available, append it under this heading.

## Item 6 — Complete (2026-09-18)

Implemented and verified on the existing macOS ARM64 development machine with
Python **3.12.13**, uv **0.12.15**, and local Compose PostgreSQL **16.15
(Debian 16.15-1.pgdg13+2)**. This is local evidence, not a new GitHub Actions run.
The approved decisions and bootstrap exception are in
[ADR-002](./adr/ADR-002-postgres-over-dynamodb.md#item-6-amendment--2026-09-18-author-approved);
operating commands are in [development procedures](./development.md).

### Final checks

| Command/check | Observed result |
|---|---|
| `uv sync --locked` | Resolved 46 packages; checked 44 installed packages; no dependency changes |
| `uv run pytest -q` | **68 passed, 11 deselected**, **89.25%** runtime coverage (772 statements, 83 missed); 80% gate passed; 2.70 s |
| `uv run pytest -m integration --no-cov -q` | **11 passed, 68 deselected**; 5.77 s; uniquely named disposable PostgreSQL databases created and removed |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 51 files already formatted |
| `.venv/bin/mypy hirz/ scripts/ alembic/` | Success; 17 source files |
| `uv build` | Built `hirz-0.0.0.tar.gz` and `hirz-0.0.0-py3-none-any.whl` |
| Isolated `uv run --isolated --no-project --with <absolute-wheel-path> python -c ...` from `/private/tmp` | Installed 29 runtime packages; imported graph context/seed modules; CLI help listed `doctor`, `seed`, `context`; exit 0 |
| `uv run alembic upgrade head` on the development database | Exit 0; applied the explicit item 6 migration |
| `uv run alembic check` | `No new upgrade operations detected.` |
| `uv run hirz doctor` | **4/4 PASS**, exit 0: authenticated Postgres, HA demo/source label, P-256 signing probe, sole head plus graph tables/materialized view |
| `git diff --check` | No whitespace errors |

The wheel contains all five new graph package files. Seed YAML and checkout-only
migration/procedure files are used from the checkout; the package does not embed
the demo seed files. Neither package build nor the isolated help check claims a
standalone deployed application.

### Database and historical-read evidence

The integration suite exercises fresh upgrade/repeated upgrade/destructive
downgrade/re-upgrade and an existing `0001_initial` household/member/account through
upgrade. Existing identifiers and account links survive; unknown rate/location
facts are not invented. Metadata comparison finds no drift, and removing the
materialized view causes the migration-presence check to fail. The foundation's
existing audit/key-safety tests continue to pass.

Graph tests cover both seeds, untouched semantic repetition, refusal of changed
and evolved households, exact validity boundaries and before-creation reads,
observations received after their measurement time, observation age at the
requested instant, same-time/backdated/stale-version refusal, future and
out-of-order observation rejection, and clearing optional values on replacement.
A new entity cannot be inserted before another entity's latest household write.
Two concurrent edits using one expected version yield **one successful edit and
one version conflict**, with one archived version. Cross-household account foreign
keys and private repository lookups refuse the other home's member. Public
snapshots contain no account subjects or channel/safe-word hashes. A current
context read is observed as **one SQL statement**.

A failure in the second seed rolls back the first seed. An injected materialized
view refresh failure rolls back both new seeds; a separate update-refresh failure
preserves the previous graph, history count, and view contents. No seed operation
writes audit rows or activates a policy.

Service-free tests exercise typed models, malformed/duplicate-key YAML,
references and demo-only input restrictions, historical query bounds, all five
scope projections, household-keyed caches, copy isolation, increasing observation
age, explicit stale-read opt-in, no cached historical reads, no fallback for bad
SQL/malformed data/missing households, and CLI arguments/credential-safe errors.
Actual SQL history and transactional semantics are verified by PostgreSQL, not
inferred from mocked connections.

### CLI runs

`uv run hirz seed constitutions/quinn-home.yaml constitutions/quinn-parents.yaml`
returned exit 0 with:

```text
quinn-home: loaded; household 536fa8ee-854e-56ca-8c5d-5ba418e710a0;
            3 members, 9 assets; constitution 7, unvalidated
quinn-parents: loaded; household bf745178-9146-5952-a310-f1d7e563977b;
               2 members, 2 assets; constitution 1, unvalidated
```

An immediate repeat returned `unchanged` for both households, preserving their
initial `valid_from` of **2026-09-18T17:42:21.620752+00:00**.

The local home UUID with `--scope energy` returned the car, home battery, solar,
and dishwasher (**4 assets, 4 twin bindings, 0 observations**), `stale: false`,
and `policy_status: unvalidated`. The parents' UUID with `--scope people` returned
**2 members, 1 trusted contact, 1 simulated verified Hirz-app method**, and no
private hash/account fields. Malik's contact has no parent-household membership.

The home UUID with `--scope people --as-of 2026-09-18T17:42:21.620752Z` returned
exit 0 with the three initial members and the seeded expected-arrival window.
For an actual historical change, the integration CLI demonstration targets only
a disposable database, runs the real argument parser and serializer, and prints:

```text
Historical CLI: at 12:00Z = Mom; current = Mom updated; preference = 72; both exit 0.
```

That demonstration was also run visibly with
`uv run pytest tests/integration/test_graph_database.py -m integration --no-cov -q -s`:
**7 passed**. Only its connection factory is redirected to the disposable database;
the developer's seeded households were not edited for the demonstration.

### Intermediate failures, limits, and friction check

Initial restricted execution of the old service-free suite returned **34 passed,
2 failed** because the existing WebSocket fixture could not bind localhost
(`PermissionError: [Errno 1] ... operation not permitted`). Docker socket and uv
cache access were likewise restricted; authorized escalation resolved all three.
These repeat [friction-log entry 6](./friction-log.md#entries), not a new upstream
defect. An early test-collection run exposed two new files named `test_graph.py`;
the integration file was renamed `test_graph_database.py`. This was an
implementation mistake, not third-party friction.

Intermediate passes were: **32** new service-free graph tests; **4** original
PostgreSQL tests; then **68** service-free tests at **89.80%** and **9** integration
tests; then **68** at **89.35%** and **10** integration tests after the additional
time/rollback guards. The final results above supersede those intermediate runs.
A heading-only instruction-file parity probe also caught the pre-existing
AGENTS-specific introductory sentence; substantive guidance is synchronized, and
that file-identification difference was retained.

No AWS deployment, new CI run, browser/TypeScript change, 20 ms context benchmark,
production throughput measurement, policy evaluation, signed audit behavior, or
device action was performed or claimed. The running Compose liveness container
was the existing image; Python/CLI checks exercised the updated checkout and the
isolated built wheel. Whole-view refresh serialization and unpartitioned
observation history retain their approved limits. All threat-model rows remain
unchanged. The local database remains migrated and seeded, and the development
stack remains running. Friction-log review found no new entry to add.

### Graph policy-fact quantization — 2026-09-18

Task 1 follow-up on branch `phase-1`, macOS, Python 3.12.13, pytest 9.1.1,
Hypothesis 6.168.0. Numeric policy facts remain floats: graph validation rounds
with `round(value, 4)` and then checks the unchanged strict policy `number()`.
The shared validator covers observation `soc`, `temp_f`, `target_f`, `power_kw`,
asset-policy `soc_min`, and only temperature preferences. Physical parameters,
location, and confidence retain their existing validation.

Commands below used `UV_CACHE_DIR=/private/tmp/hirz-uv-cache`; the fresh import
used `PATH="$PWD/.venv/bin:$PATH"` to select the project interpreter. Both pytest
commands ran with authorized local socket/database access; integration fixtures
created and removed uniquely named disposable databases.

| Command | Output |
|---|---|
| `python -c "import hirz.graph.models"` | Exit 0, no output; fresh interpreter confirms no import cycle |
| `uv run ruff check . && uv run ruff format --check . && uv run mypy hirz/ scripts/ alembic/` | `All checks passed!`; `84 files already formatted`; `Success: no issues found in 40 source files` |
| `uv run pytest` | `572 passed, 47 deselected in 58.41s`; `Required test coverage of 80% reached. Total coverage: 86.68%` (3002 statements, 400 missed); graph models: 100% |
| `uv run pytest -m integration --no-cov` | `47 passed, 572 deselected in 31.67s` |
| `git diff --check` | Exit 0, no whitespace errors |

Direct model/policy probe, run with `uv run python -`:

```python
from hirz.graph.models import ObservationState
from hirz.constitution.conditions import attribute

state = ObservationState(soc=0.1 + 0.2, temp_f=71.123456)
print(state.model_dump_json(exclude_none=True))
print(
    "policy temp_f:",
    attribute({"asset": {"state": state.model_dump()}}, "asset.state.temp_f"),
)
```

Output:

```text
{"soc":0.3,"temp_f":71.1235}
policy temp_f: 71.1235
```

The unit suite verifies all requested numeric fields, temperature-only preference
rounding, integer input, rejection outside Cedar's range and of nonfinite/bool
values, and that `number()` still rejects excess precision. The Hypothesis
property samples finite temperatures in [-1000, 1000] and resolves the stored
value through `attribute()` without `FactError`. Both the unit repository check
and the real PostgreSQL observation/history test confirm that writing
`soc=0.30000000000000004` then `soc=0.3` is a no-op on the second write; the
PostgreSQL snapshot contains `0.3`.

The initial lint command reported `I001` for the new Hypothesis import;
`uv run ruff check --fix tests/unit/test_graph.py` reported
`Found 1 error (1 fixed, 0 remaining).` The final checks above passed.
Friction-log review found no new entry earned; temporary uv cache and authorized
local socket access use the already documented entry 6 procedure.
No Phase 2 implementation, device action, scheduler implementation, new CI run,
AWS action, or push was performed. Scheduler authority and Phase 2 fact homes
are documentation-only requirements; current-phase guidance remains accurate
and neither instruction file changed.

## Item 7 — Complete (2026-09-18)

Implemented and verified locally on macOS ARM64, Python **3.12.13**, uv
**0.12.15**, Rust **1.98.1**, Hypothesis **6.168.0**, Docker Engine **29.7.2**,
and the existing local PostgreSQL 16 service. This is **local evidence**; no new
GitHub Actions run or AWS comparison is claimed. The approved semantics and
rejected alternatives are recorded in [ADR-003](./adr/ADR-003-constitution-yaml-to-cedar.md#item-7-amendment--2026-09-18-author-approved-semantics)
and [ADR-004](./adr/ADR-004-no-ml-risk-scoring.md#item-7-catalog-amendment--2026-09-18-author-approved).

### Engine setup and gate

Fetched upstream into `/private/tmp/hirz-item7-dogwood`, checked out
`996d756de1013b7ae209a14f566a80375a59f2f0`, installed Rust into task-specific
temporary directories without changing shell setup, and ran
`cargo build --release -p dogwood-cli`. The revision has no upstream Cargo.lock;
the generated lock is retained in `scripts/dogwood.Cargo.lock`. A subsequent
`cargo build --locked --release -p dogwood-cli` passed. Native binary reports
`dogwood 1.0.0`; an ignored local copy is at `.tools/dogwood`.

The **complete** home policy passed native `validate` with
`passed: true`, `passed_without_warnings: true`, `errors: []`, `warnings: []`.
Parents' full constitution also validated. Native `check-parse` reports **52
policies**, **one temporal policy**, and **one temporal operator**; all resource,
principal, household, class, hash, session and TTL correlations fit that operator.
Matching fields use the native default event schema, including `callerResource`.
The compiled manifest checks 25 temporal policies and a maximum 1440-minute window.

| Gate trace | Actual result |
|---|---|
| Permitted approval request + approved response, then matching unlock | Permit |
| Same unlock without an approval | Deny |
| Approval for another class, same hash | Deny |
| Ten-minute approval presented to a thirty-minute permit | Deny |
| Household A approval presented for household B | Deny |

The suite also checks two genuine TTL groups and two combined household policy
sets, expiry (including permit at exactly 1800 seconds and deny at 1801), rejected
approvals, wrong hashes/resources/principals/sessions, requester/approver/channel/
quorum restrictions, current vetoes and hard bounds after earlier approval, actual
action/class disagreement, governance-action exclusion, and malformed/failed/
timed-out subprocesses. Approval requests are authorized before response events
enter the local replay; the supplied facts do not authenticate a human or passkey.
Unknown action names are escaped and cannot inject trace syntax.

### Final runnable checks

For native checks `HIRZ_DOGWOOD` pointed at the built pinned binary. The tool
sandbox required escalation for loopback/socket and Docker access; no application
credentials were printed and no persistent household rows were changed.

| Command/check | Observed result |
|---|---|
| `uv run pytest` | **182 passed, 11 deselected**, **93.44%** coverage (1813 statements, 119 missed), 80% gate passed; **50.54 s** |
| `uv run pytest -m integration --no-cov` | **11 passed, 177 deselected** at that run, **5.69 s**; corrected seeds exercised in uniquely named disposable databases, then removed |
| `uv run pytest tests/cedar_conformance -k property --no-cov --hypothesis-show-statistics` | **3 passed, 33 deselected**, **27.10 s**; each property reports **200 passing, 0 failing, 0 invalid**, stopped at `settings.max_examples=200` |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 66 files already formatted |
| `uv run mypy hirz/ scripts/ alembic/` | Success; 30 source files |
| `uv build` | sdist and `hirz-0.0.0-py3-none-any.whl` built |
| Isolated wheel installation in `/private/tmp/hirz-item7-wheel`, cwd `/private/tmp` | Both packaged YAML resources load: 21 classes and 21 situation groups; installed CLI validates home with the native binary |
| `docker build --tag hirz-item7:check .` | Passed; pinned Rust builder and dependency lock, native binary copied into existing Python image |
| Container with read-only fixture mount | UID **10001**, Cargo absent, both YAML catalogs load; native full-policy validation, matching-approval permit and no-approval deny passed |
| Final rebuilt container smoke | UID 10001, Dogwood present, Cargo absent, both catalogs packaged |
| `git diff --check` | No whitespace errors |

The three deterministic properties cover bounds/missing/null facts and every role,
condition precedence/ordered overrides and Boolean preflight, and approval traces.
There are **600** generated examples per full property run, all using the native
Dogwood evaluator; this is not a mock engine comparison. Direct cases additionally
cover schedule endpoints, exact-zone occupancy, scoped IDs, membership/time
compilation, all catalog roles/situations, both seeds, schema refusals, immutable
facts, exact YAML decimal text, renderer/YAML round trips, CLI exits, and structured
diagnostics. Worked-example assertions versus downstream work are mapped in
[the constitution spec](./constitution.md#61-what-the-worked-examples-verify-in-item-7).

### CLI output and preview

Ran the actual user workflows (JSON stdout; all exit 0):

```text
uv run hirz constitution validate constitutions/quinn-home.yaml
  valid: true; version: 7; engine: dogwood-local; analysis: not analyzed: local mode
uv run hirz constitution compile constitutions/quinn-home.yaml
  valid: true; policy + schema + manifest; 21 catalog actions; one TTL group (30)
uv run hirz constitution preview constitutions/quinn-home.yaml /private/tmp/hirz-item7-v8.yaml
  Unexpected visitor: ask on phone → never
  Expected arrival: still asks on your phone
  Hirz does not identify the visitor
```

The temporary v8 is a standalone serialization of home v7 with version 8 and
`never_for: [unexpected_visitor]` on door unlock; it was not activated or stored.
Preview also returns changed diagnostic situations and relevant unchanged
situations without UI truncation. The existing stored seeds were inspected in an
explicit `SET TRANSACTION READ ONLY` transaction, then rolled back:

| Stored version | Status | Existing stored hash | Validation result |
|---|---|---|---|
| Home v7 | unvalidated | `e422d43213ce9e97e3150867eb5e48807e5e54f0b1d6bb5fe51d96e3d1cc94c6` | `security.access_code_share: security approval channels must exclude alexa, including never rules` |
| Parents v1 | unvalidated | `d2de39f61464a053eee02ef3973e9d0baef941a042730e147d18d743fa82540d` | Same explicit validation error |

No reseeding, reset, migration, or stored hash rewrite was used to make those old
versions validate. Only the repository seed files' security channels changed.

### Failures corrected and practical limits

Early compiler checks rejected integer-form decimal strings such as `decimal("76")`;
Cedar requires digits on both sides of the decimal point. Early trace serialization
also used Cedar extension syntax, yielding `type error: expected decimal, got
string`; native traces require plain decimal literals. Both implementation errors
were corrected and covered by actual native replay. The first container attempt
excluded the new Cargo lock via `.dockerignore`; adding only that lock to the
allowlist fixed the build. Sandbox GitHub lookup/escalation and the missing
upstream lockfile are recorded in [friction entries 8–9](./friction-log.md).
Earlier successful checkpoints were 109 targeted tests, then 177 full-suite tests
at 92.19%, then 181 at 93.33%; the final expanded suite result is above.

The CLI is usable; no cedarpy fallback or upstream Python-binding change was
needed. The local wrapper replays prefixes for its small approval history rather
than implementing temporal semantics itself. This is a same-process-trust-domain
local evaluator, not an external AWS boundary. `cedar-conform` now requires native
engine/compiler tests and fails for missing tooling; that workflow has not been
run remotely during this task. AgentCore event-schema integration/comparison and
automated reasoning remain item 37. Runtime risk, budgets/quiet hours, graph fact
assembly, activation, authenticated approval/redemption, hash recomputation,
signed audit, device actions and relock are **not** claimed here. All corresponding
threat-model protections remain planned.

### Final review rerun — 2026-09-18

Review found and corrected two implementation issues before handoff: the English
label formatter was replacing decimal points in numeric bounds (`0.3` became
`0 3`), and role/class condition references had redundant boundary fields alongside
the canonical requester role/action class. Numeric rendering now preserves the
value; conditions directly use the same canonical fields as authorization, so
shadow copies cannot disagree. Regression assertions cover both. The first
renderer rerun passed **182 tests**, **93.44%** coverage, **51.25 s**.

After the canonical-field correction, the final command was
`uv run pytest --hypothesis-show-statistics`: **183 passed, 11 deselected**,
**93.40%** coverage (1817 statements, 120 missed), **48.99 s**. Each of the three
native properties again reported **200 passing, 0 failing, 0 invalid** cases.
Ruff passed, formatting checked 66 files, strict mypy passed over 30 source files,
and instruction parity/workflow structure checks passed. The final wheel and
container were rebuilt: installed-wheel compilation outside the checkout and
container UID 10001/native validation/approval permit/no-approval deny all passed,
with explicit checks for numeric English, canonical fields, packaged catalogs,
and absence of Cargo. This supersedes the earlier checkpoint totals above; graph
integration and the preserved stored-seed observations are unchanged.

## Item 8 — Complete (2026-09-18)

Implemented the standalone risk scorer and shared floor function, with the
author-approved semantics recorded in [ADR-004](./adr/ADR-004-no-ml-risk-scoring.md#item-8-amendment--2026-09-18-author-approved)
and [architecture §5.3](../ARCHITECTURE.md#53-risk-engine). The existing catalog's
21 profiles retain their prior base bands, impacts and reversibility strings;
freshness policy is added to that catalog. The constitution validator now uses
the shared floor function. This is scoring and validation, not a runtime pipeline.

### Environment and commands

Local Darwin arm64, Python **3.12.13**, uv **0.12.15**, pytest **9.1.1**,
Hypothesis **6.168.0**, existing pinned native `.tools/dogwood` reporting
**1.0.0**. No dependencies or lockfiles changed. Tooling used
`UV_CACHE_DIR=/private/tmp/hirz-uv-cache` after the sandbox refused the normal
uv cache. The full suite used `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`.

| Command | Observed result |
|---|---|
| `uv run --locked pytest tests/unit/test_risk.py --no-cov -q` | **260 passed in 0.77s**, no warnings |
| `uv run --locked pytest --hypothesis-show-statistics` with sandbox escalation for existing disposable localhost tests | **443 passed, 11 deselected in 49.32s**; **93.75%** runtime coverage (1920 statements, 120 missed), 80% gate passed |
| Native generated conformance, included in that full run | Three properties, each **200 passing, 0 failing, 0 invalid** cases: **600** total |
| Coverage of `hirz/risk/__init__.py` and `hirz/risk/engine.py` | **100% line coverage** each (26 and 77 statements respectively); not a claim of exhaustive runtime security |
| `uv run --locked ruff check .` | `All checks passed!` |
| `uv run --locked ruff format --check .` | `68 files already formatted` |
| `uv run --locked mypy hirz/ scripts/ alembic/` | `Success: no issues found in 31 source files` |
| `uv build` | Successfully built `dist/hirz-0.0.0.tar.gz` and `dist/hirz-0.0.0-py3-none-any.whl` |
| Documented standalone API example | Extracted and executed the exact Python block in [development](./development.md#standalone-risk-scoring-item-8); all assertions passed; output below |
| `git diff --check` | Exit 0, no whitespace errors |

The risk checks cover all classes, matching/nonmatching factors, all 32
combinations of the five applicable HVAC increments, saturation with retained
evidence, stale-factor deduplication, exact freshness/deviation/guard boundaries,
sleep scope, missing and malformed facts, malformed catalog data, injected
exceptions, sanitized failure output, immutable/revalidated facts, deterministic
outputs and unchanged inputs. Both seed constitutions reject static HIGH/CRITICAL
auto changes; dynamically CRITICAL risk keeps `never_auto` across validated
auto/ask/never rule variants. Existing hard bounds still resolve to denial.

### API smoke output

```text
ordinary {"band":"low","base_band":"low","factors":[]} floor=none
escalated {"band":"critical","base_band":"low","factors":[{"factor":"occupant_asleep","effect":"+1 band","evidence":"An occupant is asleep in the affected area."},{"factor":"state_stale","effect":"+1 band","evidence":"Observation age 301.0s exceeds 300s."},{"factor":"deviation_from_baseline","effect":"+1 band","evidence":"Requested temperature differs from requester's preference by 7°F (>6°F)."}]} floor=never_auto
exception {"band":"critical","base_band":"low","factors":[{"factor":"scoring_error","effect":"→ CRITICAL","evidence":"Risk calculation failed."}]} floor=never_auto
```

These are labeled synthetic preview inputs and a deliberately injected exception,
not observed household conditions. No device, model, network service, database,
or active constitution was involved in the smoke example.

### Earlier failures and limits

The first focused run reported **4 failed, 256 passed**. Two test setups compared
a supplied risk rule with different seed-rule bounds; two mode variants retained
per-role restrictions that made the variants invalid constitutions. Corrected the
tests to select matching guards and construct valid variants. A deliberately
bypassed Pydantic fact instance emitted a serialization warning; scoring now
suppresses serialization warnings during its revalidation so malformed values
are not echoed. The focused rerun above passed without warnings.

The first full run inside the sandbox reported **2 failed, 441 passed,
11 deselected in 49.53s**, with the same **93.75%** coverage and all 600 generated
conformance cases passing. Both failures were existing WebSocket token tests
unable to bind a temporary localhost port, not scorer failures. The full rerun
with sandbox escalation passed as recorded above. Cache and socket friction are
recorded once in [friction log entry 6's item 8 follow-up](./friction-log.md).

No remote CI run, AWS comparison, database integration run, frontend checks,
container rebuild or installed-wheel smoke was performed for this Python-only
item. No graph extraction, identity resolution, runtime Decision, approvals,
audit writes, activation, or device execution is claimed. Pipeline integration
is item 9, `hirz decide` item 11, and Protect extraction item 32. Stored seeds
remain unvalidated and unchanged. Runtime threat-model rows remain Planned.

Final documentation review: `git diff --check` passed. A Python comparison of
the catalog against `git show HEAD:hirz/risk/classes.yaml` confirmed all 21 old
profiles are identical after excluding the added freshness field. Comparing
`AGENTS.md` and `CLAUDE.md` from `## Project` onward confirmed matching bodies.


### Missing HVAC baseline and exception-class logging — 2026-09-18

Applied the [author-approved baseline amendment](./adr/ADR-004-no-ml-risk-scoring.md#missing-hvac-baseline-amendment--2026-09-18-author-approved).
No seed, canonical factor literal, dependency, instruction-file or Phase 2 change.
The four failure logs from `de074cf` now record operation and exception class,
plus household ID for the pipeline, without exception text or traceback.

Environment: Darwin arm64, Python **3.12.13**, uv **0.12.15**, pytest **9.1.1**,
native Dogwood **1.0.0**. Commands ran from the checkout on `phase-1`, with
`UV_CACHE_DIR=/private/tmp/hirz-uv-cache`. Database commands and full suites used
sandbox escalation for existing local PostgreSQL and disposable loopback tests.
The preview used `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`; tests discovered that binary
through the existing `tests/conftest.py`. Local date is 2026-09-18; the CLI clock
below is UTC on 2026-09-19.

Commands and exact final outputs (all exit 0):

```text
$ uv run pytest tests/unit/test_risk.py tests/unit/test_pipeline.py::test_connection_failure_logs_household_without_params --no-cov -q
281 passed in 0.88s

$ uv run ruff check . && uv run ruff format --check . && uv run mypy hirz/ scripts/ alembic/
All checks passed!
84 files already formatted
Success: no issues found in 40 source files

$ uv run pytest
Required test coverage of 80% reached. Total coverage: 86.51%
================ 564 passed, 47 deselected in 60.40s (0:01:00) =================

$ uv run pytest -m integration --no-cov
===================== 47 passed, 564 deselected in 36.72s ======================
```

The service-free suite includes native Dogwood conformance; risk engine line
coverage is **100%** (76 statements). No failing test runs occurred in this task.
Existing tests changed:

- `test_missing_required_facts_fail_closed`: removed only the HVAC baseline case,
  which asserted the superseded CRITICAL contract; other missing facts still deny.
- `test_invalid_action_parameter_fails_closed`: runs missing/null/nonnumeric targets
  with both a stored and null baseline, proving target validation is retained.
- `test_connection_failure_logs_household_without_params`: expects the message to
  end with `error=RuntimeError`; existing sentinel exclusions remain intact.

New `test_hvac_without_baseline_has_no_deviation` covers both omitted and explicit
null baselines, asserting LOW and no factors with otherwise clean inputs. Existing
`test_factor_applicability` (72 °F target, 65 °F baseline) and
`test_deviation_exact_boundary` continue to prove >6 °F raises deviation risk.

Development database commands:

```sh
uv run hirz context 536fa8ee-854e-56ca-8c5d-5ba418e710a0 --scope all
uv run hirz decide --household 536fa8ee-854e-56ca-8c5d-5ba418e710a0 --as malik --surface alexa --action energy.hvac_adjust --adapter twin --entity hvac.living_room --zone 1573afea-10d3-52a1-92cc-36121a6dbbb0 --params '{"target_f":72}'
```

The context returned living-room HVAC zone
`1573afea-10d3-52a1-92cc-36121a6dbbb0` and **0 observations**. Full `decide` stdout:

```json
{"decision":"deny","event_type":"DENY_RISK","action_id":"act_8fade72f0d1a4fa990eb887e6077ca90","risk":{"band":"critical","base_band":"low","factors":[{"factor":"scoring_error","effect":"→ CRITICAL","evidence":"Missing required fact: sleeping_in_target_zone."}]},"constitution":{"version":7,"rule":"energy.hvac_adjust","mode":"ask","conditions_met":false},"boundary":{"engine":"dogwood-local","result":"not_evaluated","reason":"terminal before boundary","context_hash":null,"roles":{}},"approval":null,"budget":null,"explain":{"facts":[],"considered":[],"rejected":[]},"audit_id":null}
```

Full stderr:

```text
Hypothetical dry run; policy v7 is unactivated (stored: unvalidated); clock=2026-09-19T04:11:32.112578+00:00; current graph, not historical replay. No authentication, approval, execution grant, device operation, or audit write. Supplied evidence is simulated; boundary is dogwood-local.
```

The expected `DENY_RISK` names `sleeping_in_target_zone` in `scoring_error`, not
`baseline_target_f`. The preview remains hypothetical and the stored policy
unactivated; this does not claim successful pre-warming or device execution.
The isolated unit checks prove the baseline exception independently of the
seed's missing observations. No development graph or seed data was changed.

`git diff --check` passed. Friction log reviewed: existing documented cache/socket
setup was used successfully; no new third-party error, delay or workaround earned
an entry. No remote CI run, push, AWS work, activation or Phase 2 work was performed.

## Item 9 — Complete (2026-09-18)

### Scope and environment

Implemented the approved internal deterministic pipeline, canonical Decisions,
immutable proposals, household-scoped approvals/votes, atomic single redemption,
daily exact-Decimal budget reservations, and versioned pause/resume. The signed
append dependency is pulled forward from item 10. A committed grant is the audit
row referenced by `actions.grant_seq`; no physical execution is claimed.
[Architecture contract](../ARCHITECTURE.md#34-internal-pipeline-contract-item-9);
[storage decision](./adr/ADR-002-postgres-over-dynamodb.md#item-9-amendment--2026-09-18).

Local Darwin arm64; Python 3.12.13, SQLAlchemy 2.0.54, cryptography 50.0.1,
rfc8785 0.1.4. Existing `.tools/dogwood`, pinned source revision
`996d756de1013b7ae209a14f566a80375a59f2f0`, used through `HIRZ_DOGWOOD`.
PostgreSQL was reached at 127.0.0.1:5432 using existing `.env` credentials.
All migration, race and API-smoke writes used uniquely named disposable databases;
the ordinary development database and its stored seed policies were not migrated
or activated. No credentials were initialized/replaced. No AWS or CI run is claimed.

### Checks actually run

The installed virtual environment was updated with `uv add 'rfc8785==0.1.4'`;
`pyproject.toml` and `uv.lock` are pinned. Tests used that environment directly:

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/pytest -q --tb=short
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/pytest -m integration --no-cov -q --tb=short
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy hirz/ scripts/ alembic/
git diff --check
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/python scripts/smoke_pipeline.py
```

The service-free suite includes required native Dogwood conformance, the existing
generated corpus, same-second ordering, and reserved governance permissions.
Its final summary and coverage table:

```text
Name                              Stmts   Miss  Cover   Missing
---------------------------------------------------------------
hirz/__init__.py                      0      0   100%
hirz/api/__init__.py                  0      0   100%
hirz/api/app.py                       5      0   100%
hirz/cli.py                         105      0   100%
hirz/constitution/__init__.py         0      0   100%
hirz/constitution/boundary.py       107     10    91%   92, 103-107, 125, 135, 151, 164
hirz/constitution/cli.py             29      0   100%
hirz/constitution/compiler.py       151      3    98%   120, 125, 254
hirz/constitution/conditions.py     268     12    96%   95, 114, 131, 158-159, 182, 187, 210, 228, 298, 307, 319
hirz/constitution/evaluator.py       99      1    99%   113
hirz/constitution/preview.py         54      1    98%   131
hirz/constitution/render.py          65      1    98%   50
hirz/constitution/schema.py         212      8    96%   58, 138, 248, 267, 288, 305, 316, 319
hirz/db.py                           88     19    78%   319-323, 327, 331-341, 348-360
hirz/graph/__init__.py                0      0   100%
hirz/graph/context.py               120      4    97%   82, 85, 88, 237
hirz/graph/models.py                156      0   100%
hirz/graph/repository.py            137     17    88%   144, 186, 192, 194-208, 210, 230-232
hirz/graph/seeds.py                 147     43    71%   37, 59, 61, 100, 115, 176-214, 228-271
hirz/local.py                        31      0   100%
hirz/pipeline/__init__.py             0      0   100%
hirz/pipeline/audit.py               37     19    49%   25, 43-114
hirz/pipeline/context.py            145     16    89%   56, 65, 92, 102-108, 149, 151-156, 158, 160, 169, 201, 254
hirz/pipeline/hashing.py             38      3    92%   24, 55-56
hirz/pipeline/models.py             150      1    99%   102
hirz/pipeline/service.py            383    199    48%   114, 121, 147, 150-162, 174-191, 198-211, 499-518, 523-534, 539, 549-564, 567-575, 585-626, 642-643, 649-683, 693, 704, 711-751, 755-756, 777-815, 828-915, 920-1087
hirz/risk/__init__.py                26      0   100%
hirz/risk/engine.py                  77      0   100%
---------------------------------------------------------------
TOTAL                              2630    357    86%
Required test coverage of 80% reached. Total coverage: 86.43%
485 passed, 24 deselected in 53.17s
```

The real PostgreSQL suite covers populated upgrades, metadata agreement, scoped
foreign keys and destructive downgrade only in disposable databases, plus the new
pipeline tests. Its final run (including the final claimed-role vote restriction
and native dual-role check):

```text
........................                                                 [100%]
24 passed, 485 deselected in 12.86s
```

Static checks: `All checks passed!`; `76 files already formatted`;
`Success: no issues found in 37 source files`; `git diff --check` exited 0.

### Pipeline evidence

- Explicit NEVER/hard guards skip scoring; risk-dependent NEVER outranks CRITICAL.
  Tests cover DENY_RISK, VERIFY only for financial verification, HIGH escalation,
  requester confirmation, unresolved versus known-false conditions, pause, quiet
  hours, budget equality/crossing, invalid targets and fail-closed boundary results.
- Context checks cover incomplete occupancy, whole observations, missing state,
  stale readings, simultaneous conflicts, ambiguous bindings/preferences,
  household-scoped evidence, source preservation and local overnight quiet hours.
- Identity comes from current household account links. Tests include forged Action
  requester metadata, claimed-role intersection, account revocation, requester
  demotion, caregivers in all-adult quorum and an empty owner quorum. The native
  security grant evaluates both linked owner and claimed adult roles; a claimed
  child cannot cast the owner's vote. Missing/wrong-hash security evidence is refused.
- TOCTOU checks change class, target (including zone), nested params, scheduled time,
  requester metadata and cost. Normalization covers reordered keys, equivalent UTC
  times and numeric forms, with non-finite/noncanonicalizable data refused.
- Repeated ASK reuses the original request/deadline; duplicate votes leave one
  persisted vote. Rejection, expiry, changed policy, new pause requirements,
  cleared pause, replay and expiry after native authorization are exercised.
  Boundary denial preserves the approved request for retry inside its TTL.
- **20 concurrent redemptions: exactly 1 committed grant and 19
  DENY_APPROVAL_USED Decisions.** The committed reservation was 6; two further
  approved actions costing 3 each raced against the remaining allowance of 4:
  one EXECUTE and one DENY_BUDGET, final reservation total 9. These are synthetic
  test dollar inputs, not product savings claims.
- Equality at a cap of 1 creates ASK_BUDGET and can reserve exactly 1 after approval;
  the next 0.01 request is denied. Signing, audit INSERT and COMMIT failures each
  leave no grant, approval consumption or dollar reservation. Pause failures leave
  no graph/history/view change or AUTONOMY transition; repeated pause does not add
  another transition event. Existing caller transactions are refused and preserved.
- Every row in the native approval flow was independently checked in the test for
  contiguous sequence, previous hash, RFC 8785 envelope hash and ECDSA Prehashed
  signature; persisted Decision audit IDs match their allocated sequences.
  An incompatible key and an invalid audit pointer are refused. This is testing of
  the append primitive, not delivery of item 10's public verifier/export.

### Runnable API output

`scripts/smoke_pipeline.py` completed against native Dogwood and its own disposable
database, asserting the sequence and exact reservation before cleanup:

```text
evaluate=ASK_CONSTITUTION audit=None
propose=ASK_CONSTITUTION; vote=APPROVED
redeem=EXECUTE; boundary=dogwood-local; reserved=0.25
replay=DENY_APPROVAL_USED; committed_grants=1; device_operations=0
stored_seed=unvalidated; source=twin; public_authentication=not_implemented
```

### Failures found and fixed during implementation

The first regression run, before pipeline tests were added, reported 447 passed,
10 failed and 73.06% coverage. Stale catalog/policy-count assertions needed the two
reserved governance classes; loopback tests also hit the existing sandbox restriction.
The initial new precedence test missed the seed's required requester confirmation
and was corrected. The pause integration test then exposed `Row version conflict.`:
the graph update now supplies its current version token. Injected COMMIT failure
exposed a physical transaction remaining open after SQLAlchemy closed its transaction
object (`assert 9 == 7` audit-row count). Failed owned transactions now discard the
connection, and the rollback checks pass. An idle-connection preflight preserves
any transaction owned by the caller. Final review also required action-hash-bound
security evidence and claimed-role restrictions on votes; the final native/database
suite verifies both. No known failing check remains.

The uv cache, sandbox DNS and local PostgreSQL/socket restrictions repeated existing
friction entries; exact errors and successful workaround are appended to
[the friction log](./friction-log.md). No upstream Dogwood defect or fallback is claimed.

### Deliberately outstanding

Item 10 still owns verifier/export and the 100-concurrent-decision gate; item 11
owns `hirz decide`; item 19 owns physical execution. Public authentication/passkeys,
policy activation, adapters, AWS enforcement/anchors, settlement/refunds and
per-class action-count limits are not implemented here. Stored policies remain
unvalidated. Synthetic internal passkey evidence proves no public authentication
or compromised-worker protection. The global graph lock remains a throughput
ceiling. A lost commit acknowledgment can leave the caller uncertain, but replay
cannot grant twice. Threat claims are limited to the tested internal grant path.

### Item 9 CI build check — 2026-09-18

[Run 35407827100](https://github.com/BashaarJavaid/Hirz/actions/runs/35407827100)
at `f6ed4d0` passed ten jobs; `build` failed with `AssertionError` in
`Fresh-wheel import and CLI outside the checkout`. Its catalog assertion still
expected 21 entries; item 9 added `governance.pause_automation` and
`governance.resume_automation`, and both packaged catalogs contain 23.
Updated the assertion and its output to 23, matching the existing unit check.

Local verification on macOS/Python 3.12.13: `UV_CACHE_DIR=/private/tmp/hirz-ci-uv-cache uv build`
built the sdist and wheel. Installed the wheel with `uv pip install` into a fresh
`/private/tmp/hirz-item9-wheel-smoke` virtual environment and ran the CI import,
catalog assertion and `hirz --help` from `/private/tmp`, outside the checkout.
Output: `PASS installed hirz 0.0.0` and
`PASS packaged catalogs: 23 classes, 23 situation groups`; CLI help exited 0.
Installation required escalation for the previously documented sandbox cache/DNS
restrictions. No new third-party defect was found. The change has not been pushed;
the full GitHub Actions build and its later container checks have not been rerun.

## Item 10 — Complete (2026-09-18)

### Scope and environment

Implemented the author-approved audit verifier/export contract in
[architecture §5.10](../ARCHITECTURE.md#510-audit-ledger), with choices and rejected
alternatives in [ADR-002](./adr/ADR-002-postgres-over-dynamodb.md#item-10-amendment--2026-09-18-author-approved).
Item 9's writer and signed envelope remain unchanged. New reads and exports do not
append audit events or mutate household state. No dependencies or migrations added.

Local Darwin arm64, Python 3.12.13, PostgreSQL 16 from the existing local Compose
stack, SQLAlchemy 2.0.54, cryptography 50.0.1, rfc8785 0.1.4, pytest 9.1.1.
Native Dogwood is the existing pinned `.tools/dogwood` binary (`dogwood 1.0.0`).
Commands used `UV_CACHE_DIR=/private/tmp/hirz-uv-cache` and
`HIRZ_DOGWOOD="$PWD/.tools/dogwood"`. Live database and full-suite checks ran with
sandbox escalation for local database/socket access. Every integration test and
the smoke used its own disposable database; existing credentials and the local
household database were preserved.

### Checks and outputs

```text
uv run --locked pytest tests/unit/test_audit.py --no-cov
45 passed in 0.97s

uv run --locked pytest tests/integration/test_audit_database.py -m integration --no-cov -s
100 concurrent tasks; connection cap=20; 100 contiguous signed rows; snapshot=100; next snapshot=101
8 passed in 11.89s

uv run --locked ruff check .
All checks passed!
uv run --locked ruff format --check .
80 files already formatted
uv run --locked mypy hirz/ scripts/ alembic/
Success: no issues found in 39 source files

uv run --locked pytest
530 passed, 32 deselected in 61.21s (0:01:01)
Required test coverage of 80% reached. Total coverage: 86.39%

uv run --locked pytest -m integration --no-cov
32 passed, 530 deselected in 27.09s
```

The final full runs include the follow-up assertions that offline CLI verification
never calls configuration/database helpers, that the snapshot transaction reports
`read_only=on` and `repeatable read`, and that encoding failures retain a valid
failure sequence. The service-free coverage figure deliberately excludes live
PostgreSQL execution; the separate integration suite exercises that path.

The concurrency gate launches 100 distinct real pipeline proposals behind a start
event through a pool capped at 20 connections, using native Dogwood and the existing
graph/pointer transaction locks. All returned audit IDs are unique and map to the
correct action and serialized `Decision.audit_id`; sequences are exactly 1–100.
The verifier checks every envelope hash/signature and final pointer. A further
proposal commits after the verifier captures its snapshot/pointer and before its
row scan. That scan still verifies 100 rows and selects rows 20–40 (21 rows); the
next snapshot verifies 101. This is a contiguity test, not a throughput benchmark
or a claim of 100 simultaneously connected database writers.

Adversarial checks cover payload/metadata mutations, rehashing without a valid
signature, wrong household/key, malformed keys/signatures/encodings/types, unknown
versions/fields, duplicate JSON keys, missing/duplicated/reordered rows, backwards
timestamps, genesis/hash/pointer corruption, out-of-range selection and corruption
outside the requested export interval. File tests verify mode `0600`, preservation
of existing files, symlink refusal, and removal after an injected partial-write
failure. CLI tests verify exit statuses and withholding private upstream/payload
details. Existing empty households and zero pointers pass as empty; unknown homes
and missing nonempty-chain pointers fail.

### Runnable CLI smoke

```text
uv run --locked python scripts/smoke_pipeline.py --audit
evaluate=ASK_CONSTITUTION audit=None
propose=ASK_CONSTITUTION; vote=APPROVED
redeem=EXECUTE; boundary=dogwood-local; reserved=0.25
replay=DENY_APPROVAL_USED; committed_grants=1; device_operations=0
stored_seed=unvalidated; source=twin; public_authentication=not_implemented
audit_smoke=PASS; whole_export=valid; range=2:3; changed_row=rejected; device_operations=0
```

The harness ran actual CLI argument parsing/dispatch with only its database
connection factory redirected to the disposable database. It then ran independent
installed `hirz` processes from a temporary directory without `.env` for offline
verification. The full stdout contained these JSON result fields:

| Operation | Status | Checked range/count | Additional result |
|---|---|---|---|
| Database verification | `valid` | 1–5 / 5 | `.env` public key derivation |
| Whole export | `valid` | 1–5 / 5 | 5 exported; explicit public-key PEM |
| Range export `2:3` | `valid` | 1–5 / 5 | 2 exported; endpoints 2–3 |
| Offline whole file, trusted PEM | `valid` | 1–5 / 5 | no `.env` or database |
| Offline range, trusted fingerprint | `valid` | 2–3 / 2 | no `.env` or database |
| Same range after payload mutation | `invalid` | none / 0 | `failure_seq: 2`, `reason: Envelope hash mismatch`; exit 1 |

Every output included `not anchored: local mode` and the completeness, truncation,
erasure and re-signing limitations. Temporary exports and the smoke database were
removed; nothing executed on a device. The original pipeline smoke behavior also
passed before its new audit extension ran.

### Failures encountered and limits

The first unit collection failed because an argparse generic annotation was
evaluated at runtime (`TypeError: type '_SubParsersAction' is not subscriptable`);
postponed annotations fixed it. The first concurrency test had already verified
100 rows, then failed when its snapshot hook tried assigning an instance method
(`AttributeError: 'AsyncConnection' object attribute 'stream' is read-only`);
patching the class in the test fixed that. An indentation error introduced while
editing this hook was caught by Ruff and fixed before rerunning. These were our
implementation/test mistakes, not third-party defects. The friction log was
reviewed; no new qualifying friction entry was earned.

The audit threat-model row earns **Partial** only. Signatures/link checks do not
detect a valid tail-and-pointer rollback, complete erasure, or history re-signed
with the worker's key. Selected exports prove only included rows and internal
links, not omitted history or freshness. The unsigned wrapper cannot attest
completeness. An empty result proves no historical absence. Anchors and
`--anchors` remain item 38b; public endpoints/authentication, policy activation,
physical execution and AWS enforcement remain pending. Item 11 owns `hirz decide`.
No commit, push, deployment or new GitHub Actions run was performed or claimed.

## Item 11 — 2026-09-18

### Implementation and acceptance evidence

Implemented the approved stored-policy preview CLI, shared constitution text
loader and nine initial-decision acceptance cases. This entry distinguishes
successful disposable-database verification from the blocked invocation on the
existing development database. The command contract lives in
[development procedures](./development.md#decision-preview-item-11) and
[architecture §3.5](../ARCHITECTURE.md#35-local-decision-preview-item-11).

Environment: macOS ARM64, Python 3.12.13, pytest 9.1.1, existing local PostgreSQL,
and the pinned native Dogwood binary at `.tools/dogwood`. Commands used
`UV_CACHE_DIR=/private/tmp/hirz-uv-cache` and, for native checks,
`HIRZ_DOGWOOD="$PWD/.tools/dogwood"`. Local socket/database tests used sandbox
escalation. No new dependency, migration, container, AWS resource or remote CI
run was needed.

| Command | Observed result |
|---|---|
| `uv run --locked pytest tests/unit/test_decide.py --no-cov` | 27 passed in 0.69 s |
| `uv run --locked pytest` | **557 passed, 47 deselected in 64.94 s; coverage 86.24%**, above the 80% gate |
| `uv run --locked pytest -m integration --no-cov` | **47 passed, 557 deselected in 37.11 s**, including all 15 new CLI integration checks |
| `uv run --locked ruff check .` | All checks passed |
| `uv run --locked ruff format --check .` | 83 files already formatted |
| `uv run --locked mypy hirz/ scripts/ alembic/` | Success: no issues found in 40 source files |

The focused native run printed these nine actual CLI results (each through
`hirz.cli.main`, substituting only disposable connection and test-key configuration):

```text
daytime_hvac: EXECUTE; audit=null; approval=null; database=unchanged
sleeping_hvac: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
teen_unlock: DENY_CONSTITUTION; audit=null; approval=null; database=unchanged
unexpected_v7: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
unexpected_v8: DENY_CONSTITUTION; audit=null; approval=null; database=unchanged
expected_arrival: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
stranger_in_window: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
suspicious_request: VERIFY; audit=null; approval=null; database=unchanged
budget_exceeded: DENY_BUDGET; audit=null; approval=null; database=unchanged
```

The fixtures used complete synthetic observations with explicit twin labels and
an unambiguous owner temperature baseline. The teen had an actual stored demo
account link. v8 was seeded unactivated in its isolated database. The budget
fixture first committed an actual internal $9.60 grant with a signed audit row,
then previewed $0.80 against the $10 cap; the preview reserved zero. No device
operation occurred. Database fingerprints include all application tables, their
history tables, approvals/votes/actions, audit rows/pointers, constitution versions
and the materialized household context. The grant setup precedes the fingerprint;
each subsequent preview leaves it unchanged.

Additional checks exercised the parents' linked account, unknown accounts,
requester confirmation, pause/resume without mutation, native boundary denial and
malformed responses, missing and conflicting facts, wrong household/future
evidence, damaged hashes, wrong policy name/version, invalid/duplicate policy
YAML, missing native engine, and malformed CLI input/evidence. Error outputs did
not echo private sentinel inputs. Default decision generation, hashing and all
pipeline semantics use existing code; no test substituted a Decision.

### Existing development database invocation

Ran the actual installed CLI from the checkout with its existing `.env`:

```sh
uv run --locked hirz decide \
  --household 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --as malik --surface alexa --action finance.transfer_money \
  --adapter household --entity 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --params '{}'
```

Exit **1**, empty stdout, stderr:

```text
Migrations are missing, inconsistent, or behind; run uv run alembic upgrade head from the checkout root.
```

Read-only follow-up inspection found revision `0002_household_graph`, no pipeline
tables, two households, zero audit rows, and two stored policies. In-memory parsing
found **0 valid / 2 invalid** stored policies under the current schema. No policy
contents or secrets were printed. Applying the existing schema migration alone
would not repair those policies. The approved scope preserves them and defers
activation; no development database migration, reset, reseed or policy rewrite
was performed. A successful Decision from that existing database remains
unverified; the nine-case acceptance evidence above is from fresh disposable
fixtures, not those preserved rows.

### Failures corrected and limits

Initial collection caught `TypeError: type '_SubParsersAction' is not subscriptable`;
postponed annotations fixed the new CLI module. The first focused database run
passed the nine examples, then a separate confirmation test returned `DENY_RISK`
because its fixture omitted evidence of guest absence; supplying occupancy
completeness correctly exposed `ASK_REQUESTER_CONFIRMATION`. The next run passed
14 checks, then a fixture assumed the parents' seed had an HVAC zone and raised
`IndexError: list index out of range`; the parents' governance check now uses its
actual seed without fabricated HVAC assets. The final full integration suite
passed all 47 checks. These were our implementation/fixture errors, not upstream
defects. Existing sandbox cache/socket friction was reviewed and recorded as a
repeat in the friction log.

The author explicitly chose to keep item 11 **partial** on 2026-09-18, pending a
working invocation on the preserved development database. Passing disposable
acceptance checks does not close that outstanding local verification.

No public authentication, activation, physical execution, historical replay,
passkey verification, remote boundary, or new threat-model protection is claimed.
No commit, push, deployment or new GitHub Actions run was performed.

Final documentation checks: `git diff --check` passed; `.venv/bin/hirz decide
--help` exited 0 and listed the approved required/optional flags. Ruff and mypy
were rerun after the edits with the same passing summaries above. Updated Commands
and Current phase guidance matches in both instruction files (70-word current
phase); their pre-existing file-specific heading/introduction differences remain.

### Development database reset and Phase 1 review — 2026-09-18

The author authorized resetting the development schema after confirming there was
no audit history. The original `.env` and signing key were retained. Commands ran
from the `phase-1` checkout on macOS ARM64 with Python 3.12.13, the existing local
PostgreSQL and Home Assistant services, and the pinned native Dogwood binary.
Local database/service calls used sandbox escalation. Shell setup:

```sh
export UV_CACHE_DIR=/private/tmp/hirz-uv-cache
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
```

Before any destructive command, the read-only inspection was:

```sh
uv run python - <<'PY'
import asyncio
from pathlib import Path
import sqlalchemy as sa
from hirz.db import connect_database
from hirz.local import read_env

async def main():
    async with connect_database(read_env(Path(".env"))) as connection:
        await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        count = (await connection.execute(sa.text("SELECT count(*) FROM audit_log"))).scalar_one()
        print(f"audit_log rows: {count}")
        if count != 0:
            raise SystemExit("STOP: audit history exists")
        print("migration: " + (await connection.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one())

asyncio.run(main())
PY
```

Exit 0; actual output:

```text
audit_log rows: 0
migration: 0002_household_graph
```

```sh
uv run alembic downgrade base
```

Exit 0; no stdout or stderr.

```sh
uv run alembic upgrade head
```

Exit 0; no stdout or stderr.

```sh
uv run alembic check
```

Exit 0; actual output:

```text
No new upgrade operations detected.
```

```sh
uv run hirz seed constitutions/quinn-home.yaml constitutions/quinn-parents.yaml
```

Exit 0; actual output:

```text
[{"household": "quinn-home", "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0", "status": "loaded", "constitution_version": 7, "policy_status": "unvalidated", "members": 3, "assets": 9}, {"household": "quinn-parents", "household_id": "bf745178-9146-5952-a310-f1d7e563977b", "status": "loaded", "constitution_version": 1, "policy_status": "unvalidated", "members": 2, "assets": 2}]
```

```sh
uv run hirz seed constitutions/quinn-home.yaml constitutions/quinn-parents.yaml
```

Exit 0; actual output:

```text
[{"household": "quinn-home", "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0", "status": "unchanged", "constitution_version": 7, "policy_status": "unvalidated", "members": 3, "assets": 9}, {"household": "quinn-parents", "household_id": "bf745178-9146-5952-a310-f1d7e563977b", "status": "unchanged", "constitution_version": 1, "policy_status": "unvalidated", "members": 2, "assets": 2}]
```

```sh
uv run hirz doctor
```

Exit 0; actual output:

```text
PASS Postgres: authenticated SELECT 1.
PASS HA: real API, demo devices (simulated); required entities present.
PASS Signing key: P-256 private key signs and verifies an in-memory probe.
PASS Migrations: database matches the sole Alembic head; graph tables and household_context present.
```

```sh
uv run hirz decide \
  --household 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --as malik --surface alexa --action finance.transfer_money \
  --adapter household --entity 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --params '{}'
```

Exit 0; actual output:

```text
Hypothetical dry run; policy v7 is unactivated (stored: unvalidated); clock=2026-09-19T03:50:59.840674+00:00; current graph, not historical replay. No authentication, approval, execution grant, device operation, or audit write. Supplied evidence is simulated; boundary is dogwood-local.
{"decision":"deny","event_type":"DENY_CONSTITUTION","action_id":"act_daa4feb1c8d74333b54910c2bfdbb9d1","risk":null,"constitution":{"version":7,"rule":"finance.transfer_money","mode":"never","conditions_met":false},"boundary":{"engine":"dogwood-local","result":"not_evaluated","reason":"terminal before boundary","context_hash":null,"roles":{}},"approval":null,"budget":null,"explain":{"facts":[],"considered":[],"rejected":[]},"audit_id":null}
```

The repeated seed was a no-op for both households. Doctor passed all four checks;
the actual development CLI returned `DENY_CONSTITUTION` with null approval and
audit IDs. Policy status remains unvalidated/unactivated. The command's UTC clock
was 2026-09-19; the local session date was 2026-09-18 (America/Los_Angeles).
This run closes the earlier preserved-database prerequisite limitation; it does
not claim policy activation, physical execution, AWS enforcement, or a new CI run.

Post-reset read-only inspection (exit 0) confirmed the CLI left the audit empty
and the removed optional graph field needs no JSONB cleanup:

```sh
uv run python - <<'PY'
import asyncio
from pathlib import Path
import sqlalchemy as sa
from hirz.db import connect_database
from hirz.local import read_env

async def main():
    async with connect_database(read_env(Path(".env"))) as connection:
        await connection.execute(sa.text("SET TRANSACTION READ ONLY"))
        for label, query in (
            ("audit_log rows", "SELECT count(*) FROM audit_log"),
            ("household budgets attributes", "SELECT count(*) FROM households WHERE attributes ? 'budgets'"),
            ("migration", "SELECT version_num FROM alembic_version"),
        ):
            print(f"{label}: {(await connection.execute(sa.text(query))).scalar_one()}")

asyncio.run(main())
PY
```

```text
audit_log rows: 0
household budgets attributes: 0
migration: 0003_pipeline
```

`rg -n '\bbudgets\b' hirz/graph tests constitutions alembic` returned no matches
after removal (exit 1). The former optional field lived in generic JSONB
attributes, not a dedicated column; the architecture entity row was updated too.
Constitution-rule budget enforcement is unchanged.

The author approved operation-only logging in `Dogwood.run`, which has no
household UUID; pipeline records contain the operation and UUID. All four
`log.exception` calls use `exc_info=False`, preventing upstream exception text
from leaking SQL parameters, action data, or subprocess output. The one new unit
test injects the same private sentinel into action params and the raised connection
exception and checks both formatted logs and the record itself.

Verification commands used the same temporary uv cache; both full suites and
integration runs explicitly unset `HIRZ_DOGWOOD` to exercise checkout discovery.
Missing binaries still fail; no skip or dependency was added.

| Command | Actual output / result (exit 0) |
|---|---|
| `unset HIRZ_DOGWOOD; uv run pytest` (before the new regression test) | `557 passed, 47 deselected in 56.44s`; `Required test coverage of 80% reached. Total coverage: 85.54%` |
| `uv run ruff format hirz/pipeline/service.py tests/unit/test_pipeline.py tests/conftest.py` | `1 file reformatted, 2 files left unchanged` |
| `uv run pytest tests/unit/test_pipeline.py -k connection_failure --no-cov` | `1 passed, 25 deselected in 0.78s` |
| `uv run ruff check . && uv run ruff format --check . && uv run mypy hirz/ scripts/ alembic/` (final code) | `All checks passed!`; `84 files already formatted`; `Success: no issues found in 40 source files` |
| `unset HIRZ_DOGWOOD; uv run pytest -m integration --no-cov` (started before the final Dogwood log was added) | `47 passed, 558 deselected in 32.53s`; rerun below against final code |
| `unset HIRZ_DOGWOOD; uv run pytest` (final code) | `558 passed, 47 deselected in 58.92s`; `Required test coverage of 80% reached. Total coverage: 86.51%` |
| `unset HIRZ_DOGWOOD; uv run pytest -m integration --no-cov` (final code) | `47 passed, 558 deselected in 33.48s` |

All final checks passed. The integration suite includes the nine CLI acceptance
examples. The test count increased by one for the requested logging regression.
The requested `--no-cod` was treated as `--no-cov`, matching the documented
integration invocation; `o>/.tools/dogwood` was treated as the checkout's
`.tools/dogwood`.

Final review confirmed the verification log retains its entire prior contents,
`CLAUDE.md` and `AGENTS.md` carry identical updated guidance, and the diff stays
within the six review tasks. A temporary extra blank line caught by
`git diff --check` was removed. Third-party tooling worked as expected: the known
sandbox cache/socket requirements were handled using the temporary cache and
sandbox escalation without a new failure or workaround, so no new friction entry
was earned. No requested local verification remains outstanding. Phase 2 was not
started; no push, deployment, remote CI run, activation migration, or doctor
clock check was performed.


## Item 12 — Complete (2026-09-19)

Implemented the individually author-approved plan: all nine typed async adapter
protocols, household-bound registry/configuration/capabilities/source validation,
separate observation domains, graph-derived facts, and explicit fill-only CLI
preview inputs. Decisions and rejected alternatives are in
[ADR-006](./adr/ADR-006-twin-first-adapters.md#item-12-contract-amendment--2026-09-19-author-approved);
interfaces and behavior are specified in `ARCHITECTURE.md` §5.11, and procedures
have one home in [development](./development.md#adapter-contracts-and-graph-facts-item-12).

Environment: macOS ARM64, Python 3.12.13, uv 0.12.15; existing locked dependencies
and checkout `.tools/dogwood` discovered by `tests/conftest.py`. Commands used
`UV_CACHE_DIR=/private/tmp/hirz-uv-cache`; `uv run` used `--locked --offline`.
No dependency/lockfile changes were required. Native Dogwood was required, not
skipped. PostgreSQL integration tests created and dropped only uniquely named
`hirz_test_*` databases using the existing fixture and credentials without printing
them. The full suite's disposable socket tests and PostgreSQL connections ran
with authorized sandbox escalation.

### Failures and corrections during implementation

- The first uv checks hit the known default-cache sandbox permission failure;
  the temporary cache resolved it. The first integration attempt produced 36
  connection setup errors under the sandbox. The first escalated retry stopped
  after one setup error: PostgreSQL refused the connection on port 5432.
  Compose `ps --all` showed no services. `docker compose -f compose.dev.yml up -d
  --no-deps --wait postgres` started only PostgreSQL and reported it healthy,
  preserving the named volume. The friction log records the exact errors and
  repeat-environment classification; these are not new upstream defects.
- The initial focused suite returned `19 failed, 74 passed in 2.16s`: fixtures
  still used aggregate supplemental facts, untagged observation writes and the
  old evidence-list format. Converting them to explicit domain observations and
  graph facts produced `93 passed in 1.40s`.
- The new migration test initially returned `1 failed, 1 passed in 1.29s` because
  it tried to call the current seed loader while deliberately on an old schema.
  The fixture now seeds on current head, downgrades before writing any tagged
  observations, and constructs its synthetic legacy rows. The corrected run
  returned `2 passed in 1.45s`.
- Review found that a sleep reading without Boolean presence must remain unknown.
  Extraction now considers only explicitly present members for positive sleeping
  facts. A regression case covers this, and native generated conformance also
  includes absent members without sleep/zone fields. The exact documented light
  preview was added as a CLI integration case.

Before those final additions, the broad suites returned `625 passed, 50 deselected
in 54.56s` at `86.22%` coverage and `50 passed, 625 deselected in 31.80s` for
PostgreSQL. Final results below supersede those intermediate counts.

### Final commands and outputs

| Command (temporary uv cache; sandbox escalation where described) | Actual output / result, exit 0 |
|---|---|
| `uv run --locked --offline pytest -q --tb=short` | `626 passed, 51 deselected in 57.12s`; `Required test coverage of 80% reached. Total coverage: 86.24%` (3307 statements, 455 missed) |
| `uv run --locked --offline pytest -m integration --no-cov -q --tb=short` | `51 passed, 626 deselected in 32.43s` |
| `uv run --locked --offline pytest tests/unit/test_adapters.py -k mixed_boot --no-cov -s -q` | `1 passed, 20 deselected in 0.62s`; all four labeled observations below |
| `uv run --locked --offline pytest tests/integration/test_decide_database.py tests/integration/test_adapter_database.py -m integration --no-cov -s -q --tb=short` | `19 passed in 10.55s`; printed CLI and migration evidence below |
| `uv run --locked --offline ruff check .` | `All checks passed!` |
| `uv run --locked --offline mypy hirz/ scripts/ alembic/` | `Success: no issues found in 54 source files` |
| `uv run --locked --offline ruff format --check .` | `101 files already formatted`; repeated after the evidence/closeout records |
| `uv build --offline` | Built `dist/hirz-0.0.0.tar.gz` and `dist/hirz-0.0.0-py3-none-any.whl` |
| `git diff --check` | No whitespace errors |

### Registry and CLI proof

The mixed boot test instantiated selected adapters, resolved per-entity overrides,
checked lifecycle/capabilities and validated/stamped each observation. Every
implementation was explicitly synthetic; no physical device or real API was used:

```text
TEST IMPLEMENTATION: devices:ha; light.living_room; source=real
TEST IMPLEMENTATION: devices:ha; hvac.living_room; source=real API, demo devices
TEST IMPLEMENTATION: devices:twin; hvac.guest_room; source=twin
TEST IMPLEMENTATION: ev:twin; ev; source=twin
```

Actual argparse dispatch, stored unactivated policy loading, native Dogwood and
pipeline evaluation produced these outputs with database fingerprints unchanged:

```text
daytime_hvac: EXECUTE; audit=null; approval=null; database=unchanged
sleeping_hvac: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
teen_unlock: DENY_CONSTITUTION; audit=null; approval=null; database=unchanged
unexpected_v7: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
unexpected_v8: DENY_CONSTITUTION; audit=null; approval=null; database=unchanged
expected_arrival: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
stranger_in_window: ASK_CONSTITUTION; audit=null; approval=null; database=unchanged
suspicious_request: VERIFY; audit=null; approval=null; database=unchanged
budget_exceeded: DENY_BUDGET; audit=null; approval=null; database=unchanged
overlay missing: DENY_RISK; database=unchanged
overlay fill: EXECUTE; database=unchanged
overlay conflict: DENY_CONSTITUTION; database=unchanged
overlay foreign: DENY_CONSTITUTION; database=unchanged
overlay future: DENY_CONSTITUTION; database=unchanged
documented light preview: EXECUTE; dogwood-local=allow; audit=null; approval=null; database=unchanged
```

The last case parses the exact JSON and shell example from `docs/development.md`,
substituting only its temporary evidence path, disposable database and test key.
`EXECUTE` is a hypothetical result here; it creates no execution grant or operation.

Migration verification printed:

```text
Migration: legacy current/history preserved; presence+wearable coexist; duplicate rejected; tagged current/history downgrade refused
```

The tests also verified SQLAlchemy metadata agreement, uniqueness after migration,
immutable observation subject/domain, household/domain validation, the energy
context projection, and rollback with only legacy data. Explicit read-only
inspection of the existing development database after testing returned:

```text
Development migration: 0003_pipeline
```

No migration or reset was applied to that database, no seed file was changed, and
no signing key was generated or replaced. PostgreSQL was started for verification
and left running. The new revision must be applied explicitly before an operator
uses item 12 against the development database.

### Limits

Item 12 proves contracts, configuration, fact derivation and hypothetical previews.
It implements no production adapter, twin physics, runtime observation ingestion,
activation, device operation, automatic fallback, hosted-demo eligibility or AWS
enforcement. No threat-model row changed. No remote CI run, workflow change, commit,
push or deployment was performed; the existing placeholder CI jobs remain placeholders.

Final record review: an initial strict instruction-file comparison reported
`AssertionError` because the existing AGENTS introduction names its CLAUDE mirror.
The diff confirmed that only the pre-existing heading/introduction differ; the
substantive guidance, including both item 12 edits, matches. The post-record Ruff
check passed and the final format check reported `101 files already formatted`.

## Item 13 — Complete (2026-09-19)

Implemented the author-approved in-memory twin models, forward-only `SimClock`,
independent seeded inputs, canonical observations, and eight polling/read adapters.
The decisions and rejected alternatives are in
[ADR-006](./adr/ADR-006-twin-first-adapters.md#item-13-models-and-read-adapters-amendment--2026-09-19-author-approved).
Exact model and interface behavior has one home in
[the twin spec](./twin-and-scenarios.md#211-item-13-in-memory-contract);
the runnable procedure is in [development](./development.md#twin-models-and-read-adapters-item-13).

Environment: Darwin arm64, Python 3.12.13, uv 0.12.15 (Homebrew 2026-09-15).
Python checks used `UV_CACHE_DIR=/private/tmp/hirz-uv-cache` and locked offline
project runs. Native Dogwood was discovered by the existing `tests/conftest.py`
and ran inside the full suite; it was not skipped. PostgreSQL was already healthy.
Its tests created and dropped only the existing fixture's uniquely named disposable
databases. The development database was neither migrated nor reset; item 12's
manual upgrade remains outstanding. Source manifests and lockfiles are unchanged.

### Failures found and corrected

- Strict mypy initially reported 13 errors (optional UUID lookup, heterogeneous
  model collections, class-variable annotations, and a reused key variable), then
  10 after the smoke was added (including Decimal constructor annotations), then
  one heterogeneous storage-loop annotation. All were corrected. Ruff also caught
  a misplaced test import and an incorrectly renamed local variable.
- The first focused run was `1 failed, 21 passed in 1.15s`. It exposed a real
  configuration-precedence bug: copying a model materialized omitted defaults as
  explicit overrides, masking graph calibration. The shared validated-copy helper
  now preserves explicit-field provenance. The regression then passed with
  `22 passed in 1.04s`; later expanded focused runs passed 25 and finally 27 tests.
- The initial full run reported `3 failed, 645 passed, 51 deselected in 53.73s`,
  coverage 89.11%: two existing localhost WebSocket tests could not bind under
  the sandbox, and the same configuration-precedence regression failed. Authorized
  escalation resolved the socket restriction; no production socket behavior changed.
- Intermediate full runs passed `651 passed, 52 deselected in 56.68s` at 89.09%
  and `652 passed, 52 deselected in 56.44s` at 88.60%. Review added explicit range
  checks so a longer weather input cannot extend the world's query horizon, and
  a regression preventing backward direct reads within an uncommitted minute.
  The final run below supersedes these intermediate snapshots.
- The new PostgreSQL round-trip test first reported `1 failed, 51 passed,
  651 deselected in 31.98s`: the test passed context-only `staleness_seconds`
  metadata into canonical `Observation`. Excluding that metadata fixed the test;
  the implementation required no database change.
- The first isolated wheel install could not find existing `rfc8785==0.1.4` in the
  temporary offline cache. Authorized online installation into a disposable venv
  supplied the existing dependency; subsequent wheel reinstalls worked offline.
  A helper edit also initially used a relative repository path while its command
  was running from `/private/tmp`; rerunning from the checkout corrected that
  `FileNotFoundError`, without changing any external state. Repeat environment
  friction and exact tool errors are recorded in the friction log.

### Final verification

Commands from the checkout root (the full/socket and PostgreSQL runs used authorized
sandbox escalation; all project `uv run` commands had the temporary cache above):

```sh
uv run --locked --offline pytest tests/unit/test_twin.py --no-cov -q
uv run --locked --offline pytest -q
uv run --locked --offline pytest -m integration --no-cov -q
uv run --locked --offline ruff check .
uv run --locked --offline mypy hirz/ scripts/ alembic/
uv run --locked --offline python scripts/smoke_twin.py
uv build
```

Results:

```text
27 passed in 1.45s
653 passed, 52 deselected in 57.02s
Required test coverage of 80% reached. Total coverage: 89.11%
52 passed, 652 deselected in 31.69s
All checks passed!
Success: no issues found in 70 source files
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The PostgreSQL run preceded the final world-only backward-read regression, which
has no persistence path; all 52 database checks passed, including camera/shade/
doorbell-motion JSONB round trips. The final full Python run includes the new
regression and native Dogwood conformance. Property-based battery verification
uses 80 generated examples within one pytest test.

The actual user-facing smoke command printed:

```text
SIMULATED: standalone physics and read adapters; no actions or persistence
PASS ev_minutes_34_to_50=105.75793184
PASS warm_45_min_f=4.00089188
PASS drift_60_min_f=0.98378575
PASS ev_energy_residual_kwh=0.00000000
PASS quinn-home: adapters=8 observations=15 source=twin writes=unavailable balance_residual_kwh=0.0000000000
PASS quinn-parents: adapters=8 observations=6 source=twin writes=unavailable balance_residual_kwh=0.0000000000
```

The suite also verifies analytical EV taper and driving, battery reserve/full
saturation and 90% round-trip return, thermal coupling conservation/COP/duty,
all three appliance profiles, PV geometry/cloud/night behavior, tariff clipping
and reproducible spikes, schedule jitter/DST/overrides/recovery, exact device
latency/failure, unavailable write methods/subscriptions, private contact/call/
visitor data, lifecycle, household isolation and provenance. Equivalent minute-
partitioned and irregular polling histories produce identical state/model events.

A fresh `/private/tmp/hirz-item13-wheel` venv installed the built wheel and its
existing dependencies. After final code changes the wheel was rebuilt and
reinstalled with:

```sh
uv pip install --offline --reinstall-package hirz --python /private/tmp/hirz-item13-wheel/bin/python dist/hirz-0.0.0-py3-none-any.whl
```

From `/private/tmp`, the installed interpreter asserted that `hirz.__file__`
resolved inside that venv, imported all eight twin adapter packages, exercised
`SimClock` and the EV transition, and read the packaged SVG with
`importlib.resources`. It printed:

```text
PASS isolated installed wheel: eight adapters, clock, physics, bundled SVG; checkout not imported
```

Ruff format verification is run last after this evidence and the closeout records:
`uv run --locked --offline ruff format --check .` (118 Python files). Instruction
parity and `git diff --check` are also checked. No remote CI run, push, commit,
real feed, device action, scenario runner, persistence/ingestion, activation,
execution or new threat-model protection is claimed. The frontend is unchanged;
no frontend checks were added or represented as part of this item.

Post-closeout checks: Ruff reported `All checks passed!`, mypy reported
`Success: no issues found in 70 source files`, and the final format check reported
`118 files already formatted`. The first instruction-parity assertion excluded
only the headings and therefore caught the pre-existing AGENTS-only introductory
mirror sentence. Normalizing that existing introduction and the two headings
confirms identical guidance; no unrelated introductory text was changed.


## Item 14 — Complete (2026-09-20)

Implemented the approved credential-free energy plan: canonical pinned tariff,
`energy:real`, explicit series coverage/provenance, recorded feeds, and read-only
smoke. Interface/time semantics and exclusions are in [ADR-006's item 14
amendment](./adr/ADR-006-twin-first-adapters.md#item-14-credential-free-energy-amendment--2026-09-20-author-approved)
and its linked specifications.

Environment: macOS ARM64, Python 3.12.13, uv 0.12.15, pytest 9.1.1; installed project
dependencies and existing native `.tools/dogwood`. Commands ran from the checkout
unless stated otherwise. `UV_CACHE_DIR=/private/tmp/hirz-uv-cache` was used for local
uv checks; the wheel install used the existing user cache with network disabled.
Sandbox escalation was used for public feed/PDF downloads, the full suite's existing
local socket test, and disposable wheel-environment installation. No AWS credentials
or deployment, database migration/ingestion, remote CI dispatch, or device action.

**Primary-source cross-check and recordings.** Retained `tariffs/sources/` PDFs
were downloaded directly from the exact URLs in the canonical tariff file. Read
supply page 1 with `pdftotext -layout`; reviewed delivery pages 1–2 with both text
extraction and rendered `pdftoppm` images. Checked all eight supply values, four
Time-of-Day distribution values, standard distribution, period hours, seasons,
validity and resultant-charge vintage against those documents. The YAML records
per-row dates/URLs, exclusions and the delivery header ambiguity; hashes are tested
against the retained bytes. Normal tests compare reviewed values without requiring
PDF tools. `tests/fixtures/energy/manifest.json` retains acquisition UTC timestamps,
request URLs and hashes for day-ahead, five-minute, spring/fall DST, weather and
source-page recordings. The evidence does not treat Date.UTC chart labels as a
public timestamp guarantee or the June delivery vintage as a live rate check.

**Validation commands and actual results.**

```text
uv run pytest
777 passed, 52 deselected in 61.87s (0:01:01)
Required test coverage of 80% reached. Total coverage: 89.87%

uv run ruff check .
All checks passed!

uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 74 source files

uv run ruff format --check .
123 files already formatted

uv build
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The 52 deselected tests are the explicitly selected PostgreSQL integration suite;
there were no database changes and it was not run for this item. The final format
check is repeated after these completion records. The initial focused run passed
161 tests; an intermediate full run passed 775 at 89.86%. Final review replaced a
test-only factory shortcut with actual real/twin factory composition: the twin
factory permits only the deliberate in-memory rate-plan difference while preserving
all other household checks. The final suite verifies actual battery/solar reads
and stamping through those bindings, plus safe overflow/deep-malformed-response
handling. Early Ruff checks reported formatting/style issues and mypy reported the
computed-field property decorator diagnostic; formatting and the documented targeted
mypy suppression resolved them before the final checks. No failing checks remain.

The energy tests cover reviewed tariff values, every period boundary, both seasons,
calendar billing approximation, effective limits, Decimal sums and negatives,
export absence, unsupported profiles, UTC clipping, both DST transitions, inclusive
daily endpoints and duplicates, explicit null/empty/future gaps, malformed and
JavaScript-shaped input, unit/coordinate/horizon errors, unaligned weather reads,
missing hours, timeout and partial multi-day failure, lifecycle, household isolation,
actual mixed bindings, unavailable writes and twin series provenance. Existing twin
physics and native policy conformance tests passed unchanged in the full suite.

**Default recorded smoke.** Ran `uv run python scripts/smoke_energy.py`, exit 0:

```text
RECORDED public feed fixtures (no network)
comed_time_of_day/day_ahead: real (published ComEd rate)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=24 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=None
  import_cents_per_kwh: first=6.174 min=6.174 max=28.446 export=None
comed_time_of_day/realtime: real (published ComEd rate)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=288 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=None
  import_cents_per_kwh: first=6.174 min=6.174 max=28.446 export=None
weather: real (Open-Meteo forecast)
  requested=[2026-09-20T00:17:00+00:00, 2026-09-20T03:00:00+00:00) count=3 gaps=0 covered_hours=2.716667 complete=True
comed_hourly/day_ahead: real (ComEd day-ahead forecast; publication time unknown)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=24 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=2026-09-20 00:00:00+00:00
  import_cents_per_kwh: first=9.133 min=8.133 max=9.433 export=None
comed_hourly/realtime: real (ComEd realtime quoted supply; not finalized hourly billing)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=287 gaps=1 covered_hours=23.916667 complete=False
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=2026-09-20 00:00:00+00:00
  import_cents_per_kwh: first=8.233 min=7.633 max=20.033 export=None
  gap=[2026-08-02T02:35:00+00:00, 2026-08-02T02:40:00+00:00) missing or unpublished supply price
```

Recorded smoke retrieval fields use the injected replay clock; actual capture
metadata lives in the fixture manifest. It does not claim a live read.

**Live smoke.** Ran
`uv run python scripts/smoke_energy.py --live --history-month 2026-08`, exit 0.
The first successful read was repeated after correcting the smoke's retrieval
clock to use actual time and adding an assertion that weather returned data.
August's requested Chicago calendar month has 744 hours / 8,928 nominal five-minute
intervals. The actual final read returned 8,848 intervals, 80 missing intervals in
44 contiguous gaps, 737 hours 20 minutes covered, and 6 hours 40 minutes missing.
No interpolation or gap-free claim. Returned scheduling prices retain negatives;
they are not finalized bills, export valuations, planner savings or proof of
historical forecast publication. Exact final output:

```text
LIVE public feeds
comed_time_of_day/day_ahead: real (published ComEd rate)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=24 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=None
  import_cents_per_kwh: first=6.174 min=6.174 max=28.446 export=None
comed_time_of_day/realtime: real (published ComEd rate)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=288 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=None
  import_cents_per_kwh: first=6.174 min=6.174 max=28.446 export=None
weather: real (Open-Meteo forecast)
  requested=[2026-09-20T15:17:00+00:00, 2026-09-20T18:00:00+00:00) count=3 gaps=0 covered_hours=2.716667 complete=True
comed_hourly/day_ahead: real (ComEd day-ahead forecast; publication time unknown)
  requested=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) count=24 gaps=0 covered_hours=24.000000 complete=True
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-08-02T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=2026-09-20 15:24:52.439951+00:00
  import_cents_per_kwh: first=9.133 min=8.133 max=9.433 export=None
comed_hourly/realtime: real (ComEd realtime quoted supply; not finalized hourly billing)
  requested=[2026-08-01T05:00:00+00:00, 2026-09-01T05:00:00+00:00) count=8848 gaps=44 covered_hours=737.333333 complete=False
  observed_bounds=[2026-08-01T05:00:00+00:00, 2026-09-01T05:00:00+00:00) basis=supply_plus_distribution tariff=comed-2026-06-verified-2026-09-20 retrieved_at=2026-09-20 15:24:57.318026+00:00
  import_cents_per_kwh: first=8.233 min=-3.767 max=146.933 export=None
  gap=[2026-08-02T02:35:00+00:00, 2026-08-02T02:40:00+00:00) missing or unpublished supply price
  gap=[2026-08-03T09:20:00+00:00, 2026-08-03T09:25:00+00:00) missing or unpublished supply price
  gap=[2026-08-04T09:05:00+00:00, 2026-08-04T09:10:00+00:00) missing or unpublished supply price
  gap=[2026-08-04T19:15:00+00:00, 2026-08-04T19:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-05T08:55:00+00:00, 2026-08-05T09:00:00+00:00) missing or unpublished supply price
  gap=[2026-08-05T17:15:00+00:00, 2026-08-05T17:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-06T10:15:00+00:00, 2026-08-06T10:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-06T18:40:00+00:00, 2026-08-06T18:50:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T14:25:00+00:00, 2026-08-07T14:35:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T14:40:00+00:00, 2026-08-07T14:45:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T15:00:00+00:00, 2026-08-07T15:05:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T15:10:00+00:00, 2026-08-07T15:15:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T18:50:00+00:00, 2026-08-07T19:00:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T20:20:00+00:00, 2026-08-07T20:35:00+00:00) missing or unpublished supply price
  gap=[2026-08-07T23:40:00+00:00, 2026-08-07T23:45:00+00:00) missing or unpublished supply price
  gap=[2026-08-08T05:05:00+00:00, 2026-08-08T05:10:00+00:00) missing or unpublished supply price
  gap=[2026-08-08T13:25:00+00:00, 2026-08-08T13:30:00+00:00) missing or unpublished supply price
  gap=[2026-08-09T06:10:00+00:00, 2026-08-09T06:15:00+00:00) missing or unpublished supply price
  gap=[2026-08-09T20:50:00+00:00, 2026-08-09T20:55:00+00:00) missing or unpublished supply price
  gap=[2026-08-10T08:25:00+00:00, 2026-08-10T08:30:00+00:00) missing or unpublished supply price
  gap=[2026-08-10T17:10:00+00:00, 2026-08-10T17:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-11T11:00:00+00:00, 2026-08-11T11:05:00+00:00) missing or unpublished supply price
  gap=[2026-08-12T05:40:00+00:00, 2026-08-12T05:45:00+00:00) missing or unpublished supply price
  gap=[2026-08-14T02:15:00+00:00, 2026-08-14T03:00:00+00:00) missing or unpublished supply price
  gap=[2026-08-17T04:50:00+00:00, 2026-08-17T04:55:00+00:00) missing or unpublished supply price
  gap=[2026-08-17T17:00:00+00:00, 2026-08-17T17:05:00+00:00) missing or unpublished supply price
  gap=[2026-08-18T19:05:00+00:00, 2026-08-18T19:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-19T04:00:00+00:00, 2026-08-19T04:15:00+00:00) missing or unpublished supply price
  gap=[2026-08-19T06:15:00+00:00, 2026-08-19T06:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-25T12:30:00+00:00, 2026-08-25T12:35:00+00:00) missing or unpublished supply price
  gap=[2026-08-25T16:05:00+00:00, 2026-08-25T16:10:00+00:00) missing or unpublished supply price
  gap=[2026-08-25T16:15:00+00:00, 2026-08-25T16:20:00+00:00) missing or unpublished supply price
  gap=[2026-08-25T20:55:00+00:00, 2026-08-25T21:10:00+00:00) missing or unpublished supply price
  gap=[2026-08-26T14:55:00+00:00, 2026-08-26T15:00:00+00:00) missing or unpublished supply price
  gap=[2026-08-26T19:25:00+00:00, 2026-08-26T20:25:00+00:00) missing or unpublished supply price
  gap=[2026-08-27T19:05:00+00:00, 2026-08-27T19:10:00+00:00) missing or unpublished supply price
  gap=[2026-08-27T19:15:00+00:00, 2026-08-27T19:25:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T14:30:00+00:00, 2026-08-28T14:35:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T17:20:00+00:00, 2026-08-28T17:25:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T17:30:00+00:00, 2026-08-28T17:40:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T17:50:00+00:00, 2026-08-28T18:00:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T18:40:00+00:00, 2026-08-28T18:45:00+00:00) missing or unpublished supply price
  gap=[2026-08-28T19:25:00+00:00, 2026-08-28T19:40:00+00:00) missing or unpublished supply price
  gap=[2026-08-30T16:45:00+00:00, 2026-08-30T16:50:00+00:00) missing or unpublished supply price
```

**Twin user-path regression.** Ran `uv run python scripts/smoke_twin.py`, exit 0:

```text
SIMULATED: standalone physics and read adapters; no actions or persistence
PASS ev_minutes_34_to_50=105.75793184
PASS warm_45_min_f=4.00089188
PASS drift_60_min_f=0.98378575
PASS ev_energy_residual_kwh=0.00000000
PASS quinn-home: adapters=8 observations=15 source=twin writes=unavailable balance_residual_kwh=0.0000000000
PASS quinn-parents: adapters=8 observations=6 source=twin writes=unavailable balance_residual_kwh=0.0000000000
```

**Installed wheel outside the checkout.** Created `/private/tmp/hirz-item14-wheel`
with `uv venv --python /Users/bashaarjavaid/Projects/Hirz/.venv/bin/python`, then
installed the wheel and 29 dependencies from the existing cache with
`uv pip install --python /private/tmp/hirz-item14-wheel/bin/python --offline
/Users/bashaarjavaid/Projects/Hirz/dist/hirz-0.0.0-py3-none-any.whl`. After the final
code changes, rebuilt and reinstalled with `--reinstall-package hirz`.
From `/private/tmp`, ran the reproducible repository smoke with isolated imports
and an explicitly supplied tariff file:

```bash
/private/tmp/hirz-item14-wheel/bin/python -I /Users/bashaarjavaid/Projects/Hirz/scripts/smoke_energy.py --tariff-file /Users/bashaarjavaid/Projects/Hirz/tariffs/comed-time-of-day.yaml
/private/tmp/hirz-item14-wheel/bin/python -I -c 'import hirz; print(hirz.__file__); assert "site-packages" in hirz.__file__'
```

Both exited 0; recorded counts/gaps matched the default smoke above. Import resolved
to `/private/tmp/hirz-item14-wheel/lib/python3.12/site-packages/hirz/__init__.py`,
not the checkout. An additional temporary async wheel probe independently asserted
24 day-ahead slots per plan, 288 static / 287 recorded realtime slots and two weather
samples per plan, with all adapters closed:

```text
PASS installed wheel comed_time_of_day: day_ahead=24 realtime=288 weather=2
PASS installed wheel comed_hourly: day_ahead=24 realtime=287 weather=2
```

Third-party friction was checked and recorded as entries 10–12 plus the existing
sandbox-restriction follow-up in [the friction log](./friction-log.md#item-14-energy-research--2026-09-20).
No blocked acceptance checks. Item 15 remains next; the development database stays
unchanged on `0003_pipeline`, item 12's upgrade remains manual, and no new threat-model
protection or remote CI result is claimed.

## Item 15 — partial (2026-09-20)

**Physical gate not run:** no physical energy-monitoring plug or reviewed local
mapping was supplied. The real plug's pipeline write, measured state/power,
physical-absence scenario fallback and ordinary unavailability remain owed. No
hardware was selected or purchased. No new threat-model protection, AWS/Link
execution, remote CI result or development-database migration is claimed.

Implementation decisions and the author-approved switch from ecobee to heatpump
are in [ADR-006](./adr/ADR-006-twin-first-adapters.md#item-15-local-ha-amendment--2026-09-20-author-approved).
Reproducible operator commands are in [development](./development.md#home-assistant-adapter-item-15).
Environment: macOS arm64, Python 3.12.13, uv 0.12.15, existing local Postgres,
pinned Home Assistant 2026.9.2 demo integration and native `.tools/dogwood`.
Started the existing HA service with
`docker compose -f compose.dev.yml up -d homeassistant` after authorized sandbox
escalation. The private `.env` and its original signing key were reused without
printing or changing them.

**Recorded and adversarial checks.** `uv run python scripts/smoke_ha.py` exited 0:

```text
recorded=PASS; reads=3; subscription=acknowledged,filtered; read_only_write=refused; network_requests=0
```

The adapter/fallback targeted suite grew to 62 passing cases before the final
cleanup-redaction case. It exercises authentication and subscription refusal,
connect/auth timeout handling, acknowledgment and bound-entity filtering, shutdown,
W/kW and Celsius conversions, oldest timestamps, missing power with known on/off,
malformed/nonfinite/scoped data, secret redaction, switch services, read-only
refusals, unsupported parameters/modes/steps, contradictory effects, precise raw
verification, direct-unavailable verification and scenario-only provenance checks.
A twin/canonical read method is never consulted to verify a real write.

`uv run pytest -m integration tests/integration/test_ha_database.py --no-cov --tb=short -q`:

```text
8 passed in 4.75s
```

Those tests use native Dogwood with recorded HA transport and disposable PostgreSQL.
Eight simultaneous independently connected adapters produce exactly one POST and
seven claim refusals; reconstructing the adapter/Pipeline on another connection
produces no additional request. Proposal-only/forged Decisions, changed proposals,
hash mismatches, stale grants, scheduled actions, foreign households and changed
bindings are refused. Audit/signature/database/commit failures prevent dispatch;
a timeout after the attempt is committed cannot be retried. Empty migrations
round-trip; downgrade refuses both a claimed attempt and its audit evidence with
the claim pointer removed. The successful chain is exactly
`EXECUTE → EXECUTION_ATTEMPTED → EXECUTED → VERIFIED`.

Full PostgreSQL regressions, `uv run pytest -m integration --no-cov -q`, exited 0:

```text
60 passed, 815 deselected in 41.97s
```

Log: `/private/tmp/hirz-item15-postgres.log`. The full service-free suite after
adding switch/shutdown/direct-unavailability checks, `uv run pytest -q`, exited 0:

```text
Required test coverage of 80% reached. Total coverage: 89.53%
818 passed, 60 deselected in 59.46s
```

Log: `/private/tmp/hirz-item15-unit-final2.log`. A later cleanup-redaction regression
and its final run are appended below.

**Live user path.** Ran
`uv run python scripts/smoke_ha.py --live-demo --audit-output /private/tmp/hirz-item15-demo-audit-final.json`,
exit 0. The command required subscription observations to match the requested
values, separately verified service effects through REST and restored both devices:

```text
read=climate.heatpump; source=real API, demo devices; target_f=68.0; on=None; power_kw=None
read=climate.ecobee; source=real API, demo devices; target_f=None; on=None; power_kw=None
read=light.bed_light; source=real API, demo devices; target_f=None; on=False; power_kw=None
write=climate.heatpump; grant=1; boundary=dogwood-local; verified=True
subscription=climate.heatpump; source=real API, demo devices; power_kw=None; direct_power_kw=None
write=light.bed_light; grant=5; boundary=dogwood-local; verified=True
subscription=light.bed_light; source=real API, demo devices; power_kw=None; direct_power_kw=None
write=light.bed_light; grant=9; boundary=dogwood-local; verified=True
restoration=light.bed_light; verified=True
write=climate.heatpump; grant=13; boundary=dogwood-local; verified=True
restoration=climate.heatpump; verified=True
audit=valid; rows=16; export=/private/tmp/hirz-item15-demo-audit-final.json; offline=valid
live_demo=PASS; ecobee=read_only
disposable_database=dropped; development_database=unchanged
```

The tested heatpump target was 72 °F; restoration returned it to 68 °F and the
light to off. All four device writes had independent native grants, attempt claims
and outcome rows. The private full audit export was retained and verified offline
against the original key fingerprint before dropping the disposable database.
An earlier successful run also retained `/private/tmp/hirz-item15-demo-audit-2.json`.

**Failures encountered and corrected.** Initial database tests used an incorrect
binding lookup key (`GraphError: An exact entity key is required.`), then omitted
required synthetic room metadata (`DENY_RISK`). The first claim implementation
queried relational adapter/entity columns rather than the existing JSONB attributes;
fail-closed `PipelineError: Execution claim refused; no dispatch authorized` prevented
all requests until corrected. Downgrade tests were adjusted for the existing Alembic
safe-error wrapper (`Migration failed; check Postgres, .env, and the migration state.
Credentials and upstream details withheld.`). Two unit assertions initially expected
the generic malformed-payload error, while nonfinite power correctly returned
`Invalid Home Assistant numeric value.`; the assertions were corrected. Strict mypy
required converting SQLAlchemy's RowMapping to a dict for the existing audit verifier.

The first live bootstrap used a timestamp taken after its graph transaction began
and failed with `GraphError: Future observations are not accepted.` before any action.
It retained `hirz_ha_smoke_8a73a89e7bfe4c62905344a2072600db`; a separate read-only
verification found zero audit rows, exported/verified the empty audit at
`/private/tmp/hirz-item15-aborted-audit.json`, then dropped only that disposable
database. A read of the development database still returned `0003_pipeline`.
Subsequent smokes used one captured bootstrap timestamp and passed.

**Static checks and package.** Ruff lint passed and strict mypy reported
`Success: no issues found in 77 source files`. `uv build` produced the sdist and
wheel. Created `/private/tmp/hirz-item15-wheel` with `uv venv`, installed the wheel
and runtime dependencies using `uv pip install --python ...`, then rebuilt and
reinstalled the final cleanup change using `--reinstall-package hirz`. Ran:

```bash
/private/tmp/hirz-item15-wheel/bin/python -I /Users/bashaarjavaid/Projects/Hirz/scripts/smoke_ha.py
/private/tmp/hirz-item15-wheel/bin/python -I -c 'import hirz, websockets; print(hirz.__file__); print(websockets.__version__); assert "site-packages" in hirz.__file__'
```

The recorded smoke passed; the import resolved to
`/private/tmp/hirz-item15-wheel/lib/python3.12/site-packages/hirz/__init__.py` and
websockets reported `17.1`, proving it is a runtime dependency. The final format
check is recorded below after documentation updates. Third-party friction was
reviewed and recorded as entry 13 and an existing sandbox-restriction follow-up;
no upstream HA error or outage was invented.

**Final cleanup regression run (2026-09-20).** After adding redacted shutdown failure
handling that still closes the REST client, reran `uv run pytest -q`, exit 0:

```text
Required test coverage of 80% reached. Total coverage: 89.54%
819 passed, 60 deselected in 59.95s
```

Final full-suite log: `/private/tmp/hirz-item15-unit-final3.log`. Ruff lint and strict
mypy also passed after that change; final rebuilt/installed-wheel smoke passed.

**Documentation and final format gate.** Updated the architecture/ADR, operator
procedure, partial roadmap entry, changelog and mirrored instructions. After those
records were written, `ruff check .`, strict mypy and `git diff --check` passed;
`ruff format --check .` reported `128 files already formatted`. No physical gate
was marked complete and `THREAT_MODEL.md` was left unchanged.

## Item 16 — Complete (2026-09-20)

**Scope of completion:** the author explicitly approved the item 16 observation
stage as its completion gate. This is not full demo verification: real scripted
tool execution, persisted `scenario_runs`, graph ingestion, authenticated policy
activation, planner/Protect/executor/Link integration and their assertions remain
owed. Every future assertion is individually deferred, including `never` checks
that would otherwise pass vacuously. No device action, new threat-model protection,
remote CI result or development-database migration is claimed. Item 15's physical
plug and physical-absence gates remain pending.

Approved decisions and rejected alternatives are in
[ADR-006](./adr/ADR-006-twin-first-adapters.md#item-16-observation-stage-scenarios--2026-09-20-author-approved).
Input/report semantics live in [the scenario spec](./twin-and-scenarios.md#31-item-16-runnable-contract);
repeatable procedures live in [development](./development.md#scenario-runner-item-16).

### Environment and implementation failures

macOS 15.7.3 arm64, Python 3.12.13, uv 0.12.15, existing locked `.venv`, native
`.tools/dogwood`, existing local PostgreSQL. Source checks used
`UV_CACHE_DIR=/tmp/hirz-uv-cache` and `uv run --locked --no-sync` to reuse the
installed environment; no manifest or lockfile changed. Scenarios used
`HIRZ_DOGWOOD="$PWD/.tools/dogwood"`. There was no model, public API or device call.

The first evening run traversed all 20 events but failed its household tariff
check: the assertion matched a battery sharing the household/domain instead of
the household-subject observation. Fixed subject matching and retained a
regression assertion. Its first output was 15 passed checks and 1 failed.
The parents' first run passed all 9 checks. Initial mypy checks caught typed
member-account access, a keyword-only registry argument and transition literal
typing. The first CLI import also caught an evaluated private argparse generic;
postponed annotation evaluation fixed it.

The first focused suite reported `2 failed, 32 passed`: tests incorrectly tried
`python -m hirz` instead of the installed CLI entrypoint and rejected the harmless
word `presented_number` inside a deferred expectation. Corrected those tests to
exercise the actual CLI and forbid actual private values. The suite then passed
34 checks, and expanded malformed-input coverage brought it to 42.

The first full suite in the sandbox reported:

```text
2 failed, 851 passed, 60 deselected in 74.66s (0:01:14)
Required test coverage of 80% reached. Total coverage: 89.39%
```

Both failures were existing loopback WebSocket tests denied socket access. The
first PostgreSQL attempt similarly stopped before any test ran (`853 deselected,
1 error in 1.58s`). Authorized reruns passed. The temporary-cache offline wheel
install initially lacked an existing dependency; authorized access to the existing
cache completed the install offline. Exact environment errors and workarounds are
recorded once in [the friction follow-up](./friction-log.md#item-16-environment-follow-up--2026-09-20),
not as new upstream defects.

### Final tests and user-facing runs

```text
uv run --locked --no-sync pytest tests/unit/test_scenario.py --no-cov -q
42 passed in 9.35s

uv run --locked --no-sync pytest -q
861 passed, 60 deselected in 74.33s (0:01:14)
Required test coverage of 80% reached. Total coverage: 89.44%

uv run --locked --no-sync pytest -m integration --no-cov -q --maxfail=1 --tb=short
60 passed, 853 deselected in 41.85s

uv run --no-sync mypy hirz/ scripts/ alembic/
Success: no issues found in 79 source files

uv run --no-sync ruff check .
All checks passed!

uv build --offline
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The integration run preceded the eight added malformed-input unit cases; its
853 deselections are therefore expected. All databases it created were uniquely
named disposable test databases. No scenario command connects to PostgreSQL.

The actual CLI commands run were:

```sh
uv run --locked --no-sync hirz scenario run scenarios/demo-evening.yaml --headless --assert --output /tmp/hirz-item16-evening-final.json
uv run --locked --no-sync hirz scenario run scenarios/parents-scam-check.yaml --headless --assert --output /tmp/hirz-item16-parents-final.json
uv run --locked --no-sync hirz scenario step scenarios/demo-evening.yaml --to '18:40' --assert
uv run --locked --no-sync hirz scenario run scenarios/parents-scam-check.yaml --speed 60 --assert
```

Each exited 0. JSON stdout and separate stderr traces were retained in temporary
files; reports are reproducible artifacts, not permanent audit exports.

| Run | Status | Events processed | Active checks | Deferred future checks | Exported observations |
|---|---|---:|---|---:|---:|
| Evening | `item16_observations_passed` | 20 | 16 passed | 25 | 288 |
| Parents | `item16_observations_passed` | 5 | 9 passed | 9 | 42 |
| Evening step to 18:40 | `stopped` | 6 | 4 passed, 12 not reached | 25 | 112 |
| Parents paced at 60× | `item16_observations_passed` | 5 | 9 passed | 9 | 42 |

The paced parents report equals the headless report as parsed JSON. The injected
pacer test also matches and sums to 25 seconds of waits. The step stops before
both 18:40 events, and the full run preserves their press-before-voice order.
Repeated runs produce identical parsed reports. All observations have `source:
twin`. Mom remains absent at the expected-window doorbell press, arrives only at
her explicit 19:10 event and sleeps at 23:05. The EV remains at 0.34, the doors
remain locked and the lamp/dishwasher remain off because no commands execute.

Recorded version 7→8 passes native validation and produces the existing
unexpected-visitor “ask on phone → never” preview plus “Expected arrival: still
asks on your phone.” It is labeled recorded/simulated and `authenticated: false`.
Wrong owner, missing proposal, wrong base/increment, invalid security channels and
missing Dogwood fail while retaining version 7. Redaction, invalid references,
invalid times, omitted initial fields, unsupported/unmarked events, nonfinite
speed, duplicate YAML keys, assertion failure, CLI aliases/usage errors, existing
output files and dangling output symlinks are checked.

### Installed wheel and CI definition

Created `/tmp/hirz-item16-wheel-venv`, installed the built wheel and its existing
dependencies offline, left the checkout for `/tmp`, and ran both absolute-path
scenario commands with that environment's `hirz` executable. Verified the imported
package came from `/private/tmp/hirz-item16-wheel-venv/lib/python3.12/site-packages/`.

```text
PASS installed wheel evening: events=20 checks=16 deferred=25
PASS installed wheel parents: events=5 checks=9 deferred=9
```

The scenario CI placeholder was replaced with pinned setup, native Dogwood and
both headless assertion commands; its summary names the deferred expectations.
The YAML parsed and retains all 11 job IDs. No push, workflow dispatch, upload or
remote CI run occurred. The existing browser/conformance/latency/release limits
are not earned by this change.

Input SHA-256 values from the final reports:

```text
evening scenario: 6d51904f5495f7fdb1c52ce1468ea31ab0d350d8818f92e7fb588e15d9112047
evening household: 20a685ffdeea6597af266790bb732e644644abc4131f9dd2a2c91bff73d2489a
recorded patch: d538f15ad44f8cc79e0a6590e48888364166a72b0871c3f3f5de1a2d848745e3
parents scenario: 42a8d0dcc3a7b43e4588c6ab1a372f8b9fa60122b75dc855d00ae943ef2f4a38
parents household: 4d8dfd01a3b876714141fcb90f5d1a36dc45937fa9c3384016b727ba3592a8a3
```

### Final record consistency and formatting

After the evidence, roadmap, changelog and mirrored Current phase updates,
`ruff format --check .` reported `131 files already formatted`; Ruff lint, strict
mypy (79 source files) and `git diff --check` passed. A whole-file mirror check
initially flagged the pre-existing AGENTS-specific introductory sentence; comparison
of all substantive guidance confirms it matches CLAUDE.md exactly. That unrelated
introductory difference was preserved.

A documentation-only complexity-ceiling comment was added to the runner's small
linear timeline scans. Rebuilt/reinstalled the final wheel and reran both scenarios
outside the checkout: evening `item16_observations_passed` with 16 checks, parents
with 9. No behavioral code changed after the 861-test full run. Final formatting
was repeated after this appended evidence, as required.

## Phase 2 cleanup batch 1

Verified on 2026-09-20 on `phase-2`, macOS arm64, Python 3.12.13 and native
`.tools/dogwood`. The changelog entry is dated 2026-09-21 as requested. This is a
correction to items 12–16, not a new roadmap item.

### Regression proof

Before implementation, ran:

```sh
uv run pytest tests/unit/test_scenario.py tests/unit/test_adapters.py -k 'registry_reads_use_simulated_time or absent_member_cannot_sleep or (start_failure and factory)' --no-cov
```

```text
4 failed, 63 deselected in 0.95s
```

The demo-evening world was at 2026-10-13 while wall time was 2026-09-20. Its real
`twin` light adapter, reached through a `devices:ha` stub raising
`AdapterUnavailable`, failed with `AdapterError: Invalid scenario fallback
provenance.` The direct twin registry read also failed future-time validation.
Absent Mom's sleep event did not raise, and the startup-failure test found no
`Registry.start`/`RuntimeError` log.

Added the Registry clock argument and supplied `world.clock` in the mixed test
and twin registry helper; both get-state timestamp validations now use it. HA's
own future `last_updated` check still uses wall time. The absent-member sleep
check raises before applying an event; the test verifies unchanged world state
and the permitted no-op wake. Redacted exceptions log only static operation names
and `type(exc).__name__`, using the pipeline's existing logging pattern. The
startup test checks that `RuntimeError` is logged and `PRIVATE` is absent.

The same focused command after the corrections returned:

```text
4 passed, 63 deselected in 0.79s
```

### Development migrations

Ran the explicitly authorized `uv run alembic upgrade head`: exit 0, no stdout or
stderr. The two pending revisions are `0004_observation_domains` and
`0005_execution_attempt`. Then ran these commands in order:

```text
$ uv run alembic check
No new upgrade operations detected.

$ uv run hirz doctor
PASS Postgres: authenticated SELECT 1.
PASS HA: real API, demo devices (simulated); required entities present.
PASS Signing key: P-256 private key signs and verifies an in-memory probe.
PASS Migrations: database matches the sole Alembic head; graph tables and household_context present.

$ uv run alembic current
0005_execution_attempt (head)
```

All exited 0. Current phase now states that revision identically in AGENTS.md and
CLAUDE.md. No reset, reseed, credential replacement or physical device action was
performed. ADR-006 has a dated source-label amendment, and the scenario sketches
are explicitly targets for items 17, 22 and 35; §3.1 remains executable syntax.

### Required verification sequence

Ran the following in the requested order; all commands exited 0:

```text
$ uv run pytest
TOTAL                                      5448    571    90%
Required test coverage of 80% reached. Total coverage: 89.52%
================ 864 passed, 60 deselected in 67.99s (0:01:07) =================

$ uv run pytest -m integration --no-cov
===================== 60 passed, 864 deselected in 34.29s ======================

$ uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 79 source files

$ uv run ruff check .
All checks passed!

$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
```

The scenario CLIs emitted JSON reports; parsed summaries, with explicit assertions
on status, count and every check's passing status:

```text
demo-evening: item16_observations_passed; 16 checks passed; 25 deferred
parents-scam-check: item16_observations_passed; 9 checks passed; 9 deferred
```

Local full outputs are `/private/tmp/hirz-cleanup-batch1-pytest.log`,
`/private/tmp/hirz-cleanup-batch1-integration.log`, and
`/private/tmp/hirz-cleanup-batch1-{evening,parents}.{json,log}`. Integration tests
used disposable databases. No remote CI run was requested or claimed. The native
Dogwood checks ran locally; later-phase scenario assertions remain deferred.

Reviewed all 20 redacted re-raises across Registry, HA and real energy: each logs
the operation and exception class before raising. Registry cleanup also logs the
class, and the scenario runner logs it before returning its redacted failed
report. No exception message, traceback, input payload, URL or credential is
included by these logs.

The existing uv cache sandbox restriction recurred; the exact error and successful
escalated retry are recorded in [the friction log](./friction-log.md). No new
upstream defect was encountered. `git diff --check` passed, and the Current phase
text matches between AGENTS.md and CLAUDE.md. ROADMAP.md, THREAT_MODEL.md and
hirz/twin/physics.py are unchanged; item 15 remains Partial. No Phase 3 behavior,
composition root or real-adapter scenario loading was added.

Final formatting, after the evidence and changelog entries were written:

```text
$ uv run ruff format --check .
131 files already formatted
```

Exit 0; repeated after appending this result so formatting remains the final check.

## Doorbell press bound to approval

Author decision dated **2026-09-21**; local verification ran **2026-09-20** on
`phase-2`, macOS, Python 3.12.13, the existing locked uv environment, local
PostgreSQL and the repository's native `.tools/dogwood`. This corrects items 9
and 12 under [ADR-006](./adr/ADR-006-twin-first-adapters.md#doorbell-press-bound-to-approval--2026-09-21-author-approved).

### Regression and coverage

The new PostgreSQL case uses the existing suites and a uniquely named disposable
database. At T = `2026-10-13T19:04:00-05:00`, the press falls inside Mom's stored
arrival window. Under v8 it proposes at T+10 seconds, records the synthetic
passkey-verified phone vote at T+60, refreshes telemetry while preserving
`last_press_at`, and redeems at T+120. It checks the three-field JSONB binding,
native Dogwood authorization, one vote, and the stored audit context hash.
`EXECUTE` here is an internal durable grant, not a physical unlock.

Before implementation, the focused command returned `DENY_CONSTITUTION` instead
of `EXECUTE`. After correcting fixture freshness/versioning, the **final test**
was also run against both original pipeline files from HEAD, with the working
changes saved and restored in a `finally` block. It reproduced the same failure:

```text
$ uv run pytest tests/integration/test_pipeline_database.py -m integration --no-cov -k doorbell --tb=short
E   assert <EventType.DENY_CONSTITUTION: 'DENY_CONSTITUTION'> == 'EXECUTE'
======================= 1 failed, 13 deselected in 1.52s =======================
```

The focused corrected-code PostgreSQL run passed:

```text
$ uv run pytest tests/integration/test_pipeline_database.py -m integration --no-cov -k doorbell
======================= 1 passed, 13 deselected in 1.59s =======================
```

Seven service-free proposal/vote/redemption cases cover expected-v8 success, a
second press at T+90 refusing both a vote and redemption without inserting another
vote or approval, unexpected-v8 refusal without approval creation, unexpected-v7
success with the Boolean still true, legacy bindings under both versions, and
expiry after 30 minutes winning even over a newer press. Votes are checked at both
T+60 and T+61. Schedule removal after ASK does not change the bound classification.
Read-only `evaluate()` still creates no approval and uses the live press window;
the existing `hirz decide` integration cases run in the full PostgreSQL suite.
Four fact tests additionally verify live sleeping, occupancy, offline status and
observation age; the existing 0/60/60.001/86400-second window tests remain intact.

The service-free boundary test checks `f_context_unexpected_visitor`, equality of
`boundary.context_hash` to the full facts digest, and that removing the bound press
changes that digest. `boundary_check()` already hashes `Facts.policy.values` and
passes those facts to `boundary_input()`. The bound press is now in those values;
the existing compiler projects its derived Boolean. No graph snapshot schema,
hash algorithm, boundary schema, database column or migration changed.

```text
$ uv run pytest tests/unit/test_pipeline.py tests/unit/test_adapter_facts.py --no-cov --tb=short
============================== 70 passed in 1.18s ==============================
```

Intermediate development runs exposed a `TypeError` from serializing frozen
policy facts (fixed by the existing `wire()` helper), stale fixture observations
returning `DENY_RISK` (retained as correct behavior), a fixture insertion violating
`observations_asset_unique` (changed to versioned updates), and six test failures
from mutating a frozen `ContextSnapshot` (changed to `model_copy`). None remains
in the final verification. The initial uv cache permission failure and successful
escalated retry are recorded in [the friction log](./friction-log.md); no upstream
defect, dependency change or remote CI run is claimed.

### Required verification sequence

The following ran in the requested order:

```text
$ uv run pytest
TOTAL                                      5476    475    91%
Required test coverage of 80% reached. Total coverage: 91.33%
================ 875 passed, 61 deselected in 72.28s (0:01:12) =================

$ uv run pytest -m integration --no-cov
===================== 61 passed, 875 deselected in 37.40s ======================

$ uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 79 source files

$ uv run ruff check .
All checks passed!

$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
```

Both scenario JSON reports were parsed, asserting their status, exact check count,
all passing checks and deferred counts:

```text
demo-evening: item16_observations_passed; 16 checks passed; 25 deferred
parents-scam-check: item16_observations_passed; 9 checks passed; 9 deferred
```

These commands all exited 0. Full local outputs are
`/private/tmp/hirz-doorbell-{before,pytest,integration}.log` and
`/private/tmp/hirz-doorbell-{evening,parents}.json`. The scenario assertions remain
item 16 observations; no executor, scheduler, Phase 3 item, or physical device
operation was added. ROADMAP.md and the instruction files are unchanged. The
unexpected-visitor threat row remains Planned; no threat-model status was raised.

The final requested test command then exited 0:

```text
$ uv run pytest tests/cedar_conformance --no-cov
============================= 40 passed in 44.66s ==============================
```

Full output: `/private/tmp/hirz-doorbell-cedar.log`. All 40 native conformance tests
ran locally; AWS enforcement remains outside this correction.

Final formatting, after the records were written:

```text
$ uv run ruff format --check .
131 files already formatted
```

Exit 0. `git diff --check` also passed. The format check is repeated after appending
this result so it remains the last verification command before the single commit.

## Scenario weather from archived observations

### Author decision 2026-09-21; local verification 2026-09-20

Correction to item 16 on `phase-2`, based on `7e69ff3`. The machine clock at
retrieval was 2026-09-20 UTC; decision/document dates retain the author's requested
2026-09-21 date. Python 3.12 and the existing `.tools/dogwood` were used. No loader,
DSL, adapter implementation, assertion, dependency or Phase 3 code changed.
Item 17 remains incomplete.

The [raw archive response](../scenarios/fixtures/weather-chicago-2025-10-13.json)
was fetched once successfully with Python's `urllib.request.urlopen` and saved
byte-for-byte (1,639 bytes). Its request URL, actual retrieval timestamp and SHA-256
are recorded in the [manifest](../scenarios/fixtures/manifest.json), using the
energy-fixture manifest shape, and above each scenario's inline samples.
The request uses the seed's declared coordinates, 41.88, -87.63, both calendar
dates, hourly temperature/cloud cover, Fahrenheit and America/Chicago. The raw
response retains both full days; the inline data select 2025-10-13 17:00 through
2025-10-14 07:00 inclusive. The returned coordinates are the archive grid cell,
41.862915, -87.64877; they do not replace the requested seed coordinates.
Open-Meteo describes this [archive as reanalysis using observations and models](https://open-meteo.com/en/docs/historical-weather-api#data-sources),
so the comments identify that provenance without claiming a station measurement.

All 15 selected hours contain both values; no null hours were omitted. Their
Chicago local dates shift forward one calendar year. The evening uses the 17:00
values at its exact 17:30 start, followed by 18:00 through 07:00. Its weather
coverage ends at 08:00 because the existing Weather validator requires the last
sample strictly before `weather.end`; the scenario clock still ends at 07:00.
The parents scenario uses only the same response's 17:00 values for its 25 minutes.
The 07:00 sample is retained at the evening endpoint, with no extra hour of
physics advancement. There is no runtime fixture lookup or network request.

The initial sandbox request failed before contacting the API:
`urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`.
The authorized network escalation then succeeded. The API behaved as documented;
no friction-log entry was earned under this task's archive-only criterion.

### Scenario commands and final snapshots

Before editing, ran the evening command with stdout saved to
`/private/tmp/hirz-weather-before.json`; after editing, ran both commands below.
All three exited 0. Scenario commands used `UV_CACHE_DIR=/private/tmp/hirz-uv-cache`
to keep cache access inside the sandbox's writable roots.

```text
$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
demo-evening: item16_observations_passed; 16 checks passed; 25 deferred

$ HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
parents-scam-check: item16_observations_passed; 9 checks passed; 9 deferred
```

After reports: `/private/tmp/hirz-weather-evening.json` and
`/private/tmp/hirz-weather-parents.json`. A one-off `uv run python` check recomputed
the raw SHA-256, checked response units/timezone, compared every inline timestamp,
temperature and cloud-cover value with the selected archive rows, and asserted
the exact pass/deferred counts and that every report observation retained `twin`.
It also started each scenario's `TwinEnergy` adapter and called `get_weather` over
the horizon: both returned `source: twin`, `source_label: twin (supplied weather)`.
The initial manual probe omitted `adapter.start()` and correctly raised
`AdapterUnavailable: Twin adapter is not started.`; rerunning with the existing
start/close lifecycle passed without any product code change.

Final-snapshot values at 2026-10-14 07:00 America/Chicago, mapped to seed slugs
using `LoadedScenario.ref("assets", slug)`:

| Zone | Before `temp_f` | After `temp_f` |
|---|---:|---:|
| `hvac.living_room` | 57.8514 | 65.8044 |
| `hvac.guest_room` | 58.6986 | 66.6517 |

The archived overnight air is warmer than the old constant 40 °F, so the RC zones
cool less. HVAC remains off and no temperature assertion was added or changed.
These are simulated zone temperatures, not physical measurements or proof of
comfort enforcement. Full-demo execution and its deferred checks remain owed.

### Required checks

The full suite ran with sandbox escalation for the existing localhost-socket
tests and uv cache, with `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`; its full output is
`/private/tmp/hirz-weather-pytest.log`. The existing scenario tests also verified
repeatable reports. No new remote CI run or integration run is claimed.

```text
$ uv run pytest
TOTAL                                      5476    475    91%
Required test coverage of 80% reached. Total coverage: 91.33%
================ 875 passed, 61 deselected in 72.56s (0:01:12) =================

$ uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 79 source files

$ uv run ruff check .
All checks passed!
```

All exited 0. Mypy and Ruff used the same writable temporary uv cache.

Formatting after the evidence entry was written:

```text
$ uv run ruff format --check .
131 files already formatted
```

Exit 0; `git diff --check` also passed. Formatting is repeated after recording
this output so it remains the last verification command before committing.

## Item 17 — partial (2026-09-21)

**Not complete: the year-long acceptance gate failed.** All requested profile,
household and wear combinations were attempted, but fixed forecast-derived
controls could not continue within hard constraints against realized weather.
No constraints were relaxed, no physical states reset, and no savings were
claimed for invalid comparisons. The retained outputs and generated six-row
README table explicitly report coverage. Item 17 remains the current work item;
no threat-model row or later execution item was advanced.

### Implementation and experiment boundary

`hirz/planner/` implements a sparse MILP, the canonical proposed Plan and matching
Actions, timer/immediate/greedy schedules, strict pure-twin replay, comparison
validity, incumbent validation, timeout fallback and newest-first infeasibility
probes. The API is read-only, with no database/device mutation path. Consequential
choices and rejected alternatives are in
[ADR-005](./adr/ADR-005-deterministic-planner.md#read-only-planner-and-historical-experiment--2026-09-21).
The installed solver is SciPy 1.18.0 (HiGHS), with five seconds and 0.001 relative
gap. Workload settings and expanded physical parameters are retained in
[`workload.json`](../scripts/backtest-data/workload.json).

Public data were downloaded sequentially with explicit network authorization,
then replayed offline. The archive contains **751 checksummed responses**: 375
ComEd day-ahead daily responses, 375 five-minute daily responses, and one weather
archive response. Coverage includes the eight-day lookback and ending dates.
Parsed responses contain **8,987 observed billing-hour buckets, 8,661 complete
12-quote hours**, and **9,000 weather samples**. Missing complete hours are not
filled. Raw contents, source URLs, UTC retrieval timestamps and uncompressed
SHA-256 hashes are in [`raw/manifest.json`](../scripts/backtest-data/raw/manifest.json).
These are feed-based estimates and pinned-2026-tariff counterfactuals; production
tariff validity checks are unchanged. Day-ahead values never enter planning.

### Historical gate and independent reproduction

```text
.venv/bin/python scripts/backtest.py
18 profile/household/wear runs; requested 365 daily boundaries per run
Exit 1: incomplete coverage, stopped-run evidence retained
Retained replay elapsed_seconds: 25.921181208919734

.venv/bin/python scripts/backtest.py --verify
{"offline_reproduction_matches": true}
Exit 0: every retained non-timing result reproduced offline
```

The six primary comparison rows are generated in
[`readme-table.md`](../scripts/backtest-data/readme-table.md); full nightly data,
electricity and wear costs, losses, exports, selected forecast timestamps,
near-zero counts, negative-price durations, worst timer day, quantiles and
extrapolations are in [`results.json`](../scripts/backtest-data/results.json) and
[`daily.csv`](../scripts/backtest-data/daily.csv). The three wear settings are
$0, $0.01 and $0.02 per internal-throughput kWh. No historical figure uses live
forecast weather.

For both tariffs and all three wear settings, solar/battery MILP strategies stop
on **2025-09-01** with `Battery discharge to grid prohibited` during realized
replay. EV-only MILP strategies have **2/365 eligible days**, then stop on
**2025-09-03** with `Terminal comfort band missed` and `Hard comfort band missed`.
Other strategies continue independently until their own stopping condition;
states and failure-day forecast inputs, schedules and replay evidence are retained.
The zero-coverage solar/battery rows say unavailable. The EV-only results are
published with their 2/365 coverage and explicit extrapolation/missing-data bias,
not presented as annual performance. A feedback controller or robustness policy
was not silently introduced to rescue the results; that requires further design
and implementation before the year-long gate can pass.

### User-facing commands and timing

```text
.venv/bin/python scripts/smoke_planner.py
Exit 0: MILP proposal and greedy proposal both validated
solve_seconds: 0.030419542221352458 (< 2 seconds)
greedy_seconds: 0.02792016603052616 (< 50 ms; includes proposal construction)
cold_seconds: 0.659368374850601 (includes imports and first proposal)
```

Measurements are retained in [`smoke-planner.json`](../scripts/backtest-data/smoke-planner.json).
The separate `--live-weather` smoke used the existing RealEnergy forecast adapter:
**25 samples, complete coverage**, labeled live smoke only and excluded from the
study (`live-weather-smoke.json`). The live smoke was authorized after the network
sandbox restriction; no device credential or state change was involved.

All three scenario CLIs were rerun using native `.tools/dogwood`:

```text
hirz scenario run scenarios/demo-evening.yaml --headless --assert
item17_planning_and_observations_passed: 16 observation checks, 2 planning snapshots, 22 explicit deferrals
hirz scenario run scenarios/demo-evening-hourly.yaml --headless --assert
item17_planning_and_observations_passed: 16 observation checks, 2 planning snapshots, 22 explicit deferrals
hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
item16_observations_passed: 9 observation checks, 0 planning snapshots, 9 explicit deferrals
```

The two planning snapshots preserve Malik's linked account, with no future Dad
kitchen constraint. Forecast comparisons pass; observation-world devices remain
unchanged. Derived snapshot savings/peak expectations replace the three
provisional planning-only deferrals. At 17:33/17:35 respectively, retained ToD
savings are **$0.7579348122944097 / $0.7576057558520851**, and Hourly counterfactual
forecast savings are **$1.3655137437287528 / $1.2592157160035298**. Peak avoidance is
zero within the 0.000001 kWh validation tolerance (stored residuals are about
−5e−14 kWh); the former provisional minimum 5 kWh claim was not earned.
Reports: [`demo-evening.json`](../scripts/backtest-data/demo-evening.json),
[`demo-evening-hourly.json`](../scripts/backtest-data/demo-evening-hourly.json),
[`parents-scam-check.json`](../scripts/backtest-data/parents-scam-check.json).

### Tests, packaging and failures reported faithfully

Environment: CPython **3.12.13**, **macOS 15.7.3 arm64**, SciPy **1.18.0**, NumPy
**2.5.3**. Normal tests perform no downloads or year-long replay. Small cases cover
both profiles, all three household configurations, missing billing data with
state carry, DST, partial slots, persistence cutoff/ambiguity, future realized
weather/price independence, tiny hand-computed optima, conservation and export
limits, failed comparisons, infeasibility, fallback/incumbent validation,
canonical hashes, household isolation and linked-account provenance.

```text
.venv/bin/pytest -q --tb=short
908 passed, 61 deselected in 80.58s
Required test coverage of 80% reached. Total coverage: 91.78%

.venv/bin/pytest -m integration --no-cov -q
61 passed, 906 deselected in 40.39s

.venv/bin/pytest tests/unit/test_planner.py tests/unit/test_scenario.py --no-cov -q --tb=short
78 passed in 12.61s

.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 90 source files

git diff --check
(no errors)

uv build
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The final focused run followed limiting the Hourly scenario's archive reads to
its eight-day input window and regenerating all three scenario reports. The wheel
was installed in a separate `/private/tmp/hirz-item17-wheel` environment for an
out-of-repository forecast-plan and Action-hash smoke; its outcome is appended
below. Final format verification is run after this evidence/documentation edit.

Earlier attempts were not green: the sandbox suite reported two local-socket
permission failures and was interrupted; a stale scenario redaction/count
assertion failed after adding canonical provenance and removing provisional
deferrals, and was corrected; the first PostgreSQL attempt had **61 setup errors**
with `connection to server at "127.0.0.1", port 5432 failed: ... Connection refused`.
Starting the existing Compose PostgreSQL service (no development migration/reset)
allowed all disposable-database regressions to pass. A reproduction attempt
initially compared in-memory tuples with JSON lists; normalizing sequence types
fixed the verifier, and the next independent offline run matched exactly.
Sandbox/tool friction is recorded as follow-up to existing entries in
[`friction-log.md`](./friction-log.md). No new remote CI run was made.

Final packaging/format follow-up (same run, 2026-09-21):

```text
/private/tmp/hirz-item17-wheel/bin/python  # cwd=/private/tmp; retained forecast input
Installed wheel: validated forecast plan, canonical Action hashes, no database/device writes
/private/tmp/hirz-item17-wheel/lib/python3.12/site-packages/hirz/planner/service.py

.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 90 source files
.venv/bin/ruff format --check .
145 files already formatted
```

The final format check was run after the evidence, roadmap, changelog and
synchronized instruction-file edits. The historical coverage failure remains;
passing code checks and exact reproduction do not close item 17.

### Causal replay follow-up — 2026-09-21

The author approved fixing item 17's stopped historical runs within the existing
read-only boundary. The [ADR-005 amendment](./adr/ADR-005-deterministic-planner.md#causal-historical-replay-amendment--2026-09-21)
records the shared simulated controls and rejected alternatives. Economic planning
remains once daily; no executor, coordinator intake, endpoint, database table,
real-device write or new authority path was added. Physical parameters, hard
comfort bands, energy tolerances, tariff validity checks and forecast cutoffs are
preserved. The original partial run above remains historical evidence.

The first controller probes exposed cold-weather preparation failures on
2025-11-30 and 2026-01-25. Preparing for the declared occupied target with the
existing power limit fixed them. The same reachable-energy and preparation bounds
are included in historical MILP inputs, rather than allowing the optimizer to
rely on charging that its controller would predictably curtail. These probes were
not accepted as publication runs.

The first complete annual matrix, using the retained archive without downloads:

```text
.venv/bin/python scripts/backtest.py
exit 0
18 replications × 365 physical days × 4 strategies = 26,280 strategy-days
No stopped strategies; Time-of-Day 365/365 eligible days, Hourly 194/365
Full study generation: 1861.6711827500258 seconds
```

All three household configurations completed both tariffs at $0, $0.01 and $0.02
per internal-throughput kWh. Each Hourly replication excludes 171 days with
incomplete realized billing hours while carrying physical state through them.
Across sensitivity replications there are 5,031 eligible comparison-days out of
6,570 requested days. This is a full physical year, not a complete Hourly bill.
Annualized values remain eligible-day means × 365, with missing-data bias disclosed.
Negative savings, including the Time-of-Day solar-household results, are retained.
Observed aggregate cost, wear, loss and export totals use eligible comparison days;
full daily records retain physical energy for every simulated day.

An independent arithmetic/state audit confirmed equal EV delivery, terminal
battery energy, one appliance completion per day, zero comfort violations, and
null costs/savings on incomplete billing days. Maximum daily EV-energy error was
**8.145434549078345e-09 kWh** and battery-energy error was
**8.881784197001252e-16 kWh**, both below **0.000001 kWh**. Each strategy ends with
365 completed cycles (438 kWh); EV runs retain 4,380 kWh driven and the original
34% opening SoC after the final drive. Battery input minus output equals loss
within the same energy tolerance. Requested and applied controls, including
intra-slot completion boundaries, are retained in `results.json.gz`; the readable
`results.json` contains metrics and final states.

There were **6,569 optimal-status solves and one validated timeout incumbent**:
Hourly, solar/battery/EV, zero wear, **2026-01-28**, achieved gap
**0.0036811719670481616**. Its diagnostic says
`Time limit reached. (HiGHS Status 13: Time limit reached)`; this is not claimed
optimal. The five-second limit and requested 0.001 relative gap remain unchanged.
Five annual replications also matched earlier sequential runs exactly apart from
timing. A short, independent two-day matrix reproduced its full output, summary,
CSV, table and workload configuration. The full independent reproduction is
recorded in a subsequent entry; the annual matrix alone does not close item 17.

Local gates after the implementation and verifier regression:

```text
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/pytest --tb=short
921 passed, 61 deselected in 161.10s
Required test coverage of 80% reached. Total coverage: 91.96%

.venv/bin/pytest tests/unit/test_planner.py --no-cov -q --tb=short
46 passed in 8.58s

HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/pytest -m integration --no-cov --tb=short
61 passed, 917 deselected in 53.80s

.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 91 source files
```

The two planning scenarios pass with 16 observation checks, two planning snapshots
and 22 explicit deferrals each; the parents scenario passes with nine observation
checks and nine deferrals. Updated expectations come from the retained reports.
Linked-account provenance, the absence of the later kitchen request, and the
separate observation world remain verified. The isolated planner smoke exited 0:
**0.02991091599687934 s** solve, **0.0277769579552114 s** greedy proposal and
**0.6646711670327932 s** cold start. Earlier concurrent measurements of 0.073003 s
and 0.051419 s missed the greedy gate; the retained measurement ran after the
annual solver work and artifact writer exited, without changing the gate.

`uv build` produced the sdist and wheel. Installing the wheel in the disposable
`/private/tmp/hirz-item17-wheel` environment and leaving the checkout verified a
causal forecast replay and canonical Action hashes. No development migration or
physical plug check was performed. No new third-party API incompatibility was
observed; the previously documented sandbox escalations were reused. Final
formatting and the full offline reproduction remain closing checks below.

#### Independent reproduction failure and isolation — 2026-09-21

The first full `scripts/backtest.py --verify` replay completed all physical days
in 1,753.7478462501895 seconds but exited 1:
`offline_reproduction_matches: false`, `derived_artifacts_match: false`. Seventeen
of eighteen annual replications matched exactly apart from measured timing. The
remaining replication first differed on the recorded 2026-01-28 zero-wear Hourly
solar/battery/EV timeout: the fresh run reached optimal status in
2.9627819159068167 seconds, gap 0.0007238771401596331. Eleven daily records differed,
including propagated floating-point differences. No comparison tolerance or
solver budget was relaxed. The fresh complete output has 6,570 optimal-status
solves and is retained as the new reference. Concurrent replications were removed
and the prior report is now loaded only after solving, reducing resource
contention. A further full offline verification follows below; this failure does
not satisfy the reproduction gate.

#### Full offline reproduction and completion — 2026-09-21

The sequential full-year verification exited 0:

```text
.venv/bin/python scripts/backtest.py --verify
offline_reproduction_matches: true
derived_artifacts_match: true
elapsed_seconds: 2563.174393416848
```

All 18 annual replications match the retained complete reference exactly apart
from solver/run timing measurements: requested schedules, applied controls,
physical states (including appliance clocks), unrounded costs and savings. The
regenerated summary, CSV, README table and workload configuration also match. No
downloads, numerical comparison tolerance, hard-constraint relaxation or solver
budget change was used. The retained reference is the second complete run
(1,753.7478462501895 seconds); this isolated verification reports
2,563.174393416848 seconds for historical loading and replay, before final output
comparison/compression. The earlier timeout and failed reproduction remain
recorded above.

The study completes 26,280 strategy-days. Every Time-of-Day replication has
365/365 eligible days; every Hourly replication has 194/365. The other 171 Hourly
days preserve physical state but make no cost or savings claim. Headline and
sensitivity results, including negative savings, remain unrounded in the retained
outputs. README rows are copied from the generated table; annualized results are
eligible-day mean × 365 extrapolations with missing-data bias disclosed.

The reproduction command now checks for a retained reference before loading
history, preserving prompt failure for a missing `--output/results.json.gz` while
avoiding the reference's memory cost during timed solves. The timing/reproduction
workaround earned [friction entry 14](./friction-log.md); it is documented timeout
behavior, not a claimed upstream defect. Final local checks follow below.

A second independent arithmetic/state audit of the current reference passed:
26,280 strategy-days, 5,031 eligible
replication-days, and 6,570 optimal-status
solves. Maximum achieved gap is 0.0009989678086036007; maximum recorded solve time is
3.8145930408500135 seconds. Maximum daily EV-energy error is
8.145434549078345e-09 kWh; battery-energy error is
8.881784197001252e-16 kWh. All comfort checks, 365 cycles per
strategy, cumulative EV driving, equal terminal battery energy and cumulative
battery losses passed; incomplete billing days contain null costs and savings.

Final service-free regression run, including the new missing-reference check:

```text
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/pytest --tb=short
922 passed, 61 deselected in 84.54s
Required test coverage of 80% reached. Total coverage: 91.96%
```

The 61 PostgreSQL regressions, all three scenario commands, canonical-hash wheel
check and isolated demo/greedy performance gates recorded above remain applicable;
no pipeline, database, device adapter or scenario runner changed in this follow-up.
Ruff passed and mypy reported no issues in 91 source files. The final packaging
and post-documentation format check are recorded below.

Final packaging produced `dist/hirz-0.0.0.tar.gz` and
`dist/hirz-0.0.0-py3-none-any.whl`; every planner source in the wheel matches the
checkout. Final Ruff lint passed, mypy checked 91 source files without issues,
and `ruff format --check .` reported **146 files already formatted**. The format
check was repeated after this evidence append. Git's whitespace check passed
with CSV CRLF endings recognized. The instruction bodies match apart from their
pre-existing file-specific introductions, and the README table matches the
retained generated table exactly. Item 17's required local gates are verified;
item 15's physical plug checks and later-phase execution/persistence remain
pending. No remote CI result is claimed in this follow-up.

## Item 18 — 2026-09-21

### Implementation and initial local verification

Implemented the approved coordinator plan: deterministic bounded intake, canonical
provenance, household constraint/history tables, reserved Pipeline operations,
atomic signed record/withdrawal/replacement, context reads, conflict/precedence and
quorum reporting, split forecast windows, two-pass comfort/cost optimization and
explicit twin thermostat holds. Plan persistence, jobs, execution, automatic HA
change detection, MCP, UI and full scenario wiring remain deferred. No threat-model
row was promoted, and no remote CI result is claimed.

Commands used `HIRZ_DOGWOOD="$PWD/.tools/dogwood"` and
`UV_CACHE_DIR=/tmp/hirz-uv`. Local sockets required authorized sandbox escalation;
credentials were read from the existing `.env`, never changed. PostgreSQL migrations
and mutations ran only in uniquely named disposable databases. Development remains
on its previous revision; no `alembic upgrade` was run against it.

Initial failures were corrected rather than treated as completion: contradictory
bands initially raised planner validation instead of returning a conflict;
pre-item-18 catalog/count assertions expected 23 classes/56 compiled policies;
a legacy-migration test tried to read an old context projection with the new schema;
and the downgrade test initially expected the inner exception rather than Alembic's
redacted `CommandError`. Updated checks preserve their original guarantees.

Initial full checks (before the final direct-Pipeline authorization review):

```text
uv run pytest -q --tb=short
972 passed, 64 deselected in 91.77s (0:01:31)
Required test coverage of 80% reached. Total coverage: 90.70%

uv run pytest -m integration --no-cov -q --tb=short
64 passed, 972 deselected in 41.67s

uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 94 source files

uv run ruff check .
All checks passed!

uv build
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The full Python run includes native Cedar conformance for all catalog classes;
reserved constraint operations allow linked members on Alexa/app and deny unknown
members. PostgreSQL checks cover ownership, explicit and uniquely matched
replacement, duplicate delivery, cross-household requests, lower claimed roles,
paused-household independence, historical reads, renewal/release and rollback
when the signed recording append fails. Migration round trips compare metadata;
a downgrade with retained constraint evidence is refused without losing records.

`uv run python scripts/smoke_coordinator.py --audit-output
/tmp/hirz-coordinator-audit-20260921-final.json` returned:

```text
clarification=Please specify AM or PM; scripted answer=23:00
gate_1=PASS; linked=Malik; claimed_author=Dad
gate_4=PASS; dishwasher_start=2026-10-14 08:45:00+00:00
gate_2=PASS; target_f=72; mode=heat; source=manual:device; duration=2h
gate_3=PASS; Explicitly revise or withdraw 'car target to 60' to match the other target.
gate_5=PASS; Extend the 2026-10-13T22:45:00+00:00 deadline or explicitly lower the 50% target; no requirement was dropped.
coordinator=PASS; gates=5/5; audit_rows=12; offline=valid; device_actions=0
disposable_database=dropped; development_database=unchanged
```

The export verified against public-key fingerprint
`385589f309b374189ea1b391f4a3ad193f3674cf7fb6e72e1a97caf76e21912b`.
The dishwasher time is 03:45 America/Chicago, after the explicitly clarified 23:00.
The export is a private local artifact, not a committed secret or a published device
claim. The smoke's explicit twin observation identifies only its linked submitter.

Planner regression: `uv run python scripts/smoke_planner.py` exited 0 with a valid
optimal replay, 0.6479118750430644 seconds import time, 0.7562074998859316 seconds
cold total and a valid greedy proposal in 0.038480875082314014 seconds. Both
`demo-evening.yaml` and `demo-evening-hourly.yaml` exited 0 with
`item17_planning_and_observations_passed`, each with two passing planning snapshots.
`parents-scam-check.yaml` exited 0 with `item16_observations_passed`. These are their
existing staged assertions, not a claim of full tool/execution scenario wiring.
JSON outputs are in `/tmp/hirz-item18-planner.json` and
`/tmp/hirz-item18-{demo-evening,demo-evening-hourly,parents-scam-check}.json`.

Final review additionally moved constraint validation/ownership checks into
Pipeline assessment, so direct previews/proposals cannot report permission to
withdraw someone else's request. A new integration assertion exercises that path.
Preference-only incumbents now report no cost optimality gap when cost refinement
has not produced one. Final test reruns, full retained-backtest reproduction and
the final format check are still owed at this point; item 18 is not closed by this
initial entry. The repeated sandbox workarounds are recorded in the friction log.

### Final coordinator checks and backtest mismatch investigation

After the direct-Pipeline authorization review, unavailable zone observations
were also excluded from comfort priority, and selected preferences were carried
into baseline thermostat targets. Hold checks now meter the thermal energy for
heat, cool and off against every comparison. The final focused run passed
`34 passed, 3 deselected in 1.49s`.

```text
uv run pytest -q --tb=short
972 passed, 64 deselected in 112.70s (0:01:52)
Required test coverage of 80% reached. Total coverage: 90.62%

uv run pytest -m integration --no-cov -q --tb=short
64 passed, 972 deselected in 50.82s

uv run ruff check .
All checks passed!

uv run mypy hirz/ scripts/ alembic/
Success: no issues found in 94 source files

uv build
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The fresh coordinator smoke reproduced all five gates above and wrote
`/tmp/hirz-coordinator-audit-20260921-verified.json`: `audit_rows=12`,
`offline=valid`, `device_actions=0`, `disposable_database=dropped`,
`development_database=unchanged`. Logs:
`/tmp/hirz-item18-{tests,db,smoke,build}-verified.log`.

The first full `uv run python scripts/backtest.py --verify` completed all 18
replications without a stopped strategy, preserving 365/365 Time-of-Day billing
days and 194/365 Hourly billing days, but exited 1:

```json
{"offline_reproduction_matches": false, "derived_artifacts_match": false, "elapsed_seconds": 2541.4559225838166}
```

No retained output was overwritten. The workload templates match exactly. A
bounded diagnostic replay of the first seven days of every replication also
matches the retained daily traces exactly. The failed command's temporary output
was automatically removed by the existing verifier, so a second full comparison
is running with a temporary wrapper that retains each regenerated replication
and reports its first differing field in `/tmp/hirz-item18-backtest-diagnostic/`
and `/tmp/hirz-item18-backtest-verified.log`. Item 18 remains open until this
required reproduction gate and the final format check pass.

### Full retained reproduction and local completion

The diagnostic rerun invoked the existing `scripts.backtest.main()` with
`--verify`, wrapping only `run()` to retain and compare each completed replication;
solver parameters, inputs, comparison rules and retained published outputs were
unchanged. Every one of the 18 replication comparisons returned
`first_difference: null` and `nonoptimal: []`. All 6,570 MILP solves were optimal,
and all 26,280 strategy-days completed. The final verifier exited 0:

```json
{"offline_reproduction_matches": true, "derived_artifacts_match": true, "elapsed_seconds": 2906.818982375087}
```

That elapsed time includes the diagnostic wrapper's extra compression and
comparison work and is not a planner latency claim. The first failed comparison
was not reproduced; its exact cause remains unconfirmed because that run's
regenerated output was discarded by the existing verifier. Both outcomes remain
recorded above. No comparison was weakened, no retained artifact was replaced,
and no published figure changed. Hourly billing coverage remains 194/365 days.

The final code has the passing Python, native Cedar, PostgreSQL, signed-smoke,
planner/scenario regression, lint, type and package-build evidence recorded above.
`uv run ruff format --check .` returned `151 files already formatted`, and
`git diff --check` passed; the format check is repeated after the completion-record
updates. Third-party sandbox friction was checked and recorded. Item 18's required
local gates are verified. Remote CI is explicitly unverified. Development remains
on `0005_execution_attempt`; applying `0006_coordinator_constraints` is manual.
Plan persistence, refresh jobs, execution, automatic HA change detection, MCP/UI
and full scenario wiring remain later work; item 15's physical plug/absence checks
remain pending.

### Installed-wheel CI count correction — 2026-09-21

The [build job on `fda92c3`](https://github.com/BashaarJavaid/Hirz/actions/runs/35667718438/job/106557067937)
failed after successfully building and installing the wheel. Its packaged-catalog
assertion still expected 23 classes and situation groups; item 18 adds two reserved
constraint operations, making both counts 25. The exact failure was
`AssertionError` followed by `Process completed with exit code 1.` This was a stale
project assertion, not missing package data or third-party tool friction.

Rebuilt with `UV_CACHE_DIR=/tmp/hirz-uv uv build`, then loaded and executed the
workflow's unchanged `Fresh-wheel import and CLI outside the checkout` shell step
in a fresh temporary virtual environment. It reproduced the same `AssertionError`
locally. After changing that one workflow line to expect/report 25, repeated the
exact step in another fresh temporary environment, outside the checkout:

```text
PASS installed hirz 0.0.0
PASS packaged catalogs: 25 classes, 25 situation groups
usage: hirz [-h]
            {verify-audit,audit,decide,scenario,doctor,seed,context,constitution}
            ...
```

The corrected step exited 0. Temporary environments were removed. Dependency
installation and job-log retrieval needed the existing sandbox network workaround;
no new third-party defect earned a friction entry. No runtime code, dependency,
planner output or verification threshold changed. Broader Python and backtest
reruns are unnecessary for this workflow-literal correction; the pushed workflow
will rerun CI. Its outcome is not claimed by this pre-push evidence entry.

## Item 19 — 2026-09-21

Implemented durable local execution, explicit plan consent/revision/cancellation,
trusted observation ingestion, bounded endings and twin checkpoints. The approved
scope excludes development-database migration, remote CI dispatch and AWS. Native
Dogwood is the local boundary. Item 19a carries automatic refresh and freshness;
notification delivery and full scenario orchestration remain later work.

### Implementation checks and corrections

- Existing Pipeline/HA unit checks: `74 passed in 1.36s`; existing HA disposable
  integration checks: `8 passed in 5.17s`.
- First default executor smoke stopped before dispatch because `HIRZ_DOGWOOD` was
  unset: `Dogwood unavailable, timed out, or returned invalid output; no
  authorization`. Retained database:
  `hirz_ha_smoke_68b9f50e14d04925872a1390b519fb6b`.
- The next smoke correctly returned `DENY_RISK` for missing `target_is_bedroom`.
  Added explicit synthetic room metadata in the disposable bootstrap, not a runtime
  inference. Retained database: `hirz_ha_smoke_36b5dc1324dd4de0ab6f220b60194f35`.
- The separate-process twin smoke then passed: `submission=executing;
  boundary_calls=0; adapter_writes=0`, one worker sweep verified the light,
  `signed_rows=12`; private export `/tmp/hirz-item19-smoke-3.json` verified offline.
  Later checkpoint evidence changes are exercised by the final run below.
- Initial regression failures identified missing complete aggregate observations,
  startup restoration incorrectly rewinding an already-running injected clock,
  observation ingestion trying to insert a second current stream ID, and a retry
  audit timestamp older than a preceding lifecycle append. Corrected the production
  paths and retained regression checks. HA mismatch, hard-failure and crash cases
  then passed with a fresh retry ID and an unchanged original claim.
- The first live run stopped before a device write because the existing HA service
  was down: `Home Assistant unavailable; actual state unknown`. Retained database:
  `hirz_ha_smoke_70fa6eb98b244d26b2fe3d3a5150ac17`. Started the existing
  `homeassistant` Compose service; no volume reset or development migration.
- The live queue/worker run then verified `climate.heatpump` at 72 °F and
  `light.bed_light` on, and restored them through fresh Pipeline requests to 68 °F
  and off. `climate.ecobee` remained read-only. Output: `audit=valid; rows=40;
  offline=valid; live_demo=PASS`. Export: `/tmp/hirz-item19-live-2.json`.
  Every HA observation was labeled `real API, demo devices`.
- Full service-free Python regressions initially found seven stale catalog/count
  fixtures. Added the five reserved governance preview situations, updated risk and
  packaged-catalog assertions to 30, and the native compiled-policy assertion to 70.
  The subsequent full run passed: `1024 passed, 78 deselected in 107.72s`, coverage
  `83.72%` (80% required).
- The first full disposable integration run returned `1 failed, 77 passed`: the EV
  fixture had no `asset.policy.needed_by`, so Pipeline correctly returned
  `ASK_UNRESOLVED_CONDITION`. The isolated bootstrap now installs an explicit
  synthetic EV departure deadline. No policy condition was relaxed.
- Strict mypy reported `Success: no issues found in 104 source files`.
  `uv build` produced the sdist and wheel successfully. Final checks after the
  remaining dispatch-time TTL and signed-inverse changes are appended below.

All database tests use `--tb=short`; the initial sandbox-blocked legacy test run
used pytest's long traceback and exposed connection parameters in tool output.
No credentials were copied into repository files or evidence exports, and no
credential rotation was performed as part of this task.

### Final local verification — 2026-09-21

Commands used the existing environment with `UV_CACHE_DIR=/tmp/hirz-uv` and
`uv run --no-sync`; native checks set `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`.
Database/socket commands used the approved sandbox escape, existing local
PostgreSQL and HA demo services, and uniquely named disposable test databases.
No dependencies were added and no development migration was applied.

- `pytest -q --tb=short`: **1024 passed, 78 deselected in 108.68s**;
  **83.46% coverage**, above the 80% gate. Includes native Dogwood conformance.
- `pytest tests/integration -m integration --no-cov -q --tb=short`:
  **78 passed in 78.95s**. Includes the new executor checks and existing database,
  audit, boundary, approval and HA fail-closed regressions.
- After the final signed plan-hold event, due-ending ordering, post-ending
  observations and pre-dispatch tampering checks,
  `pytest tests/integration/test_executor_database.py -m integration --no-cov -q --tb=short`:
  **14 passed in 29.36s**. A further late-start assertion is recorded below.
- `python scripts/smoke_executor.py --audit-output /tmp/hirz-item19-twin-final-20260921.json`:
  **PASS**; submission `executing`, `boundary_calls=0`, `adapter_writes=0`;
  a separate worker process verified within one sweep, native boundary allowed,
  source `twin`, **16 signed rows**, offline verification valid. Scratch database
  dropped after success.
- `python scripts/smoke_executor.py --live-demo --audit-output /tmp/hirz-item19-ha-final-20260921.json`:
  **PASS**; heatpump **68 → 72 → 68 °F**, light **off → on → off**, each queued
  and verified by the worker; ecobee read-only. Source `real API, demo devices`,
  **40 signed rows**, offline verification valid. Restoration used fresh Pipeline
  requests. Scratch database dropped after success. These two final smoke runs
  preceded the final bounded-ending/hold changes, which the focused rerun covers.
- `ruff check .`: **All checks passed!** Strict `mypy hirz/ scripts/ alembic/`:
  **Success: no issues found in 104 source files**.
- Final `uv build`: successfully built `dist/hirz-0.0.0.tar.gz` and
  `dist/hirz-0.0.0-py3-none-any.whl`. An isolated Python invocation from
  `/private/tmp` loaded Hirz directly from that wheel and imported `Executor` and
  `PlanService`; both packaged catalogs contained **30** entries. This packaging
  probe reused installed dependencies; it was not a fresh dependency installation.
- A read-only query of the development database returned
  **0005_execution_attempt**, unchanged. Migration 0007 was exercised only in
  disposable databases, including schema matching and downgrade refusal.

The regressions cover trusted scheduler attribution and revoked linkage, fresh
sleep observations, plan roles/consent/revisions/budget reservation, refreshing-plan
refusal, expiring approvals, household isolation, retained bounded endings across
pause/cancellation/policy changes, tamper refusal, overlap/expiry, checkpoint
configuration and restart, concurrent-worker exclusion, audit failures, explicit
rollback, twin HVAC/EV/battery/appliance/lights, direct HA verification, mismatch,
hard failure and crash recovery with a fresh retry Action. Existing evidence is
preserved; no execution claim is reused. Pending notices claim a stored message,
not delivered push/email.

The physical-plug gate, AWS enforcement/home-owned offline endings, remote CI,
automatic refresh/freshness (19a), notification delivery and full scenario wiring
remain pending. No broader physical-safety or AWS threat-model row was promoted.
The third-party friction log records the sandbox workaround; no other new
third-party defect was established.

Final late-start regression rerun: **14 passed in 30.37s**. It starts a bounded
operation 15 seconds late, asserts its stored ending still uses the original
30-second end, and verifies that ending. `git diff --check` passed.

Completion records and AGENTS/CLAUDE guidance are synchronized (their existing
heading/introduction differences remain). The final format check first identified
two unformatted additions in HA verification and twin battery observations; Ruff
formatted both, and the sdist/wheel were rebuilt successfully. The subsequent
`ruff format --check .` returned **163 files already formatted**; the check is
repeated after this evidence append as the final validation command.

## Item 19a — 2026-09-21

### Local implementation and regression evidence

Implemented the approved local refresh contract in [architecture §5.4](../ARCHITECTURE.md#54-planner), with persistence/ownership in [ADR-002](./adr/ADR-002-postgres-over-dynamodb.md#durable-refresh-amendment--2026-09-21), authority/accounting in [ADR-003](./adr/ADR-003-constitution-yaml-to-cedar.md#durable-refresh-amendment--2026-09-21), and remaining-work planning in [ADR-005](./adr/ADR-005-deterministic-planner.md#durable-refresh-amendment--2026-09-21). Procedures are in [development](./development.md#item-19a-durable-local-plan-refresh).

Environment: macOS arm64, Python 3.12.13 in the existing `.venv`, pinned native
`.tools/dogwood`, local PostgreSQL 16 and the configured HA demo. Tests and smokes
migrate uniquely named disposable databases through `0008_plan_refresh`. A separate
read of development's `alembic_version` returned `0005_execution_attempt` after the
smokes. No development migration or reset was performed. Local sockets and uv's
existing cache required the already documented sandbox access; no dependencies or
AWS resources were added.

Final commands and observed results:

```text
.venv/bin/pytest --tb=short -q
1065 passed, 88 deselected in 220.28s (0:03:40)
Required test coverage of 80% reached. Total coverage: 80.32%

.venv/bin/pytest tests/integration -m integration --no-cov --tb=short -q
88 passed in 222.65s (0:03:42)

.venv/bin/ruff check .
All checks passed!

.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 111 source files

uv build --out-dir /tmp/hirz-19a-dist-final
Successfully built hirz-0.0.0.tar.gz and hirz-0.0.0-py3-none-any.whl
```

The full Python run includes native YAML/Dogwood conformance, planner and latency
checks. A separate isolated import from the extracted wheel passed the CI catalog
assertion: **31 classes, 31 situation groups**, and imported the packaged refresh
worker. The CI wheel assertion was updated with the added internal governance class;
remote CI was not run. Full run logs are `/tmp/hirz-19a-coverage-verified.log`,
`/tmp/hirz-19a-integration-verified.log` and `/tmp/hirz-19a-build-final.log`.

The refresh tests cover all eight trigger sources and duplicate polls against
persisted generations; strict threshold boundaries; first-sample/manual hold
creation, renewal, release and expiry; recorded HA attribution with preserved
upstream timestamps; unapproved and inherited consent; a same-instant consent
race; legacy-input refusal; cross-household reads; concurrent solver ownership;
an ending during a delayed solve; changes arriving during computation; cancelled
and abandoned-running work; audit failure; revoked authority; polling recovery;
5/30/60/300/300-second backoff and no waiting for future retries; notice deduplication;
required missing domains; fixed controls, running/completed appliances and original
battery/EV obligations; exhausted operations; historical held reads; retained grant
dates, negative estimates, uncertain dispatch and transactional budget refusal.
The existing concurrent-budget, boundary, dispatch/retry and migration tests also
pass in the full PostgreSQL suite. No delivery or actual-billing settlement is
claimed.

Final separate-worker smoke commands (with `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`):

```text
.venv/bin/python scripts/smoke_refresh.py --audit-output /tmp/hirz-refresh-twin-20260921-verified.json
restart=queued; replacement=published; approver=malik; per_device_evaluation=fresh
restart=running; replacement=published; approver=malik; per_device_evaluation=fresh
refresh=PASS; source=twin; signed_rows=74; offline=valid

.venv/bin/python scripts/smoke_refresh.py --live-demo --audit-output /tmp/hirz-refresh-ha-20260921-verified.json
restart=queued; replacement=published; approver=malik; per_device_evaluation=fresh
restart=running; replacement=published; approver=malik; per_device_evaluation=fresh
refresh=PASS; source=real API, demo devices; ecobee=read_only
restoration=light.bed_light; verified=True
restoration=climate.heatpump; verified=True
audit=valid; rows=106; offline=valid
live_demo=PASS; ecobee=read_only
```

Both successful disposable databases were dropped; private signed exports remain
at the named paths. Logs are `/tmp/hirz-19a-twin-verified.log` and
`/tmp/hirz-19a-ha-verified.log`. The HA smoke uses explicitly synthetic thermal
parameters, not a calibrated home model. Its real API/demo-device provenance remains
visible, and all changed settings were restored through Pipeline.

Earlier runs were not treated as completion: coverage initially passed the tests
but failed the gate at **77.34%**, then **78.97%** and **79.79%**. Added behavioral
checks reached **80.36%**, and the final source state above reaches **80.32%**.
Early failures exposed missing legacy test inputs, optional HA setpoint increments,
HA workload/domain budget scoping, retained prediction coverage when slots split,
and premature plan completion. Failed live trials restored their changed settings
and retained signed exports (`/tmp/hirz-refresh-ha-20260921.json`, and `-b` through
`-f` variants). A twin restart also failed closed with `Invalid audit pointer or
incompatible signing key`: a lifecycle row was later than the physical checkpoint.
Restore now uses the latest signed simulated instant and advances from the
checkpoint; the final separate-worker runs above verify it. The failed disposable
database `hirz_ha_smoke_5568fefa8c0d495e9b6204276db3b4a8` remains retained as evidence.
A late test fixture reused a deterministic plan ID after cancellation; a distinct
explicit workload corrected that fixture, and the full 88-test run passes.

Checked `docs/friction-log.md`. Cache/socket restrictions repeat its existing
entries; the HA increment issue was our incorrect assumption, not an upstream
contract defect. No new third-party friction entry was earned. HA's optional
increment contract is linked in `RefreshWorker.ha_facts`.

At this entry, the offline backtest has finished all 18 combinations with no stopped
runs and is still comparing retained outputs. Item 19a is not closed until that
result and the final formatting check are appended below. MCP tools, companion
endpoints/delivery, full scenario orchestration, live price/weather ingestion,
AWS, remote CI and item 15's physical-plug gate remain outside this verification.

### Retained reproduction and closure — 2026-09-21

`.venv/bin/python scripts/backtest.py --verify` exited **0** after all 18
profile/configuration/wear combinations (26,280 strategy-days), with no stopped
runs. The reported computation elapsed time was **3007.7092511251103 seconds**;
retained-result loading and artifact comparison followed it. Final output:

```json
{"offline_reproduction_matches": true, "derived_artifacts_match": true, "elapsed_seconds": 3007.7092511251103}
```

Full log: `/tmp/hirz-19a-backtest.log`. Published files and figures were not rewritten.
Hourly billing coverage remains 194/365 days (0.5315068493150685); all strategy days
completed, and completion is not represented as complete historical billing data.
The source distribution and wheel were rebuilt from the final source state.

The first final format check found one assertion needing line wrapping in the
existing executor integration test. After formatting that assertion,
`.venv/bin/ruff format --check .` passed: **172 files already formatted**. Ruff lint,
strict mypy and `git diff --check` also passed. All local item 19a gates are earned;
completion records are updated below this evidence without changing published
backtest artifacts or advancing the development database.

## Item 20 — 2026-09-21

### Backend implementation and local gates

Implemented the approved consent-gated memory plan under
[architecture §5.9](../ARCHITECTURE.md#59-memory), with the decisions and rejected
alternatives in ADR-002, ADR-003 and ADR-005's item 20 amendments. No development
migration, live HA write, AWS call or new dependency was introduced. Verification
uses Python 3.12.13, native `.tools/dogwood`, local PostgreSQL disposable databases,
and the existing local P-256 key for smoke exports; tests generate their own keys.

Final service-free regression, including native policy conformance:

```text
.venv/bin/pytest -q --tb=short
1111 passed, 95 deselected in 179.08s (0:02:59)
Required test coverage of 80% reached. Total coverage: 80.70%
```

Final PostgreSQL regression:

```text
.venv/bin/pytest -m integration --no-cov -q --tb=short
95 passed, 1111 deselected in 191.74s (0:03:11)
```

Both final commands ran with authorized localhost access. The first sandboxed
service-free run reported six failures: two blocked localhost WebSocket fixtures
and four stale risk-catalog assertions, with 79.25% coverage. Catalog assertions
were updated for `governance.memory`, and the added command/provider/reference tests
exercise the memory code without a database. Earlier targeted checks exposed a
backdated synthetic clock after a concurrent review; advancing that fixture clock
fixed the test. Final results above include these fixes. The shell initially
selected Node 23; the package checks were repeated with the documented Node 24
path, as recorded below. These failed/intermediate runs are not completion evidence.

Memory-specific coverage exercises:

- Private turn bounds, ordering, exclusive-cursor pagination, session/member/surface
  and household isolation; exact provider hint scoping and provider outage fallback.
- Source-turn ownership despite a claimed name; member-scoped numeric candidates,
  confidence bounds, learning-disabled creation/acceptance, app-only subject review,
  refusal of owner-on-behalf consent, acceptance with/without an existing preference,
  stale versions and duplicate graph-row refusal.
- Identical mutation retries, changed-content refusal, concurrent accept/reject with
  exactly one terminal transition, preference history, rollback on signed-append or
  commit failure, and rollback of preference/consent/plan holds when refresh auditing
  fails. Malformed direct Pipeline memory envelopes are rejected before storing
  transcript-bearing parameters.
- Latest explicit references, missing/stale/unavailable objects, unavailable
  VerificationCases, unknown kinds and database-outage clarification. References
  convey no execution authority.
- Presence freshness, expected-arrival start/end, contradictory room evidence,
  explicit member request precedence, conflicting graph preferences, unchanged hard
  bounds/manual holds, and graph identity/version/member provenance. A refresh
  regression verifies that removing room evidence restores household baseline
  targets instead of retaining an obsolete applied preference.
- Native Dogwood operation/surface/learning gates and migration roundtrip/schema
  checks; all existing Pipeline, graph, executor and refresh integration checks.

The final feature smoke was run as a separate CLI process:

```text
HIRZ_DOGWOOD="$PWD/.tools/dogwood" .venv/bin/python scripts/smoke_memory.py --audit-output /tmp/hirz-memory-item20-verified-audit.json
memory=PASS; pending/rejected=unchanged; accepted=74F; service_restart=persisted; worker_restart=published; approver=malik; device_grant=fresh; obsolete_attempts=0; source=twin; signed_rows=54; offline=valid; export=/tmp/hirz-memory-item20-verified-audit.json
disposable_database=dropped; development_database=unchanged
```

The smoke compares effective PlannerInput before/pending/rejected/accepted states,
reconstructs MemoryService with an empty provider, runs a fresh `hirz worker --once`
process, checks inherited Malik consent, and verifies a post-acceptance native
Dogwood grant plus simulated device read-back. Obsolete plan actions have zero
dispatch attempts. Its 54-row export is independently verified using the original
key's separately supplied fingerprint. The private export remains at the path above;
it contains no session transcript. A final read-only query independently reported
`development_revision=0005_execution_attempt`.

Additional checks:

```text
.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 118 source files
UV_CACHE_DIR=/tmp/hirz-uv uv build --offline --no-build-isolation
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The wheel was installed with `uv pip install --offline --no-deps --target` in a new
`/tmp` directory and imported from outside the checkout under isolated Python:
`PASS installed memory service; 32 classes; 32 situation groups`. The CI wheel
assertion now expects the same catalog size. With Node **24.21.0** and pnpm
**12.4.2**, `pnpm -r lint`, `pnpm -r typecheck` and `pnpm -r test` all passed;
web and mcp-app each reported **1 test passed**. `git diff --check` passed.
Repeated uv/localhost sandbox friction is appended to the existing friction log;
no new upstream API defect was observed.

At this entry, the full retained-backtest reproduction is still running; item 20
is not yet closed. Final reproduction and post-documentation formatting evidence
will be appended below. No authenticated companion consent, AWS Memory integration,
automatic extraction, other preference type, public memory CLI, cleanup job, live
feed ingestion or remote CI result is claimed.


### Retained reproduction and local completion

The complete `.venv/bin/python scripts/backtest.py --verify` exited **0**, running
all 18 profile/configuration/wear combinations from the retained archive. Every
simulation reported an empty `stopped` list. Final output:

```json
{"offline_reproduction_matches": true, "derived_artifacts_match": true, "elapsed_seconds": 2731.716256540967}
```

The verifier reproduced the retained results and derived artifacts without changing
published figures. This completes item 20's remaining reproduction gate. The full
service-free/PostgreSQL suites, native policy conformance, fresh service/worker
smoke, independently verified signed audit, package checks and development-database
revision check are recorded above. Completion records and the local-backend-only
threat-model qualification were updated after this result. The final
post-documentation format and diff checks are recorded below.

Final completion-record checks:

```text
.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 118 source files
git diff --check
(no output; exit 0)
.venv/bin/ruff format --check .
181 files already formatted
```

`AGENTS.md` and `CLAUDE.md` carry matching project guidance, including item 20's
command and item 21 as next. The format check was repeated after this evidence
append and passed. Development migrations remain manual; public authentication,
companion consent UI and AWS integration remain outside the completed local item.

## Item 21 — 2026-09-22

Scope: validated narration for canonical Plans and Decisions, the fixed offline-tested
Bedrock Converse provider, backend integration and persisted reuse. The approved
choices and rejected alternatives are in [ADR-012](./adr/ADR-012-explainer.md).
No migration, backfill, new cache table, live model call, MCP tool or UI was added.

Environment: macOS, repository Python 3.12 virtual environment, native pinned
Dogwood, and the existing Compose PostgreSQL 16.15 service. Boto3 1.43.90 and its
resolved dependencies are pinned in `uv.lock`. Dependency resolution used
`uv add 'boto3==1.43.90'`. The standard uv cache and loopback checks required the
existing sandbox escalation; [friction log entry 6 follow-up](./friction-log.md)
records the observed restriction. No AWS credential/client initialization occurs
in the offline implementation; SDK tests supply dummy credentials explicitly.

Implementation evidence:

- The planner's schedules, action hashes, physical replay, savings calculations and
  authorization fields remain unchanged. Narration attaches only `speakable` and
  optional metadata. Existing planner, pipeline, executor and refresh regressions
  pass; injected provider fields cannot modify decisions or actions.
- Unit checks cover all canonical Plan statuses, execute/ask/deny/verify outcomes
  and execution statuses; phone-only security wording; source labels; legacy
  metadata omission; ROUND_HALF_UP, signed/rounded-zero figures, units and local
  times; schema/length boundaries; invalid and negative saving comparisons;
  private text/IDs; linked-account and explicitly claimed attribution; provider
  failures, truncation, malformed output, status claims and cancellation.
- Botocore `Stubber` validates the actual Converse request, including native
  `outputConfig.textFormat` schema, inference profile, temperature and output token
  limit. A lazy-client test verifies region, 2/5-second timeouts and one total
  attempt. Successful output and fallback survive JSON round-trip/restart without
  a second provider invocation. Offline configuration initializes no AWS client;
  invalid `HIRZ_LLM` fails configuration.
- PostgreSQL tests verify audited Decision/Plan publication, valid signed rows,
  stored fallback reuse through a fresh service/provider, held-read honesty,
  household isolation, and a changed execution outcome receiving a new template.
  A refresh input arriving while async narration is in progress prevents the
  obsolete result from publishing. Coordinator and worker tests assert the database
  connection is outside a transaction during enrichment.

Commands and observed results:

```text
.venv/bin/pytest tests/unit/test_explainer.py --no-cov -q
80 passed in 2.28s

uv run pytest -q
1191 passed, 97 deselected in 127.11s (0:02:07)
Required test coverage of 80% reached. Total coverage: 81.00%

uv run pytest -m integration --no-cov -q --tb=short
97 passed, 1191 deselected in 130.07s (0:02:10)

.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 123 source files

uv build
Successfully built dist/hirz-0.0.0.tar.gz
Successfully built dist/hirz-0.0.0-py3-none-any.whl
```

The attribution guard received a final refinement after the full-suite run above:
provider prose must include both `Linked account: <name>` and
`Claimed author: <name>` for claimed authorship, rather than merely the word
"claimed". The 80-test focused run above includes that refinement; a final
full-coverage rerun is appended below. Package lint, strict typing and build were
run after the refinement. Wheel inspection found the four Explainer Python files
and `Requires-Dist: boto3==1.43.90`.

User-facing offline invocation:

```text
.venv/bin/python scripts/smoke_explainer.py
offline=PASS; fabricated_figure=rejected; canonical_plan=unchanged; actions=105; cached=valid
{'headline': 'An energy plan is ready for review.', 'details': ['Simulated data.', 'Estimated difference versus your timer schedule: $0.37.'], 'options': ['Review']}
```

The displayed figure is derived from this run's planner output, not a new published
savings claim. The simulated source label is code-owned.

Disposable database smoke (with `HIRZ_DOGWOOD="$PWD/.tools/dogwood"`):

```text
uv run python scripts/smoke_explainer.py --integration --audit-output /tmp/hirz-item21-final-audit.json
integration=PASS; decision=audited; plan=audited; restart=reused; source=twin; signed_rows=7; offline=valid; export=/tmp/hirz-item21-final-audit.json
disposable_database=dropped; development_database=unchanged
```

The smoke independently verifies the export against the trusted signing-key
fingerprint. It uses only a uniquely named disposable database and existing
synthetic bootstrap conventions. The earlier successful export is also retained
at `/tmp/hirz-item21-audit.json`; both exports are private local artifacts, not
committed evidence. A read-only development revision check returned:

```text
docker compose -f compose.dev.yml exec -T postgres psql -U hirz -d hirz -Atc 'select version_num from alembic_version'
0005_execution_attempt
```

Existing scenario gates, all exit 0, with the same native Dogwood environment:

| Command suffix after `.venv/bin/hirz scenario run` | Result | Checks | Planning snapshots | Deferred assertions/events |
|---|---|---:|---:|---:|
| `scenarios/demo-evening.yaml --headless --assert` | `item17_planning_and_observations_passed` | 16 | 2 | 22 |
| `scenarios/demo-evening-hourly.yaml --headless --assert` | `item17_planning_and_observations_passed` | 16 | 2 | 22 |
| `scenarios/parents-scam-check.yaml --headless --assert` | `item16_observations_passed` | 9 | 0 | 9 |

The JSON reports are `/tmp/hirz-item21-evening.json`,
`/tmp/hirz-item21-hourly.json` and `/tmp/hirz-item21-parents.json`. These are the
existing observation/planning assertions, not full tool or demo execution.

Failures observed and resolved during implementation:

- The first new unit run reported `2 failed, 76 passed`: heading and list formatting
  were not rejected. The shared artifact guard now rejects both.
- The first PostgreSQL attempt reported `1189 deselected, 95 errors` because local
  PostgreSQL was stopped. `docker compose -f compose.dev.yml up -d postgres`
  started the existing service; subsequent disposable tests ran against it.
- The first complete service-free run reported `1 failed, 1188 passed, 95 deselected`
  with 80.96% coverage. Its held-read mock lacked the newly required snapshot and
  expected the old detail ordering. The test now supplies trusted context and
  verifies the current source label/historical forecast wording without modifying
  the persisted plan.
- The first database run after startup reported `2 failed, 93 passed`: missing or
  foreign approval lookups carry no Action, which the new narration context lookup
  initially assumed existed. The shared context helper handles that existing denial
  path conservatively; the missing-approval and cross-household tests then passed.
- The first new publication assertion matched both the Decision and the publication
  audit event with the same event name; it now selects the publication's `mutation`
  payload. The focused database rerun reported `16 passed in 15.31s`.
- The first smoke exposed a fixture clock mismatch:
  `hirz.graph.models.GraphError: Coordination requires the current household snapshot`.
  The forecast and scenario clock are now aligned before observations are ingested.
  As required by the existing disposable helper, that failed synthetic database was
  retained: `hirz_ha_smoke_5c994afc63074cb3a0b78f162dff3656`. It contains no real device
  writes; successful smoke databases were dropped.
- Strict typing initially found a lost Optional narrowing after updating a
  PlannerResult and an un-narrowed audit JSON value in the smoke. Both are corrected;
  final strict mypy passes without broad ignores.

Limits: figure-set membership does not prove prose truth; an approved figure can
still be associated with the wrong fact. Live Bedrock availability, credentials,
model/native-schema acceptance and latency remain item 38. Protect, drafting,
external orchestrator behavior, MCP/UI and full scenario execution are unverified.
No live HA check, remote CI run or full year-long backtest rerun was claimed.

Final coverage run after the attribution refinement:

```text
uv run pytest -q
1191 passed, 97 deselected in 110.52s (0:01:50)
Required test coverage of 80% reached. Total coverage: 81.03%
```

Item 21's local gates are complete. The roadmap, changelog, narrowly qualified
threat-model claims and both instruction files were updated after these results.
Live Bedrock verification remains item 38; item 22 is next.

Final completion-record checks after documentation edits:

```text
.venv/bin/ruff check .
All checks passed!
.venv/bin/mypy hirz/ scripts/ alembic/
Success: no issues found in 123 source files
git diff --check
(no output; exit 0)
.venv/bin/ruff format --check .
189 files already formatted
```

The Commands and Current phase sections match in `AGENTS.md` and `CLAUDE.md`;
their pre-existing heading/introduction differences are preserved. The format
check was repeated after this evidence append and passed.

## Item 22 — 2026-09-22

### Implementation and intermediate verification

Implemented the internal scripted scenario host, disposable execution/artifacts,
planned-device approval resumption, and the approved scenario bootstrap described
in [ADR-005](./adr/ADR-005-deterministic-planner.md#planned-device-approval-resumption--2026-09-22-author-approved)
and [ADR-006](./adr/ADR-006-twin-first-adapters.md#executable-scenarios--2026-09-22-author-approved).
These intermediate checks do **not** close the overnight execution gate.

Environment: local macOS ARM64, Python 3.12, existing PostgreSQL and HA demo services,
pinned native Dogwood at `.tools/dogwood`, and the existing local signing key.
Commands used `HIRZ_DOGWOOD="$PWD/.tools/dogwood"` and
`UV_CACHE_DIR=/tmp/hirz-uv-cache`; socket/database checks ran with local network
access. Development migrations were not applied. The stopped HA demo container
was started using `docker compose -f compose.dev.yml start homeassistant`, retaining
its volume. No AWS, Bedrock, public price/weather fetch, push or remote CI run occurred.

- `uv run pytest -q`: **1,216 passed, 107 deselected, 80.48% coverage** (166.16 s).
  Earlier full runs exposed the sandbox's loopback restriction and coverage below
  80%; these were failures, not completion evidence. The host, export and prediction
  regression checks were added before the passing coverage run.
- `uv run pytest -m integration --no-cov -q`: **107 passed, 1,216 deselected**
  (199.37 s), using uniquely named disposable databases. Planned-action cases cover
  affirmative/rejected/expired votes, cancellation, revision, changed policy/hash/
  inputs, revoked authority, restart, concurrent responses and required endings.
- `uv run hirz scenario run scenarios/demo-evening-hourly.yaml --headless --assert`:
  `item17_planning_and_observations_passed`, 16 checks and 22 explicit deferrals.
  Parents: `item16_observations_passed`, 9 checks and 9 deferrals. Their unimplemented
  execution assertions were not promoted.
- `uv run python scripts/smoke_scenario.py --live-demo --artifacts-dir
  secrets/scenario-runs/item22-ha-final`: `execution_checks_passed`, `restored: true`,
  source `real API, demo devices`, **31 valid signed rows**. The lamp was restored
  through its authorized ending; its disposable database was dropped. The later
  `item22-ha-verified` run also passed with restoration. Physical-plug verification
  remains separate and pending.
- `uv build` built the sdist and wheel. The wheel was installed into
  `/tmp/hirz-item22-wheel`; isolated import resolved to its `site-packages/hirz`.
  Its `hirz scenario step scenarios/demo-evening.yaml --to 17:33 --assert
  --artifacts-dir secrets/scenario-runs/item22-wheel-step` returned `stopped`,
  with **9 valid signed rows**, no 17:33 planning event, and a dropped disposable
  database. This step result is not an overnight pass.
- Independent `verify_file` checks derived the public-key fingerprint from the
  configured signing key, rather than trusting the export. They accepted the above
  exports; changing a retained HA audit payload was rejected with
  `Envelope hash mismatch`. Artifact directories were `0700` and report/audit/PEM
  files `0600`; existing destinations were refused. Unit orchestration checks cover
  pacing equivalence, target-time exclusion, assertion failures and retained versus
  dropped database behavior at mocked service seams, not a second device integration.
- Ruff and strict mypy passed (128 source files). The scenario CI job's YAML and
  shell syntax passed local checks; its remote job has not run.

The required full command was exercised repeatedly with new artifact directories.
`item22-run12` retained **20,316 valid signed rows** and database
`hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d`; 23:31 consent failed with
`ValueError: Plan is not eligible for fresh consent`. Dad's 22:40 explicit revision
paused the still-unstarted guest-room preheating. The author approved an earlier
explicit 72°F request, now recorded at 17:35 and covered by 17:36 consent.

`item22-run13` reached 07:00 but was **not successful**: it retained **18,012 valid
signed rows** and database `hirz_ha_smoke_651bdaf1cbed44f18850ed538ecbd9a6`.
Its final check hit `KeyError: 'claimed_author'` because absent optional provenance
fields are omitted, and overnight plans remained held on invalid comparisons.
The diagnostic exposed a timer baseline that restarted its window after midnight
and a replaced EV target that could revert to the old default after its deadline.
Those root causes were corrected, along with demonstrated charge-limit roundoff
(`0.5000000000000001` for a 50% goal), normalized control comparisons and partial-slot
EV power prediction. Interrupted and failed diagnostic runs retain their databases
and available private evidence; none is counted as a successful execution.

The initial forecast assertions were generated from run12's signed `PLAN_CREATED`
summary, with the existing numeric tolerance. They are the initial 17:33 forecast,
not accumulated savings across revisions. Historical backtest figures and retained
inputs were not edited. Friction-log review found no new third-party API defect;
the already-recorded local sandbox/cache restriction was handled with the existing
cache/network procedure.

### Final test and packaging pass

After the startup-failure evidence guard and the last EV/battery rollover fixes:

- `UV_CACHE_DIR=/tmp/hirz-uv-cache uv run pytest -q`: **1,219 passed,
  107 deselected in 211.27 s; 80.51% coverage**. The existing loopback tests used
  authorized local network access.
- `uv run pytest -m integration --no-cov -q`: **107 passed, 1,219 deselected
  in 251.92 s**, using disposable PostgreSQL databases.
- Ruff and strict mypy passed: **128 source files**. `uv build` produced the sdist
  and wheel; the rebuilt wheel's isolated step run (`item22-wheel-verified`)
  returned `stopped`, with **9 valid signed rows** and an exclusive `0600` report.
- The final Hourly regression again returned `item17_planning_and_observations_passed`
  (16 checks, 22 deferrals). The final HA run (`item22-ha-verified`) returned
  `execution_checks_passed` with restoration and **31 valid signed rows**.
  Independent fingerprint verification accepted both retained wheel/HA exports;
  their databases were absent afterward. Their directories were `0700` and all
  three evidence files were `0600`. Development remained on `0005_execution_attempt`.
- The scenario CI YAML and every workflow shell block passed local parsing checks.
  A subsequently observed native solver stdout diagnostic earned an appended
  [friction entry](./friction-log.md); CI uses `--output` for structured reports.
  No remote CI run or push was performed.

Run16 was interrupted after diagnosing the timer baseline's battery floor resetting
at midnight. Its retained database is
`hirz_ha_smoke_854f4e3b7ac54f0686850005e024b9f9` and its export contains
**18,235 valid signed rows**. Replaying its remaining workload after anchoring the
battery window to the same deadline-relative timer start made all three comparison
baselines valid, each ending at **7.425 kWh** within numeric tolerance. This diagnostic
is not an overnight completion claim.

### Run17 final-gate failure and follow-up

The full command reached 07:00, then correctly returned exit 1 with four failed
checks: `separate_nighttime_votes`, `dad_kitchen_constraint_enforced`,
`completed_current_plan`, and `battery_terminal_preserved`. Its database
`hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f` and private `item22-run17`
artifacts are retained; **27,361 signed rows verified**, 68 visible device responses
were recorded, and the EV delivery/ceiling, comfort and initial forecast checks
passed. This is not an item 22 completion.

The dishwasher had already run at 17:36. The author approved an explicit 17:35
request to run it after 23:31; the script uses the existing normalized intake
sentence, “Do not run the dishwasher before 23:31.” Dad's request and the fresh
23:31 plan consent remain separate. The battery diagnostic showed that comparison
baselines stopped charging at 06:00 despite the accepted 07:00 terminal obligation;
late feasible workloads were held and subsequently became infeasible. The shared
baseline now continues necessary restoration through the horizon, with a late
04:45-start regression. Focused planner/scenario checks: **75 passed in 8.18 s**.

After the author-approved dishwasher timing and late-morning baseline fix, the
final regression suite returned **1,220 passed, 107 deselected in 174.81 s,
80.51% coverage**; disposable PostgreSQL returned **107 passed, 1,220 deselected
in 224.68 s**. Ruff and strict mypy again passed (128 source files). The sdist and
wheel rebuilt successfully; the reinstalled wheel's `item22-wheel-final` step run
returned `stopped` and removed its disposable database. Hourly and parents were
rerun through `--output`: respectively `item17_planning_and_observations_passed`
(16 checks, 22 deferrals) and `item16_observations_passed` (9 checks, 9 deferrals).
No historical backtest output was edited; a new full-year reproduction was not
part of this final rerun.

### Run18 and exact-duration correction

Run18 reached 07:00 with **26,512 valid signed rows** but failed
`completed_current_plan` and `battery_terminal_preserved`. Its database
`hirz_ha_smoke_59383ac7ac894c0180995fdac5b93cb0` and private `item22-run18`
artifacts remain retained. The other 45 checks passed, including the dishwasher's
separate approval and Dad's constraint: its verified opening was 23:46:01, after
the explicit 23:31 consent. EV delivery and the ceiling also passed.

The remaining failure exposed the host's one-second refresh delay after a simulated
write's microsecond tick. At 06:00 a plan needed the full remaining charging interval;
the artificial gap made that interval infeasible. On 2026-09-22 the author approved
fractional `Revert.after_s` durations as an additional canonical interface amendment.
The host no longer introduces that gap; planner/retry endings retain exact durations,
existing integer hashes round-trip unchanged, and strict invalid/sub-microsecond
inputs fail. Focused executor/scenario tests passed **36 tests in 3.28 s** after
fixing a missing import in the new test. No failure above is counted as completion.

After the approved fractional-duration amendment, the full service-free suite
returned **1,221 passed, 108 deselected in 195.43 s; 80.53% coverage**. Disposable
PostgreSQL returned **108 passed, 1,221 deselected in 250.56 s**, including the
fractional-ending restart/tamper case. Ruff and strict mypy passed (128 files).
The rebuilt/reinstalled wheel's `item22-wheel-fractional` step gate passed with
`stopped` and a removed database. The fresh `item22-ha-fractional` live smoke
returned `execution_checks_passed`, `restored: true`, and source
`real API, demo devices`; its database was removed. The focused host seam test now
advances the executor clock by a microsecond and asserts refresh occurs immediately,
with paced/headless equivalence and no whole-second wait.

### Full evening completion — 2026-09-22

The required end-to-end command completed with exit 0:

```bash
HIRZ_DOGWOOD="$PWD/.tools/dogwood" UV_CACHE_DIR=/tmp/hirz-uv-cache \
  uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/item22-run19 \
  --output /tmp/hirz-item22-run19-report.json
```

Result: **`item22_execution_passed`; 47 passed checks; 30,637 valid signed rows**.
The report retains two explicit assertion deferrals for simulated constitution
activation and security/Link execution, plus the timeline's deferred tool calls.
Execution used validated seed policy **v7**; the separate simulated preview was
**v8**, without fabricated activation audit events.

The EV was **50% at 06:30** and remained at its separate 50% ceiling. The dishwasher
completed one cycle after its permitted overnight start. **93 visible affirmative
turns** covered **92 HVAC requests and one dishwasher request**, separately from
17:36 and 23:31 plan consent. Dad's linked-account attribution and normalized 23:00
kitchen constraint passed. Guest-room temperature was **72°F at 07:00**; all checked
comfort boundaries passed. Battery SoC returned to **55%**, preserving the original
**7.425 kWh** terminal obligation within the existing tolerance, with dispatch stopped.
All 151 superseded plans had their unstarted work cancelled; the sole remaining plan
was **completed**. No plan for tomorrow was created. Initial forecast assertions
passed without adding savings across revisions or changing historical backtest files.

The runner verified the database chain and exported file before dropping
`hirz_ha_smoke_9971ecbd8fbc4e749257fa5be89c5f32`. A separate `verify_file` invocation
again accepted all **30,637 rows**, deriving the trusted public-key fingerprint from
the configured signing key, independently of the export. The retained report and
`--output` copy matched. The artifact directory was `0700`; report, audit and public
key were `0600`, as was the separate report. PostgreSQL catalog reads confirmed
this database, the latest HA database and the latest installed-wheel database were
absent. Development remained on **`0005_execution_attempt`**; failed diagnostic
databases and available evidence remain retained.

The latest real-HA smoke (`item22-ha-fractional`) verified and restored the demo lamp
with **25 valid signed rows**. The latest installed-wheel step
(`item22-wheel-fractional`) stopped before 17:33 with **9 valid signed rows**.
Both exports independently verified against the configured key's fingerprint and
had the same private permissions. Corrupted-export rejection is covered by the
retained tamper probe and passing scenario tests described above.

Final regression evidence is the fractional-duration pass above: **1,221
service-free tests, 80.53% coverage, 108 PostgreSQL tests**, strict mypy over
128 files, Ruff, sdist/wheel build, installed-wheel CLI, Hourly planning, parents
observations and live HA restoration. A final format probe found one wrapping-only
change in `heuristic.py`; Ruff applied it, and the format gate is rerun after these
evidence/documentation edits. The workflow YAML and shell syntax were checked
locally; no push or remote CI run was performed. Friction review retained the actual
SciPy stdout diagnostic entry. Physical-plug/absence verification, MCP/UI, trust,
security execution, Link, authenticated activation and live Bedrock remain outside
this completion; no threat-model claim was changed.


## Phase 3 review batch A — 2026-09-22

Local mechanical review fixes only: adult-lineage resume, four earned threat-row
statuses, the Pipeline ownership invariant, the three existing approval paths and
structured constraint intake contract, and the combined Python coverage gate.
No roadmap status or Current phase change; no commit or remote CI run.

Environment: macOS, Python 3.12.13, pytest 9.1.1, pytest-cov 7.1.0,
Hypothesis 6.168.0, existing locked dependencies, pinned native `.tools/dogwood`,
and the existing local PostgreSQL service. Commands used
`UV_CACHE_DIR=/tmp/hirz-uv-cache`; service-free socket and PostgreSQL checks used
authorized local socket access. Integration fixtures created and dropped only
uniquely named disposable `hirz_test_*` databases; no development migration,
credential change, new dependency or migration file was introduced.

### Required checks, in order

| Command | Observed summary (exit 0) |
|---|---|
| `uv run pytest` | `1242 passed, 108 deselected in 115.27s (0:01:55)`; 10,177 statements, 1,981 missed, **80.53%** coverage |
| `uv run pytest -m integration --no-cov` | `108 passed, 1242 deselected in 140.26s (0:02:20)` |
| `uv run pytest tests/cedar_conformance` | `69 passed in 67.11s (0:01:07)`; native Dogwood, no skips |
| `uv run mypy hirz/ scripts/ alembic/` | `Success: no issues found in 128 source files` |

Logs are `/tmp/hirz-batch-a-pytest.log`,
`/tmp/hirz-batch-a-integration.log`, `/tmp/hirz-batch-a-conformance.log`, and
`/tmp/hirz-batch-a-mypy.log`. The conformance command used
`COVERAGE_FILE=/tmp/hirz-batch-a-conformance.coverage` to preserve the full
service-free run's `.coverage`; its subset coverage is not the combined gate.

The new 21 unit cases exercise all seven roles on app, Alexa and scheduler:
owner/adult/caregiver execute only on app; teen/child/guest/unknown receive
`DENY_CONSTITUTION` on every surface. `Constitution.role_mode` now uses the
existing `lineage` helper; the compiler already consumes that method, so no
compiler implementation change was needed. The native reserved-governance matrix
checks the same role/surface restriction and preserves linked-role pause permits.

User-facing compile check:
`HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz constitution compile
constitutions/quinn-home.yaml` exited 0. Output at
`/tmp/hirz-batch-a-compiled.json` reports `valid=True`, version 7,
`engine=dogwood-local`, `analysis=not analyzed: local mode`. The emitted resume
forbid/permit policies require `["owner", "adult", "caregiver"]` and
`f_requester_surface == "app"`; no policy was activated.

### Combined coverage, exercised locally

Both test runs are steps of the same `python-test` CI job and runner. The initial
`uv run pytest` above collected `--cov=hirz` through pytest addopts, exactly as CI
does. After the ordered checks, the following run appended integration coverage
to that unchanged baseline, then the standalone report enforced the threshold:

| Command | Observed summary (exit 0) |
|---|---|
| `uv run --locked pytest -m integration --cov=hirz --cov-append` | `108 passed, 1242 deselected in 173.47s (0:02:53)` |
| `uv run --locked coverage report --fail-under=80` | `TOTAL 10177 739 93%`; the required 80 percent combined gate passed |
| `uv run --locked coverage report --precision=2` | `TOTAL 10177 739 92.74%` |

Logs: `/tmp/hirz-batch-a-combined-integration.log` and
`/tmp/hirz-batch-a-coverage.log`. The default report rounds to whole percent;
**92.74%** is the same data displayed at two decimal places. The per-pytest
threshold was removed; service-free coverage collection remains enabled.
No artifact transfer, runner split, dependency change or coverage exclusion was
introduced. The Commands guidance is synchronized in CLAUDE/AGENTS, whose bodies
are now identical after their headings.

### Earned threat rows

Only these four rows changed, after reading their implementation and retained
evidence; none of the four needed to remain Planned:

- **Approval granted under conditions that no longer hold → Yes for local
  execution.** `Executor.run` calls fresh `Pipeline.redeem` before dispatching new
  actions; the existing sleeper regression changes scheduled HVAC execution into
  ASK with no dispatch attempt. Preauthorized bounded endings retain their original
  grant. [Item 19 evidence](#item-19--2026-09-21) earns the local-worker claim;
  AWS remains pending item 38.
- **Physical harm from an unsafe setpoint or an open lock → Partial.**
  `hirz/executor/contracts.py` rejects `target_f` outside 66–76 °F regardless of
  policy; it does not silently adjust the value. The existing 65/77 °F refusal
  tests ran in the full suite. [Item 19 evidence](#item-19--2026-09-21) supports
  only this setpoint protection. Maximum unlock and camera-off windows are not
  built (Phase 7, item 38a).
- **A twin that lies about the world → Partial.** The risk engine's `state_stale`
  increment, graph observation ages, executor/twin and HA read-back, and the
  registry's explicit scenario-only fallback enforce the narrowed claim.
  [Item 8](#item-8--complete-2026-09-18),
  [item 12](#item-12--complete-2026-09-19),
  [item 15](#item-15--partial-2026-09-20), [item 19](#item-19--2026-09-21), and
  [item 22](#item-22--2026-09-22) evidence covers twin and HA demo devices;
  no real device is verified. Physical-plug/absence verification remains pending;
  a twin read-back never verifies a real device.
- **A child, guest, or visitor speaking to a shared Echo → Partial.**
  The schema rejects `alexa` in security approval channels and
  `Pipeline.channel_allowed` requires app surface, `passkey_verified` and the
  matching verified action hash for security votes.
  [Item 7](#item-7--complete-2026-09-18) and
  [item 9](#item-9--complete-2026-09-18) evidence earns internal enforcement only.
  Public authentication and passkey verification at the AWS boundary remain
  pending; no voice identity or broader non-security restriction is claimed.

The ownership and tool-catalog changes document existing internal contracts and
item 23/25 obligations; no MCP server or tool was built. Protected Batch B/C paths,
canonical shapes, retained evidence/backtest data, `secrets/`, ROADMAP and Current
phase are unchanged. `git diff --check` passed. Friction review found no new
third-party misbehavior or workaround, so no friction entry was added.


### Final lint and formatting

After writing this entry and the two changelog lines,
`uv run ruff check . && uv run ruff format --check .` exited 0:

```text
All checks passed!
195 files already formatted
```

The same gate is repeated after this result append so formatting remains the
last validation after the evidence record.


## Phase 3 review batch B — 2026-09-22

### Step 0 — before implementation

Measured before any Batch B implementation edit using
`PYTHONPATH="$PWD" UV_CACHE_DIR=/tmp/hirz-uv-cache uv run python
/tmp/hirz_batch_b_measure.py before` (exit 0). The script connects with
`hirz.db.connect_database(read_env(Path(".env")), database=...)` and times
`Pipeline.usage("energy.optimize_cost", "2026-10-13")` with `perf_counter`,
including both database round trips, payload decoding and Python summation.
The household is `536fa8ee-854e-56ca-8c5d-5ba418e710a0`, local date 2026-10-13
(America/Chicago). Each measurement has 11 calls on one established connection:
first call reported separately, then median and maximum of 10 warm calls; these
small samples are not an item 26 p95 claim. Live snapshot is the single
`snapshot_sql() + " WHERE h.id = :household_id"` query including result transfer,
without `ContextSnapshot` validation. Connection setup is outside the timer.

Retained connections ran only SELECTs (including SQLAlchemy's connection
introspection). For each source, an admin connection ran
`CREATE DATABASE "<unique-copy>" TEMPLATE "<retained>"`; only that disposable copy
ran `REFRESH MATERIALIZED VIEW household_context`, 11 times in a transaction
(committed after timing). Each copy contained one household and was dropped
in `finally`; commit and create/drop times are outside refresh timing.
The first sandboxed connection attempt was refused with
`connection to server at "127.0.0.1", port 5432 failed: Operation not permitted`;
these measurements used authorized local socket access. No tool defect was found.

| Retained database | Audit rows | Measurement | First ms | Warm median ms | Warm max ms |
|---|---:|---|---:|---:|---:|
| `hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f` | 27,361 | Python usage() | 256.903 | 69.029 | 98.253 |
| `hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f` | 27,361 | Copy view refresh | 13.794 | 5.395 | 6.700 |
| `hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f` | 27,361 | Live snapshot query | 17.929 | 1.768 | 2.738 |
| `hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d` | 20,316 | Python usage() | 142.087 | 34.958 | 57.039 |
| `hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d` | 20,316 | Copy view refresh | 14.176 | 5.446 | 6.867 |
| `hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d` | 20,316 | Live snapshot query | 17.652 | 1.914 | 4.563 |

Exact baseline usage and all timing samples (ms), retained here before editing:

```json
[
  {
    "database": "hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f",
    "audit_rows": 27361,
    "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
    "date": "2026-10-13",
    "budget_dates": [
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-13",
        62
      ],
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-14",
        57
      ]
    ],
    "usage": {
      "first_ms": 256.903,
      "warm_median_ms": 69.029,
      "warm_max_ms": 98.253,
      "samples_ms": [
        256.903,
        59.546,
        56.945,
        94.281,
        73.384,
        81.662,
        98.253,
        62.229,
        64.674,
        81.276,
        61.267
      ]
    },
    "usage_decimal": "3.40351976067194484740209939",
    "live_snapshot": {
      "first_ms": 17.929,
      "warm_median_ms": 1.768,
      "warm_max_ms": 2.738,
      "samples_ms": [
        17.929,
        2.738,
        2.112,
        1.941,
        1.82,
        2.095,
        1.56,
        1.716,
        1.71,
        1.581,
        1.535
      ]
    },
    "copy_households": 1,
    "refresh": {
      "first_ms": 13.794,
      "warm_median_ms": 5.395,
      "warm_max_ms": 6.7,
      "samples_ms": [
        13.794,
        6.7,
        5.11,
        4.919,
        5.297,
        5.772,
        5.225,
        5.166,
        5.493,
        5.9,
        5.507
      ]
    },
    "disposable_copy_dropped": "hirz_batch_b_9bcb8495eb834f7bbabb0f21476800c9"
  },
  {
    "database": "hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d",
    "audit_rows": 20316,
    "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
    "date": "2026-10-13",
    "budget_dates": [
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-13",
        60
      ]
    ],
    "usage": {
      "first_ms": 142.087,
      "warm_median_ms": 34.958,
      "warm_max_ms": 57.039,
      "samples_ms": [
        142.087,
        57.039,
        34.227,
        35.601,
        33.883,
        30.907,
        31.257,
        48.346,
        40.504,
        34.315,
        39.756
      ]
    },
    "usage_decimal": "2.76760048821339642363973238",
    "live_snapshot": {
      "first_ms": 17.652,
      "warm_median_ms": 1.914,
      "warm_max_ms": 4.563,
      "samples_ms": [
        17.652,
        2.066,
        2.011,
        1.683,
        1.798,
        2.446,
        1.519,
        1.558,
        1.817,
        2.319,
        4.563
      ]
    },
    "copy_households": 1,
    "refresh": {
      "first_ms": 14.176,
      "warm_median_ms": 5.446,
      "warm_max_ms": 6.867,
      "samples_ms": [
        14.176,
        6.317,
        6.867,
        4.887,
        4.496,
        5.836,
        5.227,
        4.517,
        4.544,
        5.664,
        6.718
      ]
    },
    "disposable_copy_dropped": "hirz_batch_b_42b98bc8b1154abbbbece14237b73ca5"
  }
]
```

### Step 1 — SQL aggregation measured; stopped at the author’s threshold

Replaced Python payload scans with two household/class/local-date-filtered SQL
aggregates: committed grants joined on household/sequence, and
`RESERVATION_ADJUSTED` deltas. Each sum casts JSON text to PostgreSQL `numeric`
and coalesces an empty sum to zero. No index or migration was added.

Command: `PYTHONPATH="$PWD" UV_CACHE_DIR=/tmp/hirz-uv-cache uv run python
/tmp/hirz_batch_b_measure.py after` (exit 0, authorized local socket access).
Same retained databases, household, date, timing method and 11 samples as step 0;
only SELECTs were issued. Retained audit row counts remain 27,361 and 20,316.

| Retained database suffix | Usage before warm median ms | Usage after first ms | Usage after warm median ms | Usage after warm max ms |
|---|---:|---:|---:|---:|
| `856085c4b05b4ee9bd2e4676e8ea8f0f` | 69.029 | 49.562 | 27.439 | 116.046 |
| `2342c6fd95764fd4b77aacdb67c3411d` | 34.958 | 18.830 | 9.888 | 13.249 |

The larger database remains above the author's **10 ms** threshold, so Batch B
stopped before any index, migration, Step 2 implementation or verification gate.
An index migration requires author approval. No claim of completion or item 26
latency compliance is made.

The exact returned Decimals also differ at the tail: the old Python loop rounds
intermediate sums under Python's Decimal context, whereas PostgreSQL `numeric`
sums exactly before the final Python addition. This needs clarification against
“the same Decimal” before proceeding; no rounding workaround was introduced.

| Retained database suffix | Before Decimal | After Decimal |
|---|---|---|
| `856085c4b05b4ee9bd2e4676e8ea8f0f` | `3.40351976067194484740209939` | `3.403519760671944847402099409` |
| `2342c6fd95764fd4b77aacdb67c3411d` | `2.76760048821339642363973238` | `2.767600488213396423639732357` |

All after samples and the repeated live-snapshot measurements:

```json
[
  {
    "database": "hirz_ha_smoke_856085c4b05b4ee9bd2e4676e8ea8f0f",
    "audit_rows": 27361,
    "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
    "date": "2026-10-13",
    "budget_dates": [
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-13",
        62
      ],
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-14",
        57
      ]
    ],
    "usage": {
      "first_ms": 49.562,
      "warm_median_ms": 27.439,
      "warm_max_ms": 116.046,
      "samples_ms": [
        49.562,
        28.149,
        28.667,
        26.354,
        27.722,
        30.842,
        27.156,
        26.178,
        26.374,
        25.774,
        116.046
      ]
    },
    "usage_decimal": "3.403519760671944847402099409",
    "live_snapshot": {
      "first_ms": 27.519,
      "warm_median_ms": 3.687,
      "warm_max_ms": 8.767,
      "samples_ms": [
        27.519,
        7.501,
        8.767,
        3.407,
        2.7,
        7.165,
        6.78,
        2.556,
        2.501,
        3.967,
        3.084
      ]
    }
  },
  {
    "database": "hirz_ha_smoke_2342c6fd95764fd4b77aacdb67c3411d",
    "audit_rows": 20316,
    "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
    "date": "2026-10-13",
    "budget_dates": [
      [
        "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
        "2026-10-13",
        60
      ]
    ],
    "usage": {
      "first_ms": 18.83,
      "warm_median_ms": 9.888,
      "warm_max_ms": 13.249,
      "samples_ms": [
        18.83,
        10.416,
        13.249,
        10.193,
        9.479,
        11.197,
        9.557,
        9.26,
        10.154,
        9.621,
        9.549
      ]
    },
    "usage_decimal": "2.767600488213396423639732357",
    "live_snapshot": {
      "first_ms": 8.897,
      "warm_median_ms": 2.084,
      "warm_max_ms": 3.681,
      "samples_ms": [
        8.897,
        3.681,
        2.297,
        1.921,
        1.887,
        3.279,
        1.96,
        2.208,
        2.365,
        1.775,
        1.704
      ]
    }
  }
]
```

Outstanding at the explicit stop: the negative-adjustment unit test; per-household
lock, concurrency tests and architecture/comment edits; and all ordered gates:

```bash
uv run pytest
uv run pytest -m integration --cov=hirz --cov-append
uv run --locked coverage report --fail-under=80
uv run pytest tests/cedar_conformance
uv run mypy hirz/ scripts/ alembic/
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/batch-b-evening \
  --output /tmp/hirz-batch-b-report.json
uv run ruff check . && uv run ruff format --check .
```

These gates were **not run**, and there is no Batch B evening wall-clock time,
row count, signed export or artifact directory yet. The requested destination is
`secrets/scenario-runs/batch-b-evening`; the command above corrects the supplied
`--articts-dir` typo to the existing CLI's `--artifacts-dir`. Run19's 30,637 rows
remain the comparison baseline, not a new result. The only formatting command
run before the stop was `uv run ruff format hirz/pipeline/service.py`:
`1 file reformatted`, exit 0. No assertions or scenario files were changed.

Existing checkout changes were preserved. Batch B touched only
`hirz/pipeline/service.py`, this evidence entry, and the linked Changed line in
`CHANGELOG.md`. No changes to roadmap status, Current phase, ADRs, dependencies,
retained evidence, backtest data, retained databases or `secrets/`. The friction
log was checked: the sandbox's local-socket restriction is not third-party tool
misbehavior, so no new friction entry was earned. No commit was made.

### Author clarification and resumed work — 2026-09-22

The author answered **“no index, accept exact”**: retain SQL numeric totals, add
no index or migration, and proceed despite the measured usage above 10 ms. The
preceding stop remains historical evidence. Step 2 now uses advisory namespace
`1` plus the signed first 32 UUID bits; same-home writes serialize and rare
32-bit collisions can only add serialization. The two-key advisory space is
separate from worker session locks. Whole-view refresh remains unchanged in the
transaction, with the measured one-household cost and item 38c scaling ceiling
in the existing ponytail comment. No ADR amendment is needed for this explicit
batch instruction.

### Resumed verification — all functional gates passed

Environment: existing macOS checkout, Python 3.12.13, pytest 9.1.1, existing
locked dependencies, pinned native `.tools/dogwood`, and local PostgreSQL.
All `uv` commands used `UV_CACHE_DIR=/tmp/hirz-uv-cache`. Service-free loopback
and PostgreSQL checks ran with authorized local socket access. Integration
fixtures created/dropped only disposable `hirz_test_*` databases. Conformance
used `COVERAGE_FILE=/tmp/hirz-batch-b-conformance.coverage` so its subset run did
not overwrite the combined coverage gate.

Commands were run in the required order, each with exit 0:

| Command | Observed summary |
|---|---|
| `uv run pytest` | `1243 passed, 110 deselected in 115.87s (0:01:55)`; `TOTAL 10178 1977 81%` |
| `uv run pytest -m integration --cov=hirz --cov-append` | `110 passed, 1243 deselected in 172.02s (0:02:52)`; `TOTAL 10178 735 93%` |
| `uv run --locked coverage report --fail-under=80` | `TOTAL 10178 735 93%` |
| `uv run pytest tests/cedar_conformance` | `69 passed in 67.37s (0:01:07)`; no skips |
| `uv run mypy hirz/ scripts/ alembic/` | `Success: no issues found in 128 source files` |

Logs: `/tmp/hirz-batch-b-pytest.log`, `/tmp/hirz-batch-b-integration.log`,
`/tmp/hirz-batch-b-coverage.log`, `/tmp/hirz-batch-b-conformance.log`, and
`/tmp/hirz-batch-b-mypy.log`. Pre-gate formatting used
`uv run ruff format hirz/graph/repository.py tests/unit/test_pipeline.py
 tests/integration/test_pipeline_database.py`: `1 file reformatted, 2 files left
unchanged`. Final repository-wide Ruff checks follow the records.

The added unit test invokes the real `Pipeline.usage` with mocked aggregate
results `Decimal("0.30")` and `Decimal("-0.10")`, checks an exact `Decimal("0.20")`
net and both compiled queries' household/class/date scope, numeric sums, grant
join and adjustment event filter. Existing budget tests were not changed and
passed against PostgreSQL. Two new integration tests use distinct connections
and Pipelines: different UUIDs (including a negative signed 32-bit key) hold
write contexts simultaneously; the same-household test observes the second
backend in `pg_blocking_pids`, proves it has not entered, then proves it enters
after the first transaction exits. These empty write contexts isolate advisory
lock behavior; they do not claim concurrent whole-view refreshes.

### Full evening and signed export

The timed user-facing command (corrected CLI flag spelling) was:

```bash
/usr/bin/time -p env HIRZ_DOGWOOD="$PWD/.tools/dogwood" \
  UV_CACHE_DIR=/tmp/hirz-uv-cache \
  uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/batch-b-evening \
  --output /tmp/hirz-batch-b-report.json \
  > /tmp/hirz-batch-b-evening.stdout.log \
  2> /tmp/hirz-batch-b-evening.stderr.log
```

Exit 0: **`item22_execution_passed`; 47 passed checks; zero failed checks**.
Time summary: `real 1159.21`, `user 600.31`, `sys 95.16` seconds. Wall-clock time
includes CLI startup, disposable database setup, full execution, verification,
export and cleanup. No baseline run19 wall-clock time was recorded here, so no
end-to-end speedup is claimed.

| Run | Signed audit rows | Wall-clock seconds |
|---|---:|---:|
| Item 22 run19 (retained baseline) | 30,637 | Not recorded in its evidence entry |
| Batch B evening | 29,624 | 1,159.21 |

The 1,013-row difference is observed, not attributed to a refresh-cadence change;
Batch C files and all scenario files remain unchanged. All eight `initial_summary`
fields compare exactly equal to run19's retained report, beyond the unchanged
scenario range assertions:

```json
{
  "estimated_savings_usd": 0.2797130920136214,
  "peak_kwh_avoided": -4.3421521040837296e-05,
  "grid_kwh": 49.202804672178694,
  "solar_kwh": 0.15154277752369996,
  "exported_kwh": 2.1094237467877974e-15,
  "electricity_usd": 3.3258035332563503,
  "wear_usd": 0.09367377528544629,
  "comfort_violations_minutes": 0.0
}
```

Artifacts: `secrets/scenario-runs/batch-b-evening/` contains `report.json`,
`audit.json`, and `public-key.pem`. The directory is `0700`; all three files and
`/tmp/hirz-batch-b-report.json` are `0600`. Parsed report copies compare equal.
The runner verified both the database chain and exported file. A separate
`uv run python` invocation again called `hirz.audit.verify_file` on `audit.json`,
with expected household `536fa8ee-854e-56ca-8c5d-5ba418e710a0` and a trusted
fingerprint derived from `signing_key(read_env(Path(".env"))).public_key()`.
It returned **`status: valid`, `checked_count: 29624`, `start_seq: 1`,
`end_seq: 29624`, `failure_seq: null`, `reason: null`**, retaining the local-mode
unanchored/completeness limitations. The same check asserted the scenario status,
47 checks, exact forecast equality and matching report copy. Its redacted summary
is `/tmp/hirz-batch-b-final-summary.json`; no private key was printed or written.

Read-only progress probes (`SELECT count(*), max(created_at) FROM audit_log` on
the active disposable database) observed 10,343 / 17,509 / 21,128 / 23,963 /
26,404 / 28,358 rows at local times 21:50 / 00:36 / 02:01 / 03:16 / 04:25 / 05:45,
respectively. The active database name was discovered with a SELECT from
`pg_stat_activity`; no writes were performed by those probes.

The runner printed `disposable_database=dropped; development_database=unchanged`.
A separate read-only `uv run python` catalog check using
`SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = :name)` confirmed
`hirz_ha_smoke_d3f2001ef9214f0fa227c1f355da9d2f` is absent, and
`SELECT version_num FROM alembic_version` returned `0005_execution_attempt` for
development. Retained failed-run databases and run19 artifacts were not modified.

### Scope and final records

No index or migration was added, per the author's clarification. Usage remains
above 10 ms on the larger retained database; whole-view refresh still blocks view
readers and serializes refreshing writers, with multi-household scale deferred to
the explicitly requested item 38c remeasurement. This is not an item 26 p95 pass.
No roadmap, Current phase, ADR, canonical object, dependency, refresh cadence or
scenario change was made. Only the requested Batch B artifact directory was
created under `secrets/`. Existing unrelated checkout edits were preserved.
No commit was made. `git diff --check` passed. Third-party tooling was checked for
new friction: no new defect or workaround earned an entry.

Batch B's changed tracked files and their scope:

- `hirz/pipeline/service.py`: Step 1 exact numeric SQL aggregates.
- `tests/unit/test_pipeline.py`: Step 1 negative-adjustment/net usage regression.
- `hirz/graph/repository.py`: Step 2 household advisory key and measured refresh ceiling.
- `tests/integration/test_pipeline_database.py`: Step 2 different/same-household lock tests.
- `ARCHITECTURE.md`: Step 2 lock contract and retained whole-view serialization.
- `docs/verification-log.md`: Step 0/1 measurements and Step 1/2 verification evidence.
- `CHANGELOG.md`: One Changed line linking this Batch B evidence.

Final ordered lint/format command:

```bash
uv run ruff check . && uv run ruff format --check .
```

Exit 0: **`All checks passed!`**, **`195 files already formatted`**. The same
command is repeated as the last verification operation after appending these
results, so it also covers the finished records.


## Phase 3 review batch C — 2026-09-22

**Stopped at the author's guest-room ASK limit; Batch C is not fully verified.**
The evening passed all 47 existing checks with an unchanged initial forecast, but
produced **9 guest-room asks**, exceeding the explicit maximum of five. No tuning,
approval transfer, planner/coordinator change or scenario-assertion change followed.
Hourly and the refresh smoke were not run after this stop.

### Contract written before code

The [Change-based freshness amendment](./adr/ADR-005-deterministic-planner.md#change-based-freshness--2026-09-22-author-approved)
was appended after “Exact bounded durations” before any Batch C implementation edit.
It defines freshness by complete runtime inputs, an idle job and unchanged inputs;
keeps per-tick observations/feeds and the 300-second observation bound; and rejects
timer replans, approval transfer and suppression of the household sleep rule.
`ARCHITECTURE.md` §5.4 now reflects that contract. Existing `accepted_at` storage,
approval binding, PlanService, planner, coordinator and scenario YAML are unchanged.
The host retains its five-minute observation poll and removes only the acceptance-age
wake-up and its now-unused query. `docs/development.md` has no plan-age-trigger
procedure, so it was not changed. Current phase is unchanged.

### Commands and gate results

Environment: existing macOS checkout, Python 3.12.13, pytest 9.1.1, existing locked
dependencies and pinned native `.tools/dogwood`. All uv commands used
`UV_CACHE_DIR=/tmp/hirz-uv-cache`. Service-free loopback tests and PostgreSQL checks
used authorized local socket access. Tests created/dropped disposable databases;
no development migration, dependency or credential change was performed.

Initial ordered attempt:

| Command | Observed summary |
|---|---|
| `uv run pytest` | Exit 0: `1243 passed, 111 deselected in 134.22s (0:02:14)`; `TOTAL 10173 1977 81%` |
| `uv run pytest -m integration --cov=hirz --cov-append` | Exit 1: `1 failed, 110 passed, 1243 deselected in 200.65s (0:03:20)` |

The new aged-plan test had already proved `fresh()` and an `approved` read, but its
initial thermal fixture's unbound HVAC action returned `DENY_RISK`, failing the
expected verified execution. The existing fixture had relied on refresh to bind
the replacement's zone. The test now reuses the existing synthetic light-plan and
runtime helpers, with an action due at six minutes and another at ten minutes.
Later pending work also avoids conflating refresh with the executor's normal
`PLAN_REVISED` status transition after all scheduled work finishes. The real
Pipeline and executor remain in use; no risk or approval check is mocked away.
Production code was not changed to accommodate the failed fixture.

The ordered gates restarted after that fixture correction:

| Command | Observed summary |
|---|---|
| `uv run pytest` | Exit 0: `1243 passed, 111 deselected in 134.55s (0:02:14)`; `TOTAL 10173 1977 81%` |
| `uv run pytest -m integration --cov=hirz --cov-append` | Exit 0: `111 passed, 1243 deselected, 1 warning in 197.65s (0:03:17)`; `TOTAL 10173 735 93%` |
| `uv run --locked coverage report --fail-under=80` | Exit 0: `TOTAL 10173 735 93%` |
| `uv run mypy hirz/ scripts/ alembic/` | Exit 0: `Success: no issues found in 128 source files` |

The warning was in the new fixture, not production:
`PydanticSerializationUnexpectedValue(Expected tuple[str, ...] ...
field_name='actions' ... input_type=list)`. The fixture now supplies the canonical
tuple. The focused check
`uv run pytest tests/integration/test_refresh_database.py -m integration --no-cov
-k unchanged_old_plan -W error` exited 0:
**`1 passed, 10 deselected in 3.16s`**, with warnings treated as errors.
No production code changed after the ordered test/type gates, and this focused
check did not overwrite combined coverage.

The unit regression now checks unchanged inputs at five minutes and twelve hours,
non-idle jobs, missing inputs, changed fingerprints and first-fingerprint saving.
The integration regressions prove that an unchanged plan remains approved and its
due action verifies after six minutes with no new `PLAN_REFRESH` or `PLAN_REVISED`
row since approval, and that a changed presence fingerprint still queues a refresh,
holds unstarted work, yields a refreshing read and publishes under inherited consent.
The executor test uses the worker's existing separate-observation-poll mode, with
fresh observations supplied through audited ingestion and no refresh solver run.

Logs: `/tmp/hirz-batch-c-pytest.log`, `/tmp/hirz-batch-c-integration.log`,
`/tmp/hirz-batch-c-pytest-rerun.log`, `/tmp/hirz-batch-c-integration-rerun.log`,
`/tmp/hirz-batch-c-coverage.log`, `/tmp/hirz-batch-c-mypy.log`, and
`/tmp/hirz-batch-c-fixture-check.log`.

Pre-gate formatting commands were
`uv run ruff format hirz/executor/refresh.py hirz/twin/execution.py
 tests/unit/test_refresh.py tests/integration/test_refresh_database.py`
(`1 file reformatted, 3 files left unchanged`) and, after correcting the fixture,
`uv run ruff format tests/integration/test_refresh_database.py`
(`1 file reformatted`). Final repository-wide Ruff checks follow the records.

### Evening run and explicit stop

```bash
/usr/bin/time -p env HIRZ_DOGWOOD="$PWD/.tools/dogwood" \
  UV_CACHE_DIR=/tmp/hirz-uv-cache \
  uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/batch-c-evening \
  --output /tmp/hirz-batch-c-report.json \
  > /tmp/hirz-batch-c-evening.stdout.log \
  2> /tmp/hirz-batch-c-evening.stderr.log
```

Exit 0: **`item22_execution_passed`; 47 passed checks; zero failed checks**.
Timing: `real 276.44`, `user 133.11`, `sys 21.79` seconds. EV SoC at 06:30
America/Chicago was `0.4999999999747853`, passing the unchanged 50% assertion;
`battery_terminal_preserved` passed. Every `initial_summary` field compares
exactly equal to run19:

```json
{
  "estimated_savings_usd": 0.2797130920136214,
  "peak_kwh_avoided": -4.3421521040837296e-05,
  "grid_kwh": 49.202804672178694,
  "solar_kwh": 0.15154277752369996,
  "exported_kwh": 2.1094237467877974e-15,
  "electricity_usd": 3.3258035332563503,
  "wear_usd": 0.09367377528544629,
  "comfort_violations_minutes": 0.0
}
```

Comparison derived from each signed export (not a count of all PLAN_REVISED rows):

| Metric | Item 22 run19 | Batch C evening |
|---|---:|---:|
| Plans | 152 | 22 |
| Superseded plans | 151 | 21 |
| Signed audit rows | 30,637 | 6,793 |
| ASK_CONSTITUTION rows, all classes | 93 | 10 |
| Guest-room HVAC asks | 92 | 9 |

`uv run python /tmp/hirz_batch_c_compare.py` wrote
`/tmp/hirz-batch-c-comparison.json` and `/tmp/hirz-batch-c-comparison.log`.
It returned exit 1 at the intentional stop assertion:
**`AssertionError: Guest-room asks exceed five; stop without tuning.`**
Its forecast equality check passed first. Plan counts use unique `mutation.plan`
IDs from PLAN_CREATED/PLAN_REVISED, and superseded counts use their distinct
`supersedes` references. ASK_CONSTITUTION rows are joined by action ID to the
audited `mutation.actions`, filtering `energy.hvac_adjust` and `hvac.guest_room`.
The baseline parser confirms all 92 guest-room asks before comparing Batch C.
An initial read-only export-shape probe raised `KeyError: 'transition'` because
PLAN_REFRESH also includes per-action status rows; the final analyzer distinguishes
those from job transitions and replays partial job updates by lineage. This was
an analysis-script correction, not third-party friction.

### Every guest-room asked action at the stop

Times below are the exact exported `scheduled_for` values, in UTC. Microseconds
are retained because separate asks can occur at almost the same instant.

| Audit seq | Action ID | scheduled_for | target_f |
|---:|---|---|---:|
| 4100 | `act_f69623f547a6f733c23304a7437e4b3f2aefba25a3b1f7e42d7337fb0001d408` | `2026-10-14T04:36:00Z` | 72.0 |
| 4416 | `act_c100b12698d158751dfaaf70c0f05d1cfdee3ded75d46114f01f22bba0934684` | `2026-10-14T05:00:00.000001Z` | 72.0 |
| 4777 | `act_c74f08339a71ef602fb46daf675bd89e95dfa995f6f55e7334ab9ae0e54e3343` | `2026-10-14T05:00:00.000007Z` | 72.0 |
| 5287 | `act_45056bb6dc3005394059d653d1af3a233883fbfd2a80919cd7b615a907986e45` | `2026-10-14T06:50:00.000002Z` | 72.0 |
| 5775 | `act_ad2f4b06581f6d9a801146c50df93514c18ec7fc403361a2ab99534ce0901672` | `2026-10-14T08:40:00.000003Z` | 72.0 |
| 5937 | `act_cca5dc9b87d00e3f813ef5e4f41b57dfe3493dd7492881c006f7037e8090e426` | `2026-10-14T08:40:00.000007Z` | 72.0 |
| 6391 | `act_22f9fbbc9a93f53817249dff79b6cca86ba927d0c18f0ee490ac384ba238f653` | `2026-10-14T10:45:00.000001Z` | 72.0 |
| 6529 | `act_c6cb2b0f58ba37067625ba37eabe1ce3e42bdd6b50eda12402f85ff63a9eff50` | `2026-10-14T11:00:00Z` | 72.0 |
| 6678 | `act_1f79ea21b7d6261b896e75497697f431c77e1995f5b61bde1ae484c54d668d40` | `2026-10-14T11:30:00.000001Z` | 72.0 |

All nine targets are 72°F. No planner quantization diagnosis or tuning is claimed;
that is the author's next scope decision. Approval transfer was deliberately not
implemented: the approved contract makes replacements depend on real changes, and
a real change should ask again. The sleep rule and all scenario assertions remain
unchanged.

### Every queued refresh and its recorded reason

These are all 26 durable queued transitions, including coalesced requests; they
are not 26 successful replacement publications. Reasons are read from replayed
job transitions, not inferred from narrative or action timing. Codes below quote
the complete existing reason strings:

- **C**: `Member constraint or manual hold changed`
- **F**: `Household inputs, policy, control state or prediction changed.`
- **E**: `The execution window expired.`

| Audit seq | Time (UTC) | Generation | Source plan ID | Recorded reasons |
|---:|---|---:|---|---|
| 31 | `2026-10-13T22:35:00.000000Z` | 1 | `plan_011ed2df83e82de4505e209ace9b8dc65ba342691100534ab682635213636ddf` | C |
| 155 | `2026-10-13T22:35:00.000000Z` | 2 | `plan_011ed2df83e82de4505e209ace9b8dc65ba342691100534ab682635213636ddf` | C + F |
| 490 | `2026-10-13T22:36:00.000000Z` | 3 | `plan_e3dc51ee2e7d563d4a9539ef766e626177b8b922c62c625bdaf6b2cfab339b71` | F |
| 806 | `2026-10-13T22:45:00.000001Z` | 4 | `plan_49afa1838ac5e459c7eea95631a68c456b17e12986a677ea37d6f773865e027a` | F |
| 911 | `2026-10-13T22:55:00.000002Z` | 5 | `plan_49afa1838ac5e459c7eea95631a68c456b17e12986a677ea37d6f773865e027a` | F |
| 1056 | `2026-10-13T23:30:00.000002Z` | 6 | `plan_49afa1838ac5e459c7eea95631a68c456b17e12986a677ea37d6f773865e027a` | F |
| 1358 | `2026-10-13T23:45:00.000001Z` | 7 | `plan_7ffa63838414394eb88cc6b2c3732231d899c285cb6efcb898ddfe3b47c47e09` | F |
| 1675 | `2026-10-14T00:00:00.000002Z` | 8 | `plan_456663862394945cacdb182270cb8017457312d4eddb66f95871bbe4bf45b9dd` | F |
| 2001 | `2026-10-14T00:10:00.000000Z` | 9 | `plan_4ba6fc7915a8e332e7a474feb7e4d7f02283b977a9849c8b42cd4f127a215e13` | F |
| 2245 | `2026-10-14T00:15:00.000000Z` | 10 | `plan_9e8d7d259c035c17908641a815961d639f1e9b96bba9cb258a876894baacd253` | F |
| 2718 | `2026-10-14T02:00:00.000000Z` | 11 | `plan_39fc77dc8c41b18216e2670095da1ba477ba63fb1015eabe76ce6d0a95fb0a3d` | F |
| 3171 | `2026-10-14T03:40:00.000000Z` | 12 | `plan_48ef8be2cd25dedefe664be0f327168a23b17d6876f63bffcb3bc355072c5d21` | C |
| 3222 | `2026-10-14T03:40:00.000000Z` | 13 | `plan_48ef8be2cd25dedefe664be0f327168a23b17d6876f63bffcb3bc355072c5d21` | C + F |
| 3364 | `2026-10-14T04:05:00.000000Z` | 14 | `plan_2c53f42c8c33a2f89eb8e6c5f74180d4dbe56654fc32770f90979ac5f158ed6c` | F |
| 3503 | `2026-10-14T04:20:00.000000Z` | 15 | `plan_a574d057e0a18d8ea535dc0c51e0aa6e3ce1c122abc4730a9332d4b6e783bd3e` | F |
| 3638 | `2026-10-14T04:30:00.000000Z` | 16 | `plan_0f3b4dca0c7b98d6a0b865e3e66a19aaeec98888ccc3d6fd4fc767d330c71d10` | F |
| 3870 | `2026-10-14T04:31:00.000000Z` | 17 | `plan_92871bcb1fe4543276b3f14a218c24f851d585f4c0f34a48538c55941157b284` | E |
| 3922 | `2026-10-14T04:36:00.000000Z` | 18 | `plan_92871bcb1fe4543276b3f14a218c24f851d585f4c0f34a48538c55941157b284` | E + F |
| 4272 | `2026-10-14T05:00:00.000001Z` | 19 | `plan_194415af5c213b7861f1259adfd09824221c8b7e05be166ec19831417f4da92a` | F |
| 4623 | `2026-10-14T05:00:00.000007Z` | 20 | `plan_d3543c27326028c73ea1c90525010319c84d7bfe42df2d0fe8e5764591f0e879` | F |
| 5166 | `2026-10-14T06:50:00.000002Z` | 21 | `plan_25562fb1296d7468873206a2fdb11123d8c8fee3c79ff8468798afef00d91bd5` | F |
| 5686 | `2026-10-14T08:40:00.000003Z` | 22 | `plan_b442f660fc5a5f78dec24ee4c037bfa39d48940f3362e549e0c19f48325f7b8f` | F |
| 5844 | `2026-10-14T08:40:00.000007Z` | 23 | `plan_db215a760c686278ddd3763ed5481c7006e18063f7245991ed974e8047ce3543` | F |
| 6344 | `2026-10-14T10:45:00.000001Z` | 24 | `plan_76efc7bb5729c399f98593b882c0535c66fa58b59514f581dc341892076a1451` | F |
| 6483 | `2026-10-14T11:00:00.000000Z` | 25 | `plan_121e5a245c73bb077724abdce7aaa563e0b78ff0d19c57ee3a66a09d7d3ea5fb` | F |
| 6648 | `2026-10-14T11:30:00.000001Z` | 26 | `plan_2d19d2a4644aa8221546415cc7784bceb790ba9fda743b305eb74feef2b2b45d` | F |

No accepted-plan-age reason remains. The broad F reason is reported verbatim;
this batch does not claim which underlying fingerprint field caused each one.

### Retained artifacts and verification still owed

Artifacts are only in `secrets/scenario-runs/batch-c-evening/`: `report.json`,
`audit.json`, and `public-key.pem`. The directory is `0700`; each file and the
separate `/tmp/hirz-batch-c-report.json` are `0600`. Parsed report copies match.
The scenario verified both its database chain and exported file before printing
`disposable_database=dropped; development_database=unchanged` for
`hirz_ha_smoke_e7c9f219eece49cbad40415dcb616561`.

After the ASK stop, a read-only `uv run python` evidence check independently called
`hirz.audit.verify_file` using the expected household and a trusted public-key
fingerprint derived from `signing_key(read_env(Path(".env"))).public_key()`.
It again returned **`status: valid`, `checked_count: 6793`, `start_seq: 1`,
`end_seq: 6793`, `failure_seq: null`, `reason: null`**; local-mode anchoring and
completeness limitations remain. Its result and the EV/terminal checks are in
`/tmp/hirz-batch-c-evidence-summary.json`. No private key was printed or written.

The sole read-only progress probe used SELECTs from `pg_stat_activity` and
`SELECT count(*), max(created_at) FROM audit_log` on the active disposable database;
it observed 6,462 rows at 05:50 local time. Retained databases and run19 evidence
were not modified.

The following required functional gates remain **not run**, because the author
explicitly required stopping when guest-room asks exceed five:

```bash
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening-hourly.yaml --headless --assert \
  --output /tmp/hirz-batch-c-hourly.json
uv run python scripts/smoke_refresh.py \
  --audit-output /tmp/hirz-batch-c-refresh-audit.json
```

No migration, dependency, canonical-shape change, approval transfer, planner tuning,
coordinator edit, scenario edit, backtest change or extra `secrets/` output was made.
Existing checkout changes were preserved. No new third-party defect or workaround
earned a friction-log entry. `git diff --check` passed. No commit was made.

Batch C's tracked changes:

- `docs/adr/ADR-005-deterministic-planner.md`: Step 1 contract, appended before code.
- `ARCHITECTURE.md`: Step 1 freshness sentences and observation-age distinction.
- `hirz/executor/refresh.py`: Step 2 removal of plan-age detection/freshness gates.
- `hirz/twin/execution.py`: Step 2 removal of the acceptance-age wake-up only.
- `tests/unit/test_refresh.py`: Step 2 change-based freshness regression.
- `tests/integration/test_refresh_database.py`: Step 2 aged-plan execution/read and changed-fingerprint hold/inherited-consent checks.
- `docs/verification-log.md`: Step 4 commands, comparison, every refresh reason and ASK-limit stop.
- `ROADMAP.md`: Step 4 single appended item 19a sentence, with verification stop explicit.
- `CHANGELOG.md`: Step 4 one Changed line linking the contract and this evidence.

### Final record and formatting gate

After writing the records, `uv run ruff check . && uv run ruff format --check .`
returned exit 0:

```text
All checks passed!
195 files already formatted
```

The same command was run last again after recording this output. This is record
hygiene only; Hourly and the refresh smoke remain unrun at the explicit ASK stop.


## Phase 3 review batch C2 — 2026-09-22

### Part 1 — audit-only classification, accepted by the author

Source: `secrets/scenario-runs/batch-c-evening/audit.json` only; no retained
PostgreSQL database was opened. For each queued PLAN_REFRESH transition carrying
a deviation, the preceding PLAN_CREATED/PLAN_REVISED mutation for that source
plan supplied validated RuntimeInputs. Every deviation value was matched to its
preceding OBSERVATIONS_RECORDED sample, and `hirz.executor.runtime.predicted`
was called at that observation's instant. Its original forecast behavior remains
available without the new `applied` argument. Reproduction scripts are
`/tmp/hirz_c2_investigate.py` and `/tmp/hirz_c2_details.py`.

There were **12 queued transitions carrying deviations, 17 asset samples and
18 numeric threshold exceedances: 12 power, five temperature and one SoC**.
The twelve queue-to-source-mutation joins were `490→283`,
`806/911/1056→588`, `1675→1442`, `3364→3284`, `3503→3431`, `3638→3571`,
`3922→3705`, `4272→3984`, `5686→5210`, and `6344→5880`. Predictions below are
rounded for display; strict comparisons used the full values. Times are UTC,
2026-10-13 before midnight and 2026-10-14 afterward. Repeated entries include
previous deviations carried into a later queue.

| Queue seq | Observation time UTC | Asset | Field | Observed | Predicted | Strict threshold | Cause |
|---:|---|---|---|---:|---:|---:|---|
| 490 | 22:36:00 | EV | power_kw | 0 | 7.4 | >0.25 | Prediction starts at 22:35; consent arrives at 22:36 before dispatch. |
| 490 | 22:36:00 | Battery | power_kw | 0 | 4.999897 | >0.25 | Same consent gap; battery opening is undispatched. |
| 806 | 22:45:00.000001 | EV | power_kw | 0 | 7.4 | >0.25 | Verified bounded stop precedes the next undispatched opening. |
| 911 | 22:55:00.000002 | EV | power_kw | 0 | 7.4 | >0.25 | Earlier deviation persists while refresh is blocked and charging remains held. |
| 911 | 22:55:00.000002 | Guest HVAC | temp_f | 67.9483 | 69.001921 | >1°F | Prediction includes a held 22:45 warming command. |
| 1056 | 23:30:00.000002 | EV | power_kw | 0 | 7.4 | >0.25 | Prediction continues through held charging actions. |
| 1056 | 23:30:00.000002 | EV | soc | 0.3536 | 0.390942 | >0.02 | Accumulated predicted energy from undispatched actions. |
| 1056 | 23:30:00.000002 | Battery | power_kw | 0 | 5 | >0.25 | Earlier bounded operation ended; predicted 23:30 opening remains held. |
| 1056 | 23:30:00.000002 | Guest HVAC | temp_f | 67.9483 | 72 | >1°F | Later warming commands never dispatched. |
| 1675 | 00:00:00.000002 | EV | power_kw | 0 | 7.4 | >0.25 | Midnight stop precedes the next opening; tariff also changes. |
| 3364 | 04:05:00 | Living HVAC | temp_f | 71.7362 | 70.441667 | >1°F | Unapproved plan predicts cooling; genuine sleep/room change overlaps. |
| 3503 | 04:20:00 | Living HVAC | temp_f | 71.7085 | 70.590153 | >1°F | Replacement lacks consent; cooling never dispatched. |
| 3638 | 04:30:00 | Living HVAC | temp_f | 71.6902 | 70.5895 | >1°F | Another unapproved replacement predicts undispatched cooling. |
| 3922 | 04:36:00 | EV | power_kw | 0 | 7.4 | >0.25 | Expired battery opening held the plan's charging work. |
| 3922 | 04:36:00 | Dishwasher | power_kw | 0 | 0.685714 | >0.25 | Same hold prevented the predicted cycle start. |
| 4272 | 05:00:00.000001 | EV | power_kw | 0 | 7.4 | >0.25 | Verified bounded stop precedes the next undispatched opening. |
| 5686 | 08:40:00.000003 | EV | power_kw | 7.4 | 0 | >0.25 | Prediction reaches the charge ceiling just before actual delivery. |
| 6344 | 10:45:00.000001 | Battery | power_kw | 0 | -5 | >0.25 | Verified bounded stop precedes the next undispatched opening. |

Causes group into prediction before dispatch (including consent and next-slot
openings), further drift manufactured by held work, and expected physical
transitions. At 22:45 and 22:55 the refresh failures were battery-export/comparison
validation blocks. At 08:40 the subsequently audited RuntimeInputs record actual
SoC `0.4546133333081187` against the governing limit `0.4546133333333333`: about
one microsecond of charge remained. Both round to 0.4546; power still differs by
7.4 kW. Seq 5844 queues again when that deviation disappears. The precise upstream
split between floating-point arithmetic and accumulated dispatch offsets was not
separately established. No other numeric deviation remains causally unexplained.

Dishwasher lifecycle triggers are separate: seq 4623 at 05:00:00.000007 sees
`on=true` after the start verified at seq 4620, 05:00:00.000005. The start has empty
parameters, so the old ownership check cannot match it. Seq 5166 at
06:50:00.000002 sees `on=false` after the known 105-minute cycle. Prediction agrees
with both observations, but the raw `on` sample still changes.

The period-name transitions are seq 1675 (`mid_day_peak→evening` at 00:00),
2718 (`evening→overnight` at 02:00), and 6483 (`overnight→morning` at 11:00).
`fingerprint()` copies `price_band` into samples; `poll_inputs()` independently
hashes configured price/weather/calendar content over the stable forecast origin.
The 22:35 workload already contains prices 0.26551, 0.10194, 0.06739 and 0.09243
USD/kWh for those future intervals. Seq 1675 also carries an EV deviation, so
removing the tariff field alone would not eliminate that queue.

The window-crossing queues are seq 1358 at 23:45:00.000001, 2245 at 00:15:00,
and 6648 at 11:30:00.000001. Their clock-dependent source is the `boundaries`
digest of row IDs and start/end Booleans. Constraint/calendar row contents stay
in `graph`. Verified battery/EV stops coincide with the first/last crossing.
The solver already has timed constraints and derived preferences; its audited
inputs include the 00:15 preference end and 11:30 EV-target deadline. The raw
calendar row behind the 23:45 digest cannot be identified from that hash alone.

The initial five-group replacement classification overlaps: eleven publications
relate to deviation appearance/persistence/disappearance, including one tariff
transition and one presence transition; two explicit member revisions must also
be counted. A mutually exclusive partition of 21 replacements is two explicit
constraint changes, two presence/sleep changes, three tariff changes, three
window crossings, two appliance transitions and nine other deviation/expiry
cascades. Four genuine change-driven replacements remain in that history;
17 removals were an opportunity estimate, not a promised rerun count.

**04:31 correction:** seq 3699 starts attempt 1 at 04:30; seq 3705 publishes at
04:30; seq 3760 makes the job idle. Consent arrives at 04:31 (3764), the battery
opening is skipped (3820), refresh queues (3870), and a member notice follows
(3919). The battery was scheduled at 04:30, with `expected_effect.by=04:31` and
`revert.after_s=60`. This is delayed consent, not delayed publication. No
PLAN_REFRESH transition in this export records a transient `next_retry`.
`RefreshWorker.run` nevertheless has a real publication gap: computation,
runtime building, narration and polling precede the generation/fingerprint and
horizon checks, with no replacement-opening expiry check before transfer and
publication. The old consent path also lacked that expiry check.

The approved fixes remove period names and boundary digests, replay verified
applied controls through existing physics, recognize appliance lifecycle and
charge-ceiling transitions, requeue expired publication without notice, and
retain late consent while auditing missed openings and queuing a non-explicit
autonomous replacement. Exact consent semantics and rejected alternatives are
recorded in [ADR-005](./adr/ADR-005-deterministic-planner.md#change-based-freshness--2026-09-22-author-approved).

### Part 2 — implementation and verification

The approved changes are implemented in the refresh fingerprint, applied-control
prediction, publication guard and consent lifecycle. The queued late-consent job
uses `explicit=False`; `commit_mutation` inherits the stored approver for that
autonomous replacement. Focused integration evidence verifies the 23:30 proposal /
23:31 consent shape: one skipped opening, no NOTICE_PENDING, one replacement,
inherited approver and verified execution. The full replay below does **not** pass.

| Approved fix | Part 1 cause group | Expected effect on the Batch C history |
|---|---|---|
| Remove price_band | Known tariff transitions | Addresses three classified replacements; midnight also has a deviation. |
| Remove boundaries digest | Known constraint/calendar crossings | Addresses three classified replacements; row changes still refresh. |
| Applied controls and charge-ceiling precision | Undispatched/held controls, bounded endings and charge ceiling | Addresses the nine remaining deviation/expiry cascades with the consent fix; groups overlap. |
| Appliance ownership and completion | Two expected cycle transitions | Addresses two classified replacements. |
| Publication expiry guard | Potential stale computation/publication | No confirmed transient-publication case in this export; prevents publishing an expired opening. |
| Retain late consent and queue recovery | Missed opening before consent | Removes the expired-window notice and requires one legitimate autonomous recovery, rather than a second consent. |

No wider drift tolerance, grace period, plan-age adjustment, canonical shape,
dependency, migration, scenario or existing assertion change was made. Existing
availability, presence, plugged-in and unowned-control checks remain. Skipped
openings keep their terminal status when superseded, while pending approvals are
still expired; this exposes the assertion conflict below.

#### Ordered verification through the stop

Commands used the existing local environment and native `.tools/dogwood`.
Integration and scenario databases were uniquely named disposable databases.
The default uv cache restriction required authorized sandbox escalation; see the
[friction follow-up](./friction-log.md). No retained database was read or edited.

| Command | Actual summary / status | Local log |
|---|---|---|
| `uv run pytest` | `1246 passed, 114 deselected in 113.26s (0:01:53)` | `/tmp/hirz-c2-pytest-verified.log` |
| `uv run pytest -m integration --cov=hirz --cov-append` | `114 passed, 1246 deselected in 187.90s (0:03:07)` | `/tmp/hirz-c2-integration-complete.log` |
| `uv run --locked coverage report --fail-under=80` | `TOTAL 10235 731 93%`, exit 0 | `/tmp/hirz-c2-coverage.log` |
| `uv run mypy hirz/ scripts/ alembic/` | `Success: no issues found in 128 source files` | `/tmp/hirz-c2-mypy.log` |

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/batch-c2-evening \
  --output /tmp/hirz-batch-c2-report.json
```

**Exit 1: `failed`; 41 passed checks, six failed checks; 4,443 valid signed audit
rows.** Log: `/tmp/hirz-c2-evening.log`. The scenario retained its disposable
failure database; it was not reopened. Evidence comes only from the new report
and audit export. All eight `initial_summary` fields exactly equal run19.
No NOTICE_PENDING message reports an expired window. Four other notices concern
household-rule redecision, prohibited battery export or infeasibility.

| Failed check | Evidence |
|---|---|
| `ev_soc_at` | At 11:30 UTC SoC is 0.3703290265127458. |
| `ev_delivery_and_ceiling` | Required final 0.5 SoC was not delivered; the independent ceiling check passes. |
| `comfort_at_replay_boundaries` | Existing comfort assertion fails. |
| `completed_current_plan` | No completed plan satisfies the existing check. |
| `battery_terminal_preserved` | Existing terminal-energy assertion fails. |
| `superseded_work_cancelled` | Requires `cancelled` for every undispatched superseded action, excluding the newly preserved terminal `skipped` state. |

**Author decision required before continuation:** the superseded-work assertion in
`hirz/twin/execution.py` requires every superseded action without an execution
attempt to be `cancelled`. Fix 5 retains missed openings as `skipped`; the focused
late-consent test verifies that status. Propose accepting `skipped` only when the
own lifecycle evidence records `expired before consent`, while continuing to
require cancellation for other undispatched superseded work. This assertion has
not been changed. An alternative is to permit later supersession to cancel the
skipped row while retaining its earlier skipped audit event; that would change
the approved implementation's terminal-state interpretation and focused test.

Separate execution failures also remain unresolved. The first new path reaches
DENY_CONSTITUTION at seq 503 (22:36:00.000001 UTC), for the guest HVAC command
scheduled at 22:35 with heat target 68.055°F. Seq 589 queues `Current household
rules require a new decision.` Another denial at 23:15 leads to the blocked
battery-export comparison at seq 1197. Later genuine changes encounter an
infeasible remaining workload. At 04:31, consent correctly skips thirteen missed
openings from the 04:05 proposal, queues the non-explicit recovery at seq 2144,
and publishes at seq 2210. Further household-rule denials produce replacements;
seq 3860 finally blocks on `Battery discharge to grid prohibited`. The exact
cause of those denials has not been established; no policy, assertion or solver
constraint was weakened to bypass them. Lower counts in a failed execution are
not evidence of successful C2 behavior.

Hourly verification and `scripts/smoke_refresh.py` were **not run** after this
assertion gate. Their required commands remain outstanding, followed by a fresh
successful ordered verification run after any semantic correction:

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening-hourly.yaml --headless --assert \
  --output /tmp/hirz-batch-c2-hourly.json
uv run python scripts/smoke_refresh.py --audit-output <new-file-under-/tmp>
```

#### Retained comparison at the stop

Counts derive from unique audited mutation plan IDs, distinct supersedes
references, and ASK_CONSTITUTION action IDs joined to `energy.hvac_adjust` /
`hvac.guest_room`. Refresh reasons count their presence in queued transitions
(replaying partial job state by lineage); reasons can coexist or persist in a
coalesced request, so these counts are not a disjoint replacement classification.
The historical age reason below is reported only for comparison, not revisited.

| Metric | Item 22 run19 | Batch C | Batch C2 (failed) |
|---|---:|---:|---:|
| Plans | 152 | 22 | 8 |
| Superseded plans | 151 | 21 | 7 |
| Signed audit rows | 30,637 | 6,793 | 4,443 |
| ASK_CONSTITUTION, all classes | 93 | 10 | 5 |
| Guest-room HVAC asks | 92 | 9 | 4 |
| Queued refresh transitions | 160 | 26 | 13 |

| Reason in queued transition | Item 22 run19 | Batch C | Batch C2 (failed) |
|---|---:|---:|---:|
| Member constraint or manual hold changed | 4 | 4 | 5 |
| Household inputs, policy, control state or prediction changed. | 28 | 23 | 5 |
| The accepted plan is five minutes old. | 132 | 0 | 0 |
| The execution window expired. | 3 | 2 | 0 |
| Current household rules require a new decision. | 2 | 0 | 10 |
| consent arrived after scheduled changes | 0 | 0 | 1 |

All four C2 guest-room asks occur after 23:05 local; the target of zero or one is
not met. They occur at 04:31:00.000002, 04:36:00.000003, 05:00:00.000002 and
05:15:00.000003 UTC (audit seqs 2681, 2842, 3232, 3619). Two are successive
scheduled actions in the same replacement, so “one ask equals one replacement”
is not valid for this failed rerun. Full comparison output is
`/tmp/hirz-c2-comparison.json`; the temporary analyzer's success-only assertion
was not used to suppress the failed run.

#### Development failures retained for completeness

Earlier service-free runs passed with 1,245 tests before the skipped-approval
cleanup regression test was added. The first full integration run reported
`2 failed, 112 passed, 1245 deselected in 195.48s`: the new publication test had a
long opening window and the appliance fixture incorrectly introduced an
obligation through revision. The next reported `1 failed, 113 passed, 1245
deselected in 203.99s`: the appliance fixture lacked the original HVAC asset
binding. These new test fixtures were corrected, with no scenario assertion
change. The three focused tests then reported `3 passed, 11 deselected in
7.61s`, and the integration rerun reported `114 passed, 1245 deselected in
192.55s`. A final review preserved approval expiry when keeping skipped status,
added that regression check, and reran the successful ordered commands above.

The evening assertion failure is the outstanding product verification failure.
This batch is not complete; no commit, ROADMAP status or Current phase change
was made. Pre-existing workspace changes were preserved. Final Ruff checking is
run after this partial evidence and the approved decision/contract records.

Final Ruff attempt: `uv run ruff check . && uv run ruff format --check .`
first found three I001 import-order issues in the new integration tests. Targeted
`ruff check --fix tests/integration/test_refresh_database.py` corrected only those
imports; no behavior or assertion changed. The final command was rerun after
this record. Retained run19/Batch C audit and report SHA-256 checks all match the
pre-C2 snapshot, and every scenario file matches its pre-C2 hash.

Final Ruff summary: `All checks passed!`; `195 files already formatted`, exit 0.


### Author-approved continuation and successful rerun — 2026-09-22

The author approved narrowing `superseded_work_cancelled` to accept an unstarted
superseded action in `skipped` status only when its **own** lifecycle evidence
records `expired before consent`. The assertion now joins that action's
`lifecycle_seq` to the household-scoped audit row, checks its action ID, skipped
status and exact reason, and requires all other unstarted superseded work to be
cancelled. Tests reject missing evidence, another action's evidence, a different
expiry reason and held work. No scenario YAML or other scenario assertion changed.

**Correction to the first-run diagnosis above:** seq 503 was the Pipeline's
initial plan-authority denial caused by C2, not a new independent household-rule
failure. The 22:36 observations (seq 492) precede the EV execution attempt (498)
and VERIFIED (501), all at exactly 22:36:00 UTC. The next HVAC action is assessed
at 22:36:00.000001 and denied at seq 503 with mode `never`, `risk: null` and empty
`explain.rejected`. C2's inclusive timestamp comparison incorrectly applied the
EV write to the earlier same-instant observation. Separately, `fresh()` compared
raw fingerprints while `detect()` compensated owned control changes, allowing
Hirz's own control changes to invalidate its next action's plan authority. The
subsequent holds and six failed checks cascaded from this authority failure;
the earlier discussion of independent execution failures is superseded by this
confirmed diagnosis and the successful rerun.

The author-prescribed fixes were applied in order:

1. `predicted()` applies only dispatches strictly before the observation instant.
   The regression checks pre-dispatch EV power/charging at T and applied power/
   charging at T plus one microsecond. The twin's existing post-write clock tick
   supplies the later sample time; no clock was backdated.
2. `compensate_owned_controls()` contains the former detection compensation and
   is called by both `detect()` and `fresh()`. A real disposable-database test
   consents to two due actions on two devices and verifies both in one sweep,
   without DENY_CONSTITUTION, EXECUTION_HELD or a queued refresh.
3. `Pipeline.assess()` catches plan-authority rejection with canonical
   `Explanation.rejected = ("Plan execution lacks current approver authority",)`.
   A regression verifies that sentence, the deny and absent risk evaluation;
   private exception text is not exposed. No canonical shape changed.

Focused checks passed before the full gates: `3 passed, 90 deselected in 2.00s`
and `1 passed, 14 deselected in 3.10s`. Logs:
`/tmp/hirz-c2-r2-focused-unit.log`, `/tmp/hirz-c2-r2-focused-integration.log`.

#### Full ordered verification

| Command | Actual summary | Log |
|---|---|---|
| `uv run pytest` | `1247 passed, 115 deselected in 116.51s (0:01:56)` | `/tmp/hirz-c2-r2-pytest.log` |
| `uv run pytest -m integration --cov=hirz --cov-append` | `115 passed, 1247 deselected in 209.11s (0:03:29)` | `/tmp/hirz-c2-r2-integration.log` |
| `uv run --locked coverage report --fail-under=80` | `TOTAL 10247 736 93%`, exit 0 | `/tmp/hirz-c2-r2-coverage.log` |
| `uv run mypy hirz/ scripts/ alembic/` | `Success: no issues found in 128 source files` | `/tmp/hirz-c2-r2-mypy.log` |

The failed C2 artifacts remain untouched. The successful rerun uses a new nested
directory within the approved C2 artifact directory and a new output file:

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening.yaml --headless --assert \
  --artifacts-dir secrets/scenario-runs/batch-c2-evening/rerun-2 \
  --output /tmp/hirz-batch-c2-rerun-2-report.json
```

**Exit 0: `item22_execution_passed`; 47 passed checks, zero failed checks; 3,527
valid signed audit rows.** Log: `/tmp/hirz-c2-r2-evening.log`. EV SoC at 06:30
America/Chicago is `0.49999999992435573`; delivery, comfort, terminal battery,
completed-plan and approved superseded-work checks all pass. Every one of the
eight initial forecast summary fields exactly equals run19. There are **zero
NOTICE_PENDING rows**, including no expired-window notice. The only
DENY_CONSTITUTION is seq 3524, a terminal `governance.refresh_plan` request at
12:00 UTC; no planned device action has a plan-authority denial in this rerun.

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run hirz scenario run \
  scenarios/demo-evening-hourly.yaml --headless --assert \
  --output /tmp/hirz-batch-c2-hourly.json
```

**Exit 0: `item17_planning_and_observations_passed`; 16 passed checks and two
passed planning snapshots.** Log: `/tmp/hirz-c2-r2-hourly.log`. This remains the
Hourly planning/observation verification, not a second full execution claim.

The literal smoke command first failed before execution because this shell did
not export `HIRZ_DOGWOOD`: `Dogwood.run error=FileNotFoundError`, followed by
`Dogwood unavailable, timed out, or returned invalid output; no authorization`.
Log: `/tmp/hirz-c2-r2-smoke.log`. No audit output was created; the smoke retained
its disposable failure database, which was not reopened. This was an omitted
documented environment setting, not a third-party defect. Configuring the same
native binary used above resolved it without a code or dependency change:

```sh
HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run python scripts/smoke_refresh.py \
  --audit-output /tmp/hirz-batch-c2-refresh-audit.json
```

Exit 0, `/tmp/hirz-c2-r2-smoke-configured.log`:

```text
disposable_database=dropped; development_database=unchanged
restart=queued; replacement=published; approver=malik; per_device_evaluation=fresh
restart=running; replacement=published; approver=malik; per_device_evaluation=fresh
refresh=PASS; source=twin; signed_rows=74; offline=valid; export=/tmp/hirz-batch-c2-refresh-audit.json
```

#### Successful comparison

The same audit-only counting method used above produced
`/tmp/hirz-c2-r2-comparison.json` and `/tmp/hirz-c2-r2-comparison.log`.

| Metric | Item 22 run19 | Batch C | Batch C2 rerun 2 |
|---|---:|---:|---:|
| Plans | 152 | 22 | 6 |
| Superseded plans | 151 | 21 | 5 |
| Signed audit rows | 30,637 | 6,793 | 3,527 |
| ASK_CONSTITUTION, all classes | 93 | 10 | 2 |
| Guest-room HVAC asks | 92 | 9 | 1 |
| Queued refresh transitions | 160 | 26 | 7 |

| Reason in queued transition | Item 22 run19 | Batch C | Batch C2 rerun 2 |
|---|---:|---:|---:|
| Member constraint or manual hold changed | 4 | 4 | 4 |
| Household inputs, policy, control state or prediction changed. | 28 | 23 | 4 |
| The accepted plan is five minutes old. | 132 | 0 | 0 |
| The execution window expired. | 3 | 2 | 0 |
| Current household rules require a new decision. | 2 | 0 | 0 |
| consent arrived after scheduled changes | 0 | 0 | 1 |

Reasons can coexist in a queued transition and explicit constraint changes also
alter the input fingerprint. These are queue-reason occurrences, not separate
replacement counts. The five C2 replacements are attributable to the explicit
17:35 constraint revision, the 19:10 arrival, Dad's 22:40 explicit revision,
Mom's 23:05 sleep/presence change, and one 23:31 missed-opening recovery.
Publication audit seqs are 283, 986, 1791, 1929 and 2128. The background
publication mechanism labels these mutations autonomous, while each job's
`explicit` flag controls whether consent is inherited.

At 23:31, seven openings of the 23:05 proposal are skipped with `expired before
consent` (seqs 2021–2030, interleaved with normal scheduling). Queue seq 2070 has
`explicit: false` and only `consent arrived after scheduled changes`; publication
2128 inherits consent. The single guest-room ask is seq 2233 at
04:31:00.000002 UTC, for 72°F, scheduled at 04:31 UTC. It follows this genuine
missed-opening divergence after 23:05 local. **The requested zero-or-one target
is met: one guest-room ask.** The focused 23:30-proposal/23:31-consent fixture
still verifies exactly one skipped opening and one autonomous replacement.

The prior failed evidence is retained, not rewritten. New ADR and architecture
text records the approved freshness rule; the C2 changelog line links here.
No scenario YAML, unrelated assertion, dependency, migration, canonical shape,
ROADMAP status, Current phase or retained database was changed. The existing
plan-age work was not revisited. No commit was made. The previously recorded
cache limitation and this documented Dogwood setting did not earn a new
third-party defect entry. Ruff is run last after these records.

Final command, after the records: `uv run ruff check . && uv run ruff format --check .`.
**Exit 0: `All checks passed!`; `195 files already formatted`.** Retained run19,
Batch C and first C2 audit/report/public-key hashes match their captured values;
all verified code hashes match the full-gate run and scenario YAML hashes are
unchanged. The final Ruff command was repeated after recording this summary.


### HA smoke CI diagnostics — 2026-09-22

The author requested investigation of [run 35824038863](https://github.com/BashaarJavaid/Hirz/actions/runs/35824038863), then authorized exposing the underlying failure before changing execution behavior. Ten jobs passed; `scenarios` failed at `Live HA lamp and bounded restoration`. The original log reported `status: failed`, `restored: true` and only the wrapper exception. It did not publish the retained scenario report, so the original CI cause remains unconfirmed.

The smoke now prints the report error and failed/not-reached checks. A refused scripted lamp request also names its decision, risk band and factor names, without dumping the canonical decision or audit payload. No approval, freshness, device or assertion behavior changed.

Local verification:

- `UV_CACHE_DIR=/tmp/hirz-uv-cache uv run --locked pytest tests/unit/test_scenario_execution.py --no-cov`: **23 passed in 2.47s**.
- Strict mypy initially caught optional risk access in the diagnostic; after guarding it, `UV_CACHE_DIR=/tmp/hirz-uv-cache uv run --locked mypy hirz/twin/execution.py scripts/smoke_scenario.py`: **Success: no issues found in 2 source files**.
- `HIRZ_DOGWOOD="$PWD/.tools/dogwood" UV_CACHE_DIR=/tmp/hirz-uv-cache uv run --locked python scripts/smoke_scenario.py --live-demo --artifacts-dir /tmp/hirz-ci-35824038863-diagnostic`: **exit 1**, now visibly reporting `ValueError: Lamp request was not queued: decision=ask, risk=medium, factors=['state_stale']`; observation and both VERIFIED assertions were `not_reached`. The final lamp state matched its original state; this does not establish a toggle or bounded restoration. Evidence and disposable database `hirz_ha_smoke_224d0e268631439590cc6697e49348d0` remain retained. Development was not migrated.

This verifies diagnostics, not a fix of the live smoke. Remote verification follows the diagnostic push. Third-party friction review found only the already-recorded sandbox network/cache restrictions; no new upstream defect was established. Ruff runs after this entry.
