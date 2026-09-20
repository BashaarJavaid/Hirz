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
