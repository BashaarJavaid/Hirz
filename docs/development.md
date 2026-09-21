# Development procedures

The existing stack setup and credential recovery procedures remain in the
[README](../README.md#local-development-stack-phase-0-items-2–3) until their planned
move before submission. This page owns the new graph operating procedures.

## Item 6: migrate, seed, inspect

Run from the checkout root with the existing PostgreSQL service and `.env`:

```bash
uv sync --locked
uv run alembic upgrade head
uv run alembic check
uv run hirz doctor
uv run hirz seed constitutions/quinn-home.yaml constitutions/quinn-parents.yaml
uv run hirz context 536fa8ee-854e-56ca-8c5d-5ba418e710a0 --scope energy
uv run hirz context bf745178-9146-5952-a310-f1d7e563977b --scope people
```

The loader prints household UUIDs, member/asset counts, versions, and `loaded` or
`unchanged`. Both policies are **unvalidated**. It never activates a constitution,
creates a signed audit event, calls an adapter, or installs a runtime write API.
The author-approved bootstrap exception is recorded in ADR-002.

Each file has exactly two YAML documents: graph first, constitution second. Only
the two named demo households, `demo` account links and twin bindings are accepted.
Graph keys and references are validated before insertion; duplicate keys are
rejected. Initial versions use the injected transaction clock (UTC wall time in
the CLI); the seeds contain no observation timestamps or invented history.

All files supplied to one command load atomically. Repeat commands compare parsed
contents and stored facts, so comments and formatting do not matter. An untouched
matching household is a no-op. A changed seed, graph edit/history, audit event, or
constitution activation makes the command fail rather than reset data. There is
no `--force` or implicit initialization at startup. Use disposable test databases
for mutation tests, not the existing demo households.

`context` accepts scopes `all` (default), `people`, `member`, `energy`, and
`environment`. `member` requires `--member <uuid>`; other scopes reject it. UUIDs
for members are present in a `people` read. For a historical read:

```bash
uv run hirz context <household-uuid> --scope all --as-of <timezone-aware-ISO-8601>
```

Use an actual graph `valid_from` timestamp or a later recorded instant. Reads
before a household existed and future historical reads fail. Times without a
UTC offset fail argument parsing. History answers what was recorded then; an
observation received later cannot appear in an earlier snapshot even when its
measurement timestamp was earlier.

Output is redacted JSON: no account subjects, channel values/hashes, or safe-word
hashes. Missing measurements stay missing. Source labels distinguish real,
real-API demo devices, and twin data. The read-only command opts into stale
fallback, but caches are per service instance; separate CLI invocations share no
cache, so a fresh CLI invocation cannot read through a database outage. Library
callers default to `allow_stale=False` and must not opt in for decisions.

Success exits 0; operational errors exit 1; invalid command arguments exit 2.
Errors withhold upstream SQL parameters and private values. No command prints
credentials. Doctor checks all graph tables and the materialized view in addition
to its existing service/signing checks. `alembic check` covers table metadata;
PostgreSQL integration tests exercise the view's contents and refresh behavior.

## Verification and recovery

```bash
uv run pytest
uv run pytest -m integration --no-cov
uv run ruff check .
uv run ruff format --check .
uv run mypy hirz/ scripts/ alembic/
uv build
```

Integration tests create uniquely named `hirz_test_*` databases and remove only
those databases. They exercise fresh/populated migrations, historical boundaries,
seed repetition, privacy, version conflicts, concurrent updates, and rollback.
No test executes a household action. The default suite remains service-free with
its 80% coverage gate; its existing WebSocket fixture needs localhost binding.

Migrations remain explicit. If a migration or refresh fails, retain data and fix
the cause; never reset an evolved household to make seeding pass. Item 6 downgrade
destroys its graph additions and history while retaining the foundation tables;
`downgrade base` destroys the application tables as well. Exercise downgrade in
disposable databases, except for the empty-audit development reset below.

A development schema reset and reseed is permitted whenever a read-only query
confirms `audit_log` is empty, because there is no audit history to preserve.

Whole-view refresh and graph writers serialize globally. This is the approved
small-graph implementation; neither the 20 ms context budget nor production write
throughput is claimed by item 6. Observation partitioning, real adapter ingestion,
policy activation, auth, and signed audit behavior remain later items.

## Local constitution workflows (item 7)

Install Rust 1.98.1 with Cargo and a native linker (Apple command-line tools on
macOS; the normal build toolchain on Linux). The build uses the pinned upstream
revision and checked-in dependency lock, needs network access, and writes only a
local binary. No Python bindings or daemon are required.

```sh
uv sync --locked
uv run python scripts/build_dogwood.py
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run hirz constitution validate constitutions/quinn-home.yaml
uv run hirz constitution compile constitutions/quinn-home.yaml --gateway-resource hirz-local
uv run hirz constitution preview constitutions/quinn-home.yaml /path/to/proposed-v8.yaml
uv run pytest
```

Alternatively put the pinned `dogwood` binary on `PATH`. A missing binary fails
validation/tests; it does not select another engine. The default Gateway resource
is `hirz-local`. Validate/compile output JSON with English, local engine findings,
and `not analyzed: local mode`; compile also includes policy text, action schema,
and a manifest. Preview accepts two complete documents (standalone or seed
envelopes), not an English patch. Diagnostics go to stderr and failures exit
nonzero. None of these commands requires `.env`, a database, credentials or AWS.
Local engine checks do not establish AWS conformance or authenticate approvals.

The container's Rust build stage checks out the same source revision and uses
`scripts/dogwood.Cargo.lock`. Only its native binary reaches the final Python
image; Cargo stays in the builder, and runtime UID remains 10001. Python wheels
carry the class catalog and situation corpus. CI requires native local checks in
`cedar-conform`; AWS comparison remains item 37.

**Existing seed history is preserved.** The files now explicitly give
`security.access_code_share` the `app_push` channel. Old stored seeds inherit
Alexa, so validating them reports `security.access_code_share: security approval
channels must exclude alexa, including never rules`. Their rows, hashes and
`unvalidated` status are not rewritten. Do not reset a household, rerun seeding to
force a change, or edit the stored YAML/hash: the later activation workflow owns
new stored constitution versions. Corrected files can seed a fresh disposable
household for tests. Bootstrap remains the explicit item 6 exception.

## Standalone risk scoring (item 8)

The [risk contract](../ARCHITECTURE.md#53-risk-engine) accepts a canonical Action,
typed facts, and its selected validated Rule. This example uses explicitly
synthetic constitution-preview data; it does not read live observations, access
the database, approve anything, or act on a device. The pipeline CLI is documented
under [decision preview](#decision-preview-item-11).

Run from the repository root:

```sh
uv run --locked python - <<'PY'
from pathlib import Path
from unittest.mock import patch

from hirz.constitution.preview import situation
from hirz.constitution.schema import load
from hirz.risk import floor_outcome
from hirz.risk.engine import RiskFacts, score

policy = load(Path("constitutions/quinn-home.yaml"))
action, _ = situation(policy, "energy.hvac_adjust")
rule = policy.rule(action.action_class, action.requested_by.role)
ordinary = RiskFacts(observation_ages_seconds=(0,),
                     sleeping_in_target_zone=False, baseline_target_f=72)
escalated = RiskFacts(observation_ages_seconds=(301,),
                      sleeping_in_target_zone=True, baseline_target_f=65)
for label, facts, expected in (("ordinary", ordinary, "low"),
                                ("escalated", escalated, "critical")):
    result = score(action, facts, rule)
    assert result.band == expected
    print(label, result.model_dump_json(), "floor=" + floor_outcome(result.band))
with patch("hirz.risk.engine.guards", side_effect=RuntimeError("injected failure")):
    result = score(action, ordinary, rule)
    assert result.band == "critical" and result.factors[-1].factor == "scoring_error"
    print("exception", result.model_dump_json(), "floor=" + floor_outcome(result.band))
PY
```

The ordinary result is LOW with no floor. Sleep, stale state, and deviation
together reach CRITICAL; the injected exception also produces CRITICAL. Both
have `never_auto` floors. These are synthetic test inputs, not observed household
conditions. To test the implementation, run
`uv run --locked pytest tests/unit/test_risk.py --no-cov`, then the full Python
checks above with the pinned native Dogwood binary available. A sandbox that
cannot write uv's normal cache can set `UV_CACHE_DIR` to a writable temporary
directory; this changes tooling storage only.

## Internal pipeline API (item 9)

The API is `hirz.pipeline.service.Pipeline`: `evaluate`, `propose`, `vote`, `redeem`.
Construct an explicit `PolicyBundle` with `await PolicyBundle.validate(household_id,
policy, Dogwood())`, then supply a SQLAlchemy async connection, `AuditWriter` wrapping
the existing validated signing key, and an injected clock. Mutation methods own their
transaction; pass a connection without an active transaction. The trusted `Principal`
and typed `SupplementalEvidence` are internal integration inputs, not public request
bodies. Construct the one canonical `Action`, then set its `content_hash` with
`hirz.pipeline.hashing.action_hash`. Budget estimates are nonnegative `Decimal` values.
The full API and trust contract is in [architecture §3.4](../ARCHITECTURE.md#34-internal-pipeline-contract-item-9).

With local PostgreSQL running and the existing `.env` initialized, run:

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run --locked python scripts/smoke_pipeline.py
```

This runnable internal API example creates a uniquely named `hirz_smoke_*` database,
migrates and seeds it, validates an explicit policy with native Dogwood, evaluates and
proposes a notification authorization, records a vote, redeems once, and retries the
same approval. It asserts one grant and the exact Decimal reservation, then drops only
its disposable database. It reads the existing signing key without changing credentials.
Stored seed policies remain unvalidated. No notification is sent or device operated.
Actual output and checks are recorded once in the [item 9 evidence](./verification-log.md#item-9--complete-2026-09-18).

For the real database checks, `uv run --locked pytest -m integration --no-cov` uses
uniquely named disposable databases, including upgrade/downgrade and metadata agreement.
The internal service does not expose authentication, activation,
physical execution (item 19), or AWS enforcement. Item 11 wraps its read-only
evaluation in [the CLI](#decision-preview-item-11). Audit append is available internally;
audit verification/export procedures follow below.

## Decision preview (item 11)

Run from the checkout root with the existing regular mode-0600 `.env`, its original
P-256 signing key, local PostgreSQL at the existing migration head, and the pinned
native Dogwood binary. Migrations remain an explicit operator command; `decide`
never runs them. The household's referenced stored policy must pass current
validation. [Preserved old seeds](#local-constitution-workflows-item-7) are not
rewritten or replaced with files from the repository; upgrading the schema alone
does not repair an invalid policy.

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run hirz decide --help
uv run hirz decide \
  --household 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --as malik --surface alexa --action finance.transfer_money \
  --adapter household --entity 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --params '{}'
```

With a valid stored seed this returns `DENY_CONSTITUTION`, with exit 0: the command
successfully evaluated a forbidden hypothetical action. It moves no money and
creates no audit row. Policy/configuration/database errors instead exit 1 with
safe stderr and empty stdout. Invalid command inputs exit 2 without echoing values.
Stdout is only canonical Decision JSON; stderr labels every returned result as a
hypothetical preview of an unactivated policy. Even `EXECUTE` grants no authority.

Both demo UUIDs are returned by `hirz seed`; `quinn-parents` is
`bf745178-9146-5952-a310-f1d7e563977b`. `--as` selects a stored `demo` account subject,
not a voice or authenticated person. `--surface` is required (`alexa`, `app`, or
`scheduler`). Action class, adapter, entity and JSON-object params are required;
`--zone` takes a household HVAC zone UUID. Read actual bindings and zone IDs with
`hirz context <uuid> --scope all`; no friendly-name inference is performed.

Optional `--cost` is an exact, finite, nonnegative Decimal; omission leaves cost
unknown, so a budgeted action can deny. `--at` accepts an aware ISO timestamp and
otherwise uses current UTC. It changes the clock against current graph data, not
historical state; earlier row versions are not recovered, and stale/missing facts
still fail closed. Seed files contain no observations, so seeding alone does not
establish the facts needed for an HVAC or security preview.

Optional `--evidence <file.json>` now reads a strict JSON object with optional
`observations`, `asset_rooms`, and `scam_pattern` fields. This is an incompatible
change from item 11's aggregate evidence list: `occupancy_complete`, `guest_present`,
`target_is_bedroom`, `unexpected_visitor` and `doorbell_online` are no longer caller
flags. Their graph homes are in `ARCHITECTURE.md` §5.11. The example below uses the
new shape. Duplicate JSON keys, invalid/nonfinite values and non-twin evidence are
rejected. `--requester-confirmed` remains hypothetical confirmation only; there are
no approval, passkey, vote, redemption or policy-file controls.

The reproducible nine-case CLI run uses only disposable databases and synthetic
fixture state; it prints each initial event and verifies unchanged database state:

```sh
uv run pytest tests/integration/test_decide_database.py -m integration --no-cov -s
```

It calls the actual argparse dispatch and handler, substituting only database and
test-key configuration. Native Dogwood, stored policy loading and the pipeline run
normally. The spending fixture establishes usage with an internal grant, never a
fabricated audit row or device operation. Actual results and the existing local
database's reset and successful invocation are recorded in [item 11 evidence](./verification-log.md#development-database-reset-and-phase-1-review--2026-09-18).

## Adapter contracts and graph facts (item 12)

The registry and nine domain protocols exist; production adapters, twin models and
observation ingestion do not. No application endpoint or CLI command starts an
adapter in this item. `HIRZ_ADAPTERS` is a process environment variable containing
comma-separated `domain:implementation` pairs, for example `devices:ha,ev:twin`.
Omitted domains are unavailable; selected implementations must be registered by
the host. The factory dictionary currently has no production registrations.
Per-entity asset bindings override defaults. Nothing automatically falls back to twin.

The printable boot proof uses only test implementations and no device credential:

```sh
uv run pytest tests/unit/test_adapters.py -k mixed_boot --no-cov -s
uv run pytest tests/integration/test_adapter_database.py -m integration --no-cov -s
uv run pytest tests/integration/test_decide_database.py -m integration --no-cov -s
```

The integration tests create and drop uniquely named disposable databases. They
exercise migration, preserved current/historical reads, domain uniqueness, guarded
rollback and actual CLI dispatch with native Dogwood, verifying no preview writes.
They do not migrate or reset the existing development database.

**Schema compatibility.** Operators explicitly run `uv run alembic upgrade head`
before using item 12 with their development database. Startup and preview never run
migrations. Revision `0004_observation_domains` preserves old null-domain rows and
history. Those observations remain visible to reads but cannot supply decision
facts. New readings require an explicit domain and new IDs rather than inferred
retagging. Downgrade refuses any tagged current or historical observations, even
if only one domain exists: the old application's model cannot read the field.
Never erase history, reset the database or change its audit key to work around this.

**Explicit preview file.** For a seeded `quinn-home` with no stored light observation
or room metadata, save this JSON as `/private/tmp/hirz-light-preview.json`. The
observation ID is a synthetic preview ID, and the asset UUID is the seed's living
room light. Every supplied reading must have its own explicit ID, domain, aware
observation time and `source: twin`.

```json
{
  "observations": [{
    "id": "34a7254d-3a84-5dd4-b23c-5cd7c6ae2c2b",
    "household_id": "536fa8ee-854e-56ca-8c5d-5ba418e710a0",
    "asset_id": "cac78d95-1ad7-5ea1-9d46-7fa092854363",
    "domain": "devices",
    "observed_at": "2026-10-13T17:35:00-05:00",
    "source": "twin",
    "state": {"available": true, "on": false}
  }],
  "asset_rooms": [{
    "asset_id": "cac78d95-1ad7-5ea1-9d46-7fa092854363",
    "room_kind": "other"
  }]
}
```

```sh
uv run hirz decide \
  --household 536fa8ee-854e-56ca-8c5d-5ba418e710a0 \
  --as malik --surface alexa --action environment.lights \
  --adapter twin --entity light.living_room --params '{"on":true}' \
  --at 2026-10-13T17:35:00-05:00 \
  --evidence /private/tmp/hirz-light-preview.json
```

The optional `scam_pattern` field is an object containing `household_id`,
`observed_at`, `source: "twin"`, and Boolean `scam_pattern`. Presence examples instead
supply member-subject observations in domain `presence`, one per member; recovery
uses separate `wearable` observations. Room kinds are only `bedroom` and `other`.
The snapshot overlay accepts new subject/domain readings or exact canonical
no-ops, never changed readings or partial field merges. Room metadata fills only
missing values. Unknown UUIDs, duplicate overlay entries, cross-household facts,
future observations, non-twin sources and arbitrary graph changes are rejected.
Conflicts discovered against the graph return a fail-closed Decision; malformed
file input exits 2. All success output remains hypothetical, with no execution
grant, audit row or database change. See the evidence log for actual runs.

## Audit verification and export (item 10)

Run database commands from the checkout root with the existing initialized `.env`
and migrated PostgreSQL. These are local operator commands, not public authenticated
API endpoints. Use a household UUID from the seed/context output:

```sh
uv run --locked hirz verify-audit --household "$HOUSEHOLD_ID"
uv run --locked hirz audit export --household "$HOUSEHOLD_ID" --output audit.json
# Choose an interval that exists in this household; endpoints are inclusive.
uv run --locked hirz audit export --household "$HOUSEHOLD_ID" --range 2:3 --output audit-range.json
```

Exports refuse existing paths and are created with mode `0600`. They include
unchanged signed payloads and may contain household information; there is no
redaction mode. Even a range export checks the entire household chain first.
For command/result and file-format semantics, see
[architecture §5.10](../ARCHITECTURE.md#510-audit-ledger).

To obtain the public key and fingerprint directly from your own trusted local
installation, run the following in the checkout. It prints only public material;
it never generates or replaces a signing key:

```sh
uv run --locked python - <<'PY'
from pathlib import Path
from hirz.audit import fingerprint, public_pem
from hirz.local import read_env, signing_key
key = signing_key(read_env(Path('.env'))).public_key()
print(public_pem(key), end='')
print('Fingerprint:', fingerprint(key))
PY
```

Save just the PEM block as `trusted-public.pem` or retain the fingerprint, and
transfer that trust information separately from an untrusted export. Database
commands may use `--public-key trusted-public.pem` without loading the private
key; they still need `.env` for database credentials. Do not accept a key simply
because it was embedded in the file being checked.

Offline verification needs the installed Hirz CLI but neither PostgreSQL nor `.env`:

```sh
hirz verify-audit --household "$HOUSEHOLD_ID" --file audit.json --public-key trusted-public.pem
hirz verify-audit --household "$HOUSEHOLD_ID" --file audit-range.json --trusted-fingerprint "$TRUSTED_FINGERPRINT"
```

Both commands return JSON and nonzero exit status on failure. `empty` is a
successful check of an empty chain, not proof that history never existed.
`--anchors` is not implemented; all results state the local anchoring limitation.
Do not repair rows, reset pointers or replace keys to make verification pass.
Preserve the original evidence and restore the original key when it is missing.

Run the disposable end-to-end example and concurrency check with:

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run --locked python scripts/smoke_pipeline.py --audit
uv run --locked pytest tests/integration/test_audit_database.py -m integration --no-cov -s
```

The smoke extends the existing internal pipeline example. It substitutes only the
CLI's connection factory to target its uniquely named disposable database (the
local CLI deliberately has no database-selection flag); parsing, verification,
file writing, and cryptography are real. Offline commands run as separate installed
CLI processes in a temporary directory without `.env`. It verifies full and range
exports, changes one exported payload, asserts rejection, and removes only its
temporary files and database. No device operation or live-household mutation occurs.

## Twin models and read adapters (item 13)

Run the credential-free demonstration from the checkout root:

```sh
uv run --locked python scripts/smoke_twin.py
uv run --locked pytest tests/unit/test_twin.py --no-cov
```

The smoke reads both existing seed files without loading them into PostgreSQL,
uses explicit synthetic inputs and in-memory `rate_plan=twin` copies, boots eight
read adapters, and prints measured physics checks and household energy residuals.
All observations are labeled `twin`. No `.env`, network feed, model, solver, device
command, audit append or development migration is involved. The script's values
are demonstration inputs, not product defaults or real ComEd rates.

For library use, construct the validated models in `hirz.twin`, supply a
`TwinConfig`, and construct `TwinWorld` with canonical household records and a
`SimClock`. `hirz.twin.adapters.registry(world, config)` uses the existing adapter
configuration syntax; omitting `config` reads `HIRZ_ADAPTERS`, with no implicit
defaults. Start/close the registry and resolve an advertised read capability.
Advance a paused clock with `clock.jump(aware_timestamp)` before reading adapters.
`world.advance_to(at)` is useful for physics checks but does not move the clock;
do not subsequently ask adapters to read an earlier clock instant. Reinitialize
the world to replay. Supply all missing calibration/initial-state inputs explicitly.

For doorbell inputs, pause the clock, take `clock.now()`, and submit strict JSON
through the twin adapter's `on_event(body, {})`. This changes simulated world
state only; it is not a Ring webhook route. Every action method and device
subscription remains unavailable. Full interfaces and numerical defaults have one
home in [the twin spec](./twin-and-scenarios.md#211-item-13-in-memory-contract).

The integration regression for the new nullable observation fields uses only the
existing uniquely named disposable databases:

```sh
uv run --locked pytest -m integration --no-cov
```

Item 13 adds no schema revision and does not apply item 12's pending development
database upgrade. The bundled SVG is original repository artwork and ships in the
Python wheel; it is visibly labeled as simulated.

## Credential-free energy adapters (item 14)

No database, account credentials or worker is needed. The default smoke reads hashed
recordings; opt into public network reads explicitly:

```bash
uv run python scripts/smoke_energy.py
uv run python scripts/smoke_energy.py --live --history-month 2026-08
uv run pytest tests/unit/test_energy.py
```

The live command reads one day of Time-of-Day/day-ahead prices, the requested whole
month of five-minute quotes, and three hours of current weather. It prints source
labels, requested/observed bounds, slot counts, explicit gaps, coverage and prices
derived from returned data. Missing intervals are expected to remain visible;
acceptance requires returned data, not an invented complete month. Recorded mode
covers August 1 and the captured weather window, and uses an injected clock; its
retrieval timestamps are replay-clock values. Actual fixture acquisition timestamps,
URLs and SHA-256 are in `tests/fixtures/energy/manifest.json`.

Construct `RealEnergy(household, delivery_class=..., tariff_path=...)` with
`delivery_class="residential_single_family_without_electric_space_heat"` and an
explicit `Path` to `tariffs/comed-time-of-day.yaml`; call `await start()` before
reads and `await close()` in `finally`. The wheel intentionally does not discover a
checkout or silently choose a tariff: distribute the reviewed YAML separately and
supply its path. The smoke also accepts `--tariff-file /absolute/path/to/file.yaml`.
The tariff's retained PDFs and hashes support manual cross-checks; normal tests use
reviewed values without a PDF dependency.

For registry use, merge `hirz.adapters.energy.real.factories(delivery_class=...,
tariff_path=...)` into the existing factory map and explicitly select `energy:real`.
Register the household energy subject as `real` for tariff observations. Per-asset
battery/solar twin bindings continue to select the existing twin factory. Supply
the twin world with an explicit in-memory copy using `rate_plan="twin"`; its factory
allows that rate-plan difference while checking all other household fields. A missing
location disables weather only. There is no implicit twin fallback, asset-derived
class, ingestion, database mutation, real device read or action execution.

Read `series.slots` / `series.samples`, check `series.complete` and retain `series.gaps`
and provenance. `get_prices` supplies the scheduling basis; `get_supply_history`
returns supply-only data for historical research. **Billing exclusions, supply
validity and the pinned-delivery historical limit are specified in
[twin §2.6](./twin-and-scenarios.md#26-tariff).** Historical day-ahead retrieval is
not proof of publication time; five-minute quotes are not finalized hourly bills.

## Home Assistant adapter (item 15)

Item 15's local software is available; its physical plug gate remains outstanding.
This uses `dogwood-local`, not the AWS signed-command boundary. No worker poller,
ongoing graph ingestion, scheduler, automatic retry, twin writes or Link execution
is provided. The development schema is not upgraded by any smoke command.

The default smoke needs no services or credentials:

```bash
uv run python scripts/smoke_ha.py
```

For the approved live demo, use the initialized private `.env`, running local
Postgres and Home Assistant, and the pinned `.tools/dogwood` executable:

```bash
docker compose -f compose.dev.yml up -d postgres homeassistant
uv run python scripts/smoke_ha.py --live-demo --audit-output /private/tmp/hirz-ha-demo-audit.json
```

The output path must not exist. `config/homeassistant/adapter-demo.yaml` explicitly
maps the demo heatpump, ecobee and bed light to the disposable Quinn home's
living-room HVAC, guest-room HVAC and light assets. Ecobee is read-only because it
has a ranged target; the heatpump is tested at 72 °F in its existing heat mode.
The light is turned on. Subscription observations and direct read-backs must be
labeled `real API, demo devices`. Separate pipeline actions restore the original
heatpump target and light state. Restoration failures are printed and fail the
command; inspect HA before retrying. A request with an uncertain outcome is never
resent under its old action/grant.

The command creates and migrates a uniquely named `hirz_ha_smoke_*` database.
The approved test-only bootstrap installs initial HA bindings, explicit `other`
room metadata for the synthetic light asset, direct HA input observations and
one-time simulated absent-member observations. This does not change the seed
loader's twin-only restriction or activate a policy. After native Dogwood grants,
signed attempts and outcome rows, the whole audit is verified, exported privately
(mode 0600), and verified offline. Only then is a successful smoke database deleted.
A failing smoke retains its named database, including when export or restoration
fails. Do not delete it before preserving/verifying its audit evidence.

For a physical plug, supply a reviewed local YAML file explicitly, with the
control and its actual power sensor from your HA installation:

```yaml
url: http://127.0.0.1:8123
entities:
  switch.your_explicit_plug:
    source: real
    power_sensor: sensor.your_explicit_plug_power
```

```bash
uv run python scripts/smoke_ha.py --live-plug --config /private/tmp/my-ha-plug.yaml --audit-output /private/tmp/hirz-ha-plug-audit.json
```

This mapping must contain exactly one `light.*` or `switch.*` control, `source: real`
and a `sensor.*` power sensor; the disposable binding maps it to `light.living_room`.
No hardware is selected automatically. It authorizes on and restoration via the
Pipeline, requires measured power, checks direct HA state and observes the event
stream. A physical-device run is not claimed until this has actually passed;
physical absence still needs the scenario-fallback and ordinary-unavailability
checks in roadmap item 15. Synthetic outage tests do not close that hardware gate.

Application integration uses
`hirz.adapters.devices.ha.factories(config_path=..., assets=..., bindings=..., pipeline=...)`
and the existing `Registry`; omit `pipeline` for read-only adapters. Pass trusted
per-asset sources to the registry matching the YAML. `HA_TOKEN` is read from `.env`
only, with the existing regular-file/0600 checks. Never put it in YAML or a binding.
Only explicitly bound controls are discovered or read. Unknown/unavailable controls
raise `AdapterUnavailable` with `actual state unknown`; missing power produces null.

For a scenario, give the registry `scenario_mode=True` and explicit
`fallback_bindings=(...)` naming the same assets with `adapter="twin"`, and register
the household's existing twin factory. `await registry.get_state(asset_id)` can
then read its twin on primary unavailability. `resolve()` still selects HA; ordinary
`stamp()` still rejects the fallback as a primary observation. Authentication,
malformed payloads and invalid provenance fail without falling back. An ordinary
household has no fallback and cannot verify a real action from a twin.

Migration `0005_execution_attempt` follows item 12's `0004_observation_domains`.
Apply upgrades explicitly only when intended; the smokes migrate disposable data.
Downgrade refuses any claimed attempt or `EXECUTION_ATTEMPTED` row, even if its
claim pointer was removed. Never erase evidence to force a downgrade.

## Scenario runner (item 16)

This is an offline, in-memory simulation. No database initialization, migration,
seeding command, `.env`, HA, AWS, LLM or physical device is needed. The scenario
files supply explicit simulated inputs; their seed files are read without writes.
The full input/report contract is in [the scenario specification](./twin-and-scenarios.md#31-item-16-runnable-contract).

Build the pinned native Dogwood CLI if it is not already present, then select it
explicitly. A missing or failing validator refuses simulated activation; there is
no fallback that silently skips that check.

```sh
uv run python scripts/build_dogwood.py
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
uv run hirz scenario step scenarios/demo-evening.yaml --to "18:40" --assert
uv run hirz scenario run scenarios/demo-evening.yaml --step --to "18:40" --assert
uv run hirz scenario run scenarios/parents-scam-check.yaml --speed 60 --assert
uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert --output /private/tmp/hirz-evening-new.json
```

Stdout is the JSON report; event progress is on stderr. `--output` creates a new
file exclusively and also emits the same report on stdout. Existing paths,
including symlinks, are refused. Input hashes identify the exact scenario, seed
and recorded patch bytes. Reports omit private call/channel data and raw speech;
they have no audit range and are not signed audit exports.

Headless mode jumps directly between event/check times. A normal run paces the
same simulated instants at the YAML speed or positive finite `--speed` override.
Step replays from the beginning, advances to the target and exits before events
at that time; it does not store a resumable session. Checks at/after the target
are `not_reached`, even if the corresponding pre-event snapshot is exported.

Exit 0 means the requested run/step finished without a failed active check.
With `--assert`, only a full run can report `item16_observations_passed`; a step
reports `stopped`. Without the flag, checks are `unchecked` and a full run reports
`completed_unchecked`. An explicit future assertion remains `deferred` in every
case. Exit 1 is an input, validator, runtime, assertion or output failure; exit 2
is CLI usage failure. Inspect the report status rather than interpreting exit 0
as full demo verification.

```sh
uv run pytest tests/unit/test_scenario.py --no-cov
uv run pytest
uv run pytest -m integration --no-cov
uv run mypy hirz/ scripts/ alembic/
uv run ruff check .
uv build
```

Run the format check after appending verification evidence. PostgreSQL regressions
use their existing uniquely named disposable databases; the scenario commands
never connect to PostgreSQL. For a wheel smoke, install the wheel into a temporary
venv, leave the checkout, and pass an absolute path to a scenario file (its relative
household/patch references still resolve from that file). Scenario fixtures are
repository inputs, not bundled runtime assets.
