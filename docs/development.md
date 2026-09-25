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
local reference CLI and its private MCP helper. No Python bindings or network
daemon are required; standalone constitution commands use the reference CLI.

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
`scripts/dogwood.Cargo.lock`. Only the two native binaries reach the final Python
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

## Item 17 planner and backtest

The planner is a read-only Python API: `hirz.planner.service.plan(PlannerInput)`.
Its proposed Actions confer no execution authority. Run from the repository root:

```sh
uv sync --locked
uv run python scripts/smoke_planner.py
uv run python scripts/smoke_planner.py --live-weather
uv run python scripts/backtest.py
uv run python scripts/backtest.py --verify
```

The smoke separates SciPy import/cold timing, solve timing, and greedy proposal
timing. `--live-weather` reads the existing Open-Meteo adapter and is explicitly
excluded from historical figures. Smoke exits nonzero if a plan or either latency
gate fails. The study replays retained inputs offline by default. Replications run
sequentially so other study solves and artifact compression do not compete with
the five-second solver budget. `--fetch` is the
explicit public-network operation: archive day-ahead and five-minute responses
sequentially, including lookback and ending coverage, and fetch archived weather.
It resumes existing checksummed downloads without refreshing them. A network
failure leaves completed responses and their manifest intact. `--start` and
`--end` accept ISO dates; `--output` selects a generated-artifact directory.

`results.json` is the readable metrics/final-state summary; `results.json.gz`
retains the full daily record, selected forecast timestamps, comparison exclusions,
requested schedules, applied controls and their segment boundaries. `daily.csv`,
`readme-table.md` and `workload.json` are derived artifacts. Study exit 1 means a
strategy failed to complete the requested physical horizon; inspect `stopped` and
`physical_days`. Missing billing quotes alone exclude savings for that day and
reduce eligible/total coverage, without resetting state or failing physical
completion. Aggregate cost, wear, loss and export totals use eligible
timer-comparison days; the full daily record retains physical energy on days
with missing bills. `--verify` makes no downloads and compares a fresh replay
to the full retained record and regenerates the summary, CSV, publication table and workload
configuration, excluding only solver/run timing measurements (physical cycle
clocks are compared); exit 0 means reproduction,
**not** that every requested day had a valid cost comparison. The shared simulated
feedback contract and its conservative terminal-energy bound are in
[ADR-005](./adr/ADR-005-deterministic-planner.md#causal-historical-replay-amendment--2026-09-21).

```sh
uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
uv run hirz scenario run scenarios/demo-evening-hourly.yaml --headless --assert
uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
```

Planning snapshots are separate from the observation world and do not charge the
scenario car or change its thermostat. The two planning scenarios supply their
weather and retain tool, approval, audit and execution deferrals. The Hourly
counterpart remaps the seed's schedule dates by -365 days and labels its tariff
counterfactual. See [verification](./verification-log.md#full-offline-reproduction-and-completion--2026-09-21)
for measured coverage, the raw archive inventory, and subsequent verification runs.

## Item 18 coordinator and audited intake

The interface is `Coordinator(Pipeline(...))` in `hirz/planner/coordinator.py`.
`intake(principal, action_id=..., text=..., horizon_end=...)` returns a clarification
without changing constraints for unsupported/ambiguous input, or a canonical
Pipeline Decision plus the recorded constraint UUID. The principal is the trusted
linked-account result, never a name supplied in the text. Pass `replaces=UUID` for
an explicit replacement, or `withdraw=True, replaces=UUID` for withdrawal. A
`change …` sentence must uniquely match that account's current request of the same
kind/device. Retry with the same action ID, principal and complete input.

`plan(principal, inputs, previous=None)` resolves membership, reads a current
snapshot and returns structured conflicts, per-class approval requirements and a
read-only planner result. Input slot start must equal the explicit Pipeline clock;
inputs and any previous Plan must belong to that household. A plan remains a
proposal without execution authority. Grammar and precedence are in
[architecture §5.5](../ARCHITECTURE.md#55-coordinator).

For an explicit simulated manual event, pass `manual=Observation(...)` with the
same current clock, HVAC asset, `domain="devices"`, `source="twin"`, target and
mode. This atomically versions the observation and records its two-hour hold;
renewal withdraws the earlier hold. `release living room hold` releases a uniquely
matched current hold. The submitted account is recorded without asserting who
physically changed a setting. This is not automatic Home Assistant detection.

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run python scripts/smoke_coordinator.py --audit-output /tmp/hirz-coordinator-audit-NEW.json
uv run pytest tests/unit/test_coordinator.py --no-cov
uv run pytest tests/integration/test_coordinator_database.py -m integration --no-cov --tb=short
```

The smoke needs the existing local PostgreSQL credentials, signing key and native
Dogwood. It creates and migrates a uniquely named disposable database, explicitly
clarifies eleven to 23:00, demonstrates all five roadmap checks, verifies the full
signed chain, writes an exclusive private export and verifies it offline. Success
drops the disposable database; failures preserve it with its generated name.
The smoke sends no device commands and does not upgrade the development database.

The migration head is `0006_coordinator_constraints`; the development database stays
on its existing revision until the operator explicitly runs `uv run alembic upgrade
head`. `hirz context HOUSEHOLD_UUID --scope constraints` requires the upgraded schema.
It includes expired/withdrawn history rather than removing evidence. Downgrade is
refused whenever current records, archived records, or constraint audit events
exist. Use `--tb=short` for database tests so third-party traceback locals cannot
print connection parameters. Verification evidence: [item 18](./verification-log.md#item-18--2026-09-21).

## Item 19 durable local execution

Item 19 remains local (`dogwood-local`). The execution migration is
`0007_execution_lifecycle`; the development database is intentionally still on
`0005_execution_attempt`. No command below implicitly migrates or initializes it.
Use the disposable smoke paths for verification before choosing an explicit
operator-run development migration.

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run python scripts/smoke_executor.py --audit-output /tmp/hirz-executor-audit-NEW.json
uv run python scripts/smoke_executor.py --live-demo --audit-output /tmp/hirz-executor-ha-audit-NEW.json
uv run pytest tests/unit/test_executor.py --no-cov
uv run pytest tests/integration/test_executor_database.py -m integration --no-cov --tb=short
```

The default smoke seeds and migrates a uniquely named disposable database, ingests
Registry observations through Pipeline, submits a light request with zero boundary
calls, and launches a separate worker process. It checks verified state and exports
and verifies the signed chain. The live variant uses only the reviewed HA demo
mapping; it queues thermostat/light writes and restoration through Pipeline, leaves
ecobee read-only, and retains the signed export. Success drops the smoke database;
failure prints its retained name. The physical-plug gate remains item 15.

For an already explicitly migrated local database:

```sh
export HIRZ_TWIN_SCENARIO=scenarios/demo-evening.yaml
export HIRZ_ADAPTERS=devices:twin,ev:twin,energy:twin,presence:twin
export HIRZ_SIM_SPEED=1
uv run hirz worker --household HOUSEHOLD_UUID --once
# Omit --once to poll once per wall-clock second.
```

`--database NAME` selects an explicit local database without changing credentials
or migrating it. Twin configuration comes from `HIRZ_TWIN_SCENARIO`; stored explicit
bindings still win over domain defaults. The scenario provides configuration and
initial state, not scenario event execution (item 22). For HA bindings,
`HIRZ_HA_CONFIG=config/homeassistant/adapter-demo.yaml` supplies reviewed entities
and provenance; the private `.env` provides `HA_TOKEN`. Real energy defaults also
require `HIRZ_DELIVERY_CLASS` and `HIRZ_TARIFF_FILE`. Unknown or unavailable adapter
implementations fail closed. The worker validates the stored selected local policy;
this is not production policy activation or AWS enforcement.

Internal callers use `Pipeline.enqueue(action, trusted_principal)`,
`Executor.sweep/rollback` and `PlanService.record/approve/revise/cancel`. Every queued
Action needs an aware command-state deadline. Bounded work also needs an explicit
start and exact `revert`; nonzero EV/battery controls always require a stop. An
immediate unbounded Action may omit its start. Do not modify approved parameters or
reuse an Action ID for a retry. A failed attempt retains its claim permanently.
Explicit rollback uses the signed captured inverse and current policy; restoring a
nonzero EV/battery control also requires an explicit new bounded ending.

Plan approval reserves its derived electricity-plus-wear estimate under a separate
`energy.optimize_cost` grant. Device rules, votes and TTLs still apply. Unknown
per-device estimates remain unknown, and a configured device budget can refuse them.
A refreshing or blocked plan cannot be approved; item 19a supplies durable refresh
below. Actual billing settlement, notification delivery and full scenario wiring
(22) are deferred. Pending notices are records to show the addressed member; no push
or email delivery is claimed.

Restart verifies the twin checkpoint's signed hash and configuration identity, then
resumes its committed simulated time without adding wall-clock downtime. A new twin
configuration requires a separate disposable household/database; do not overwrite
a checkpoint to force compatibility. Due endings precede new openings and survive
pause, cancellation and policy changes. A stopped local worker/database cannot
perform endings until it returns; offline home-owned endings remain item 38a.


## Item 19a: durable local plan refresh

The migration head is `0008_plan_refresh`. Development remains on
`0005_execution_attempt`; only disposable verification databases were migrated.
The migration preserves legacy proposals and audit evidence. A legacy plan needs a
complete replacement workload from an eligible member before further openings;
existing authorized endings remain runnable.

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run python scripts/smoke_refresh.py --audit-output /tmp/hirz-refresh-twin-NEW.json
uv run python scripts/smoke_refresh.py --live-demo --audit-output /tmp/hirz-refresh-ha-NEW.json
uv run pytest tests/unit/test_refresh.py --no-cov
uv run pytest tests/integration/test_refresh_database.py -m integration --no-cov --tb=short
```

Both smokes create isolated databases and launch separate workers for queued and
abandoned-running restart cases. They retain signed exports and verify them offline.
The live variant uses the reviewed HA demo mapping, a declared synthetic thermal
workload, and restores every changed thermostat/light setting through Pipeline;
it leaves ecobee read-only. These checks do not calibrate a real home's thermal
model. A failed run retains its disposable database; use a new audit output path
for each attempt. No command above migrates development data.

`PlanService.record/revise(..., runtime=RuntimeInputs.from_schedule(inputs, schedule))`
requires complete supplied physical/forecast inputs for execution. Internal callers
can request refresh (including plain explicit “change”), update supplied inputs or
read the canonical current Plan through `request_refresh`, `update_inputs` and
`read_current`. `explicit=False` is for trusted automatic triggers, not a consumer
consent shortcut. An explicit eligible member retry names `retry_action_id`; failed
operations otherwise retain exhaustion across plan versions. Inspect held reads and
signed job transitions for blocking reasons. Successful reads clear transient read
failure; conflicts need a relevant change or an explicit request.

The normal worker now polls configured adapters and services refresh with a separate
connection/solver thread while prioritizing endings. `--once` finishes the batch
ready at invocation and one execution sweep; it never waits for a future retry.
`HIRZ_ADAPTERS=devices:ha` and the reviewed HA mapping support HA-only thermal plans;
missing required domains fail closed. Twin price/weather/calendar changes use the
existing configured adapters; live price/weather ingestion remains deferred.
MCP endpoints, companion delivery, AWS and remote CI are not verified here.


## Item 20 consent-gated memory

`hirz.memory.service.MemoryService` is an internal backend contract, documented in
[architecture §5.9](../ARCHITECTURE.md#59-memory). Callers supply a trusted linked
`Principal`, a unique mutation `action_id`, and typed `TurnInput` or `Candidate`
objects. `review(..., proposal_id=..., accept=True|False)` requires the subject's
app principal. Returned refusals carry a canonical Decision and no record. This
is not a public authentication or companion consent workflow.

Run the disposable twin demonstration with the existing Postgres service, local
signing key and native Dogwood, using a **new** private output path:

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run python scripts/smoke_memory.py --audit-output /tmp/hirz-memory-audit.json
uv run pytest tests/integration/test_memory_database.py -m integration --no-cov --tb=short
```

The smoke migrates only a uniquely named disposable database to `0009_memory`,
uses synthetic linked principals, compares pending/rejected/accepted planner
inputs, queues acceptance-driven refresh, starts a separate `hirz worker --once`
process, checks inherited consent and held obsolete work, and exports/verifies the
signed audit chain using an independently supplied key fingerprint. It drops its
database on success and retains it on failure. There are no live HA writes.
Retain the reported audit path privately; it contains identifiers and decisions,
not session transcripts. An empty in-process provider after restart does not lose
Postgres session context or accepted graph preferences.

Development remains on `0005_execution_attempt`. Upgrading development through
0006–0009 is a separate explicit operation (`uv run alembic upgrade head`), never
startup behavior and not performed by these checks. `0009_memory` downgrade
refuses retained session/proposal rows or memory audit events. No automatic
retention cleanup, cloud calls, extraction, other preference types, public memory
CLI or companion UI are included.


## Item 21 Explainer

`uv run python scripts/smoke_explainer.py` uses offline planner facts, validates
templates, rejects a fabricated figure and verifies unchanged canonical planning
fields and serialization/reuse. It initializes no AWS client or credentials.

With local PostgreSQL running and the existing audit key initialized:

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run python scripts/smoke_explainer.py --integration --audit-output /tmp/hirz-explainer-audit.json
```

The output file must be new. The smoke creates and removes a uniquely named
disposable database, applies migrations there, uses the existing synthetic bootstrap,
publishes a plan and queued Decision through the Pipeline, reconstructs the service,
and verifies the signed export independently. The development database is never
upgraded. Keep the private export outside version control.

Internal callers may pass `TemplateExplainer` or `BedrockExplainer` to `Coordinator`
and `RefreshWorker`; omitted providers use templates. The local worker reads
`HIRZ_LLM=off|bedrock` from its process environment, defaulting to `off`. Invalid
values fail configuration. Bedrock uses the standard AWS credential chain and may
incur inference charges when explicitly enabled; item 21 checks use SDK stubs only.
Do not put provider credentials in graph records or narration metadata.

The Explainer's cache is the existing audited Plan/Decision JSON document. Reads do
not generate model text or write replacement narration. A held read may still run
the pre-existing audited freshness detection from item 19a. See
[ADR-012](./adr/ADR-012-explainer.md) for hash inputs, length/figure guards and their
semantic limits. MCP, UI and live Bedrock remain later work; internal scenario execution is described below.

## Item 22 executable evening

Use the existing local PostgreSQL service, `.env` signing key, and pinned native
Dogwood. The runner creates and migrates a uniquely named disposable database;
it does not migrate or seed the development database.

```bash
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run hirz scenario run scenarios/demo-evening.yaml --headless --assert
uv run hirz scenario run scenarios/demo-evening-hourly.yaml --headless --assert
uv run hirz scenario run scenarios/parents-scam-check.yaml --headless --assert
uv run python scripts/smoke_scenario.py --live-demo --artifacts-dir secrets/scenario-runs/ha-new-run
```

The last command requires the existing HA demo service. It uses current time and
normal pacing, changes only the explicitly mapped `light.bed_light`, and requires
Pipeline-authorized restoration. Missing HA or failed restoration fails that gate.
It does not satisfy the physical-plug gate.

Use `--artifacts-dir NEW_DIR` to select a new private evidence directory. Keep
`report.json`, `audit.json` and `public-key.pem` together. The report identifies the
seeded execution policy and the separate simulated preview. Failed databases are
retained by name for diagnosis; remove them only after reviewing their evidence.
Step and unchecked reports do not claim completion. No remote CI dispatch or
public MCP/authentication claim is included.

For machine-readable results, use `--output <new-file>` or the retained
`report.json`: native solver diagnostics can also appear on stdout
([recorded friction](./friction-log.md)).

## Item 23: local MCP transport

The existing `hirz.api.app:app` entrypoint serves `/mcp` and liveness-only `/health`.
Only `what_can_you_do` is registered. Its typed structured result includes the
existing `Speakable` and explicitly says household tools are not connected.
There is no household data in this local preview. Authenticated startup is
documented under item 24 below; supplied credentials in this preview return 503. Exact limits, allowed headers, and the GET 405 decision are in
[ADR-013](./adr/ADR-013-mcp-transport.md#local-boundary).

Use Node 24 for Inspector. With locked Python dependencies installed, start the
standalone server (stop it before starting Compose on the same port):

```sh
uv run --locked uvicorn hirz.api.app:app --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
uv run --locked python scripts/smoke_mcp.py
```

The smoke runs `initialize → tools/list → tools/call` using the official SDK,
asserts protocol `2025-11-25` and no session ID, validates the structured result,
and prints it with a PASS summary (failure exits nonzero). `--url` supports a
separate test app's allocated loopback port; changing only Uvicorn's port does not
change the fixed production allowlist. Tests use `create_app(port=allocated_port)`.

For the existing initialized Compose stack:

```sh
docker compose -f compose.dev.yml up -d --build --wait --wait-timeout 180
uv run --locked python scripts/smoke_mcp.py
```

This check requires no development-database migration, seeding or action. The CI
Python test job runs the same smoke immediately after server startup.

Inspector 2.7.0 uses `--transport http` and `--server-url`. Isolate its state without
changing HOME, and keep authentication enabled:

```sh
inspector_dir=$(mktemp -d)
chmod 700 "$inspector_dir"
export MCP_STORAGE_DIR="$inspector_dir/storage"
export MCP_CATALOG_PATH="$inspector_dir/catalog.json"
export MCP_CLIENT_CONFIG_PATH="$inspector_dir/client.json"
export MCP_INSPECTOR_OAUTH_STATE_PATH="$inspector_dir/oauth.json"
export MCP_INSPECTOR_LOG_DIR="$inspector_dir/logs"
export MCP_INSPECTOR_SECRET_STORE=memory
export MCP_AUTO_OPEN_ENABLED=false
unset DANGEROUSLY_OMIT_AUTH
pnpm dlx @modelcontextprotocol/inspector@2.7.0 --web
```

Open the launch URL containing the generated local token; do not save the token in
repository evidence. Add a Streamable HTTP server with URL
`http://127.0.0.1:8000/mcp`, connect, list Tools, select `what_can_you_do`, and run it
with no inputs. Record the displayed structured result. The web launcher rejects
an ad-hoc server URL combined with `MCP_CATALOG_PATH`, so enter the URL in the UI.
The browser uses Inspector's authenticated backend; no CORS is needed on Hirz.

For CLI checks, use the same temporary state paths, but unset the catalog variable
for the ad-hoc target (the CLI does not need a catalog):

```sh
unset MCP_CATALOG_PATH
pnpm dlx @modelcontextprotocol/inspector@2.7.0 --cli --transport http \
  --server-url http://127.0.0.1:8000/mcp --method initialize --format json
pnpm dlx @modelcontextprotocol/inspector@2.7.0 --cli --transport http \
  --server-url http://127.0.0.1:8000/mcp --method tools/list --format json
pnpm dlx @modelcontextprotocol/inspector@2.7.0 --cli --transport http \
  --server-url http://127.0.0.1:8000/mcp --method tools/call \
  --tool-name what_can_you_do --tool-args-json '{}' --format json
```

Stop Inspector with Ctrl-C and remove only the temporary directory created above
when finished. Inspector is not a project dependency. Focused checks:
`uv run --locked pytest tests/unit/test_mcp.py --no-cov`; full Python coverage uses
the service-free, integration-with-append, then 80 percent report sequence in
`AGENTS.md`. UI verification and all completion evidence are tracked in the
[item 23 log](./verification-log.md#item-23--2026-09-23).

## Item 24: local OAuth

The Compose entrypoint remains the generic preview. To run authenticated local
MCP, use three terminals from the checkout root (port 8000 must be free):

```sh
uv run --locked python scripts/dev_oauth.py init
uv run --locked python scripts/dev_oauth.py serve
```

```sh
uv run --locked uvicorn --factory hirz.api.app:create_local_oauth_app \
  --host 127.0.0.1 --port 8000 --no-access-log
```

`init` creates only a missing, separate RSA-2048 dev OAuth key in the regular,
nonsymlink `0600` `.env`. It preserves unrelated entries, refuses malformed or
empty existing keys, and never uses/replaces the audit key. `serve` never creates
a key. Keep access logging disabled: authorization URLs and callbacks contain
short-lived grant material. This is a **simulated login**, never proof of a real
person's identity. Its choices come from the canonical seeds; selecting one does
not seed the database or create a link. Normal startup registers no household
or diagnostic tool. No migration or development seed is needed for this item.

The only client is `hirz-dev-sdk`, public (`token_endpoint_auth_method=none`), with
callback `http://127.0.0.1:8765/callback`. Preload that static client information
in SDK token storage, then use its OAuthClientProvider. Request canonical resource
`http://127.0.0.1:8000/mcp`, an exact callback, S256, and supported scopes. An omitted
scope requests `hirz:read`; Approve grants exactly the displayed scopes. Deny
returns `access_denied`. No dynamic registration or revocation endpoint exists.
See [ADR-014](./adr/ADR-014-local-oauth.md) for lifetimes, request limits, rotation,
key-cache behavior and the approved in-memory dev-state exception.

For a reproducible full SDK flow, run:

```sh
uv run --locked python scripts/smoke_oauth.py
uv run --locked python scripts/smoke_oauth.py --browser
```

The smoke allocates loopback ports and a uniquely named disposable database,
explicitly migrates/seeds only that database, and starts separate issuer and MCP
processes with ephemeral signing material. A third listener receives SDK callbacks.
It preloads static registration, then lets the SDK discover PRM/issuer metadata,
generate PKCE, receive consent, exchange the code, call its test-only `oauth_probe`
and refresh automatically. Mom links to both homes with different roles. The smoke
also denies consent, checks a wrong audience returns 401, and compares the complete
seeded graph/policy/history plus empty audit/action tables after the requests.
It prints only redacted identities/status, never codes, tokens or keys. Successful
runs drop their database; failures retain the uniquely named database using the
existing disposable-database procedure. Development is untouched.

`--browser` prints a local callback-harness root URL. Open it to reach the SDK's
live consent page; select **Mom — Malik's home**, check the displayed scopes, and
Approve. The page shows callback completion and the terminal reports SDK success.
The second household links automatically; when the terminal requests Deny, reopen
the same root URL and click Deny. The callback page reports no access was granted.
The ordinary smoke drives these same HTML forms with HTTP for CI. Browser checks
must actually run before claiming visual verification.

Anonymous Inspector regression continues to use the item 23 commands above;
Inspector OAuth registration is deferred. Supplied credentials in generic-preview
mode return 503. Authenticated mode returns 401 with the root PRM challenge for
invalid/missing required credentials; valid insufficient scopes return 403 with
`insufficient_scope`. Unmapped/child members get generic onboarding only, with
403 for protected calls. Required keys or database unavailable returns 503.
Anonymous generic onboarding does not require either dependency.

Focused checks:

```sh
uv run --locked pytest tests/unit/test_oauth.py tests/unit/test_mcp.py --no-cov
uv run --locked pytest tests/integration/test_oauth_database.py -m integration --no-cov
```

Use the ordinary service-free/integration/combined-coverage sequence for the full
suite. The Python CI job runs `smoke_oauth.py`; remote CI and production linking
are not implied by local success.


## Item 25 local household tools

The implemented contract and boundaries are in [ADR-015](./adr/ADR-015-household-tools.md)
and [the tool catalog](./tool-catalog.md). Migrations `0010_household_tools` and
`0011_planning_objective` are explicit; startup never migrates. Development remains on `0005_execution_attempt`.
Use a disposable database for item 25 verification, not the development database.
The existing authenticated factory requires the local audit signing key and native
Dogwood: policy validation/compilation happens at startup, and a changed stored
policy requires restart. OAuth issuance remains a separate local process.

```sh
export HIRZ_DOGWOOD="$PWD/.tools/dogwood"
uv run --locked python scripts/smoke_household_tools.py --audit-output /tmp/household-audit.json
```

Choose an unused output path. The script creates two disposable twin households,
starts separate OAuth/MCP processes, uses SDK PKCE and real tools/list/tools/call,
starts and restarts the worker, tests durable objective changes and fresh consent,
checks configured profiles per device, tests a same-second revision/approval refusal,
restarts MCP for a durable retry, and independently verifies a signed audit export.
The smoke extends its temporary evening fixture to 08:00 because the original
scenario ends at 07:00; it does not alter the main scenario. Success drops its
scratch database; failures retain it for diagnosis. Audit files are private.
Initial explicitly labeled verified-channel fixtures are permitted only during
that disposable bootstrap; all later case changes require Pipeline decisions.

For manual first-plan work, configure `HIRZ_TWIN_SCENARIO` with explicit scenario
inputs covering the requested horizon and run the existing `hirz worker` command.
Tonight/overnight/tomorrow_morning end at the next household-local 08:00; next_24h
needs a full 24 hours of configured inputs. Missing coverage fails; no fabricated
plan substitutes for missing inputs. The worker continues bounded device endings
while preparation/refresh runs. Security and real contact delivery remain unavailable.

For household profiles, export `HIRZ_PROFILES_FILE` to an explicitly authored YAML
file before starting authenticated MCP. Its shape is `households` → household UUID
→ profile name → `settings` list. Names are `recovery_morning`, `guests_arriving`,
`night` and `away`. Each of 1–20 entries has `action` (`set_temperature`,
`turn_on_light` or `turn_off_light`) and `room`; only temperature settings also
require `temperature_f` (66–76). No profiles or device settings are installed by
default. Configuration is validated at startup and changes require restart;
approvals already issued retain their frozen settings. The smoke writes its own
explicit temporary twin configuration. Every device is separately checked and
may need approval or be blocked; later automation may change an immediate setting.

`get_household_plan` accepts `objective` plus `request_id`; use `cheapest`,
`most_comfortable` or `greenest`. The worker computes the approved priorities from
existing explicit inputs. Greenest reduces grid electricity, without an emissions
claim. A changed objective holds the old plan and requires fresh consent for its
replacement; reads preserve the choice and fixed horizon.

The reusable host is `hirz.host.headless.HeadlessHost` (Strands pinned at 1.57.0).
Its turn method preserves conversation context, discovers actual MCP tools and
holds a proposed commitment until `confirm(approved=True)` is explicitly called.
Selection tests use that host with tool execution canceled; SDK smoke proves execution.
To rerun the verified live selection gate, provide working US Bedrock credentials/model
access and append `--live-selection --budget-ledger /tmp/household-bedrock-budget.json`
to the smoke command. Reuse the **same budget file across retries**; never reset it
to bypass the author-approved aggregate $2.00 ceiling. Check current pricing before
any later invocation. The ledger reserves native-counted input and maximum output
cost before each wire attempt, including retries, with no heuristic fallback.
Missing credentials/counting support, exhaustion or any wrong selection keeps the
gate pending. The adjacent `.selection.json` records outcomes and actual token
usage; retain or move an existing report before rerunning (the report refuses overwrite).
Use `AWS_PROFILE=hirz` for the supplied profile. The runtime counter requires
the foundation model ID without `us.`, while Converse requires the US inference
profile; both have now succeeded. The separate Mantle denial does not block this
route. AWS enables model subscriptions on first use; there need not be an
"enable access" button, and pre-invocation agreement status alone does not prove
runtime access is blocked. Retain the existing ledger across diagnostic probes
and full runs. See the
[ADR amendment](./adr/ADR-015-household-tools.md#accesscounting-amendment--2026-09-23).

```sh
uv run --locked pytest --tb=short
uv run --locked pytest -m integration --cov=hirz --cov-append --tb=short
uv run --locked coverage report --fail-under=80
uv run --locked ruff check .
uv run --locked mypy hirz/ scripts/ alembic/
uv run --locked ruff format --check .
```

The first suite includes native local policy conformance when Dogwood is configured.
If sandbox cache access fails, set `UV_CACHE_DIR=/tmp/hirz-uv-cache`; local PostgreSQL
and loopback process verification require local network access. Item 26 latency and
full isolation gates remain separate. Retained run evidence is in the verification log.

## Independent add-on checks (item 25a)

The [addon-check repository](https://github.com/BashaarJavaid/addon-check) is a
separate Node 24/TypeScript checkout; its README owns the generic CLI contract,
synthetic fixtures and publication procedure. [ADR-016](./adr/ADR-016-add-on-conformance-checker.md)
records the scope and Amazon/MCP authentication distinction. Passing scoped checks
is not Amazon certification.

Build its locked dependencies (`npm ci && npm run build` in that checkout), then
run from Hirz with Node 24 on PATH and native Dogwood configured:

```sh
HIRZ_LLM=off uv run --locked python scripts/smoke_household_tools.py \
  --audit-output /private/tmp/hirz-conformance-audit-NEW.json \
  --conformance-cli ../addon-check/dist/cli.js
```

The audit and adjacent `.conformance.json` report paths must both be new. The smoke
creates disposable households, performs existing SDK/worker/restart assertions,
then invokes the built checker with `--require-complete`. Explicit cases cover all
twelve tools and reuse durable request IDs. Only context/onboarding are timed;
context gets missing/malformed-token probes. Cases are transient and private,
the bearer is a subprocess environment variable, and the report has no payloads.
The smoke independently verifies its signed audit export after the checker returns.
The developer database is neither migrated nor reset. Do not add live selection
or reset the retained Bedrock budget ledger for this gate. A failure retains its
disposable database according to the existing smoke procedure.

The conformance CI job uses the same path with a full checker commit SHA, Node 24,
npm's lockfile and native Dogwood. It initializes and cleans up only its runner's
Compose project. The checker measures two tools; the full tool latency/isolation
suite remains item 26. See the [evidence log](./verification-log.md#item-25a--2026-09-23)
for publication state and actual runs.

## Authenticated tool budget and isolation (item 26)

Item 26 isolation and item 26b latency are complete following author review on
2026-09-24 ([closure](./verification-log.md#closure--2026-09-24)). Both scenarios
pass the raw authenticated JSON-RPC `tools/call` round-trip gate for the local
authenticated MCP surface on the Linux CI runner, with SDK references reported
separately; AWS ingress, cold start and Alexa host overhead remain item 38.
Linux CI is the gate of record; local runs are diagnostic because macOS with
PostgreSQL inside Docker Desktop produces multi-second disk outliers.

Latency jobs stay on `workflow_dispatch`; pushes and pull requests run ordinary
CI, including isolation. **Dispatch CI once before closing any roadmap item that
changes the pipeline, tools, executor, refresh or storage, and once before
submission; record each run in the evidence log.** Open the repository's
**Actions → CI → Run workflow**, select the branch, and click **Run workflow**.
This runs both latency matrix jobs alongside the ordinary jobs. See the
[closure amendment](./adr/ADR-017-tool-latency-and-isolation.md#closure-amendment--2026-09-24).

To compare a private local `report.json` with a CI run's payload-free timing
summary, first match the commit, scenario and measurement protocol; distinguish
raw round-trip gate values from the separate SDK references. Compare the same
case and pooled-tool rows, sample counts, minimum, median, nearest-rank p95 and
maximum, retaining every sample and the unchanged 250 ms threshold. Record the
platform/PostgreSQL environment and CI run link beside the comparison in the
evidence log; an SDK-timed historical run is not directly comparable to the raw
server protocol. Private local reports remain private; CI does not upload raw
household reports. The retained same-commit `0dc1ccf` Time-of-Day comparison had
three failing cases on CI versus 14 locally ([evidence](./verification-log.md#full-gate-results-for-0dc1ccf--2026-09-23)).

[ADR-017](./adr/ADR-017-tool-latency-and-isolation.md) owns the approved protocol.
Use the existing local PostgreSQL service, `.env` and native Dogwood. The runner
creates disposable databases and starts loopback OAuth/MCP and separate worker
processes. Bedrock stays off; development migrations remain manual.

The benchmark's disposable databases explicitly migrate through
`0012_budget_indexes`. It adds grant-reference and budget-ledger indexes only;
rollback to 0011 removes those indexes without erasing evidence. Startup never
migrates, and this task leaves the development database on 0005.

Rebuild with `scripts/build_dogwood.py` before this gate: MCP requires the private
`dogwood-helper` beside the configured `HIRZ_DOGWOOD` executable (the same path
with `-helper` appended). Startup prepares its policies; shutdown kills/reaps it.
A helper failure requires restarting MCP; it never falls back to cached decisions
or the one-shot CLI. The build retains the unmodified CLI for native equivalence
checks, then applies the reviewed two-line Clone patch for the helper. Both use
the existing pinned Rust/Cargo dependency versions.

```sh
HIRZ_LLM=off HIRZ_DOGWOOD="$PWD/.tools/dogwood" uv run --locked python scripts/smoke_tool_budget.py \
  --mode all --artifacts-dir /private/tmp/hirz-tool-budget-NEW
uv run --locked pytest tests/latency -m latency --no-cov -s
uv run --locked pytest tests/integration/test_mcp_isolation.py -m integration --no-cov
```

The CLI requires a new artifact directory; `--mode latency` or `--mode isolation`
runs one gate separately. `all` is the default. Run latency without competing test
or benchmark processes. The explicit `latency` marker excludes it from the normal
suite and coverage; never omit `--no-cov` from a timing run. Set
`HIRZ_BUDGET_ARTIFACTS` to a new parent directory to retain pytest reports in one
subdirectory per energy scenario. CI sets `HIRZ_BUDGET_SCENARIO` to select one of
`demo-evening` or `demo-evening-hourly` in each isolated 75-minute matrix job;
the default pytest invocation and CLI still cover both.

Private mode-0600 reports and signed audit exports live in a mode-0700 directory.
The report retains all raw samples, per-case/per-tool summaries, local interaction
and startup observations, software/platform information and row counts. Partial
samples survive an assertion failure. Failed disposable databases remain available
for diagnosis; successful runs drop only their disposable databases. Never upload
these household reports or exports as public CI artifacts. The dedicated CI job
publishes a payload-free timing summary and cleans up its own services.

The parents fixture remains unchanged in capability. The additional explicitly
labeled disposable home copy exists only for symmetric foreign plan, constraint
and approval probes. All runtime records use Pipeline. These gates concern local
authenticated tools and simulated devices; AWS cold start, production linking,
Alexa voice latency and real phone/security execution remain separate work.

## Item 27: MCP App cards

Use Node 24 and the locked workspace. Build cards before authenticated local startup
or Python distribution builds:

```sh
pnpm install --frozen-lockfile
pnpm --filter mcp-app build
uv build
```

The five generated files in `hirz/mcp/ui/` are ignored and included in the wheel/sdist.
Authenticated startup fails on missing/incomplete assets; generic onboarding has no
asset prerequisite. Docker builds them in its Node stage. Static resource reads are
anonymous and carry no household state. Tool calls retain OAuth and existing scopes.
No migration is added. Keep the development database unchanged for card verification.

Optional `HIRZ_CARD_EVIDENCE_FILE` is a startup YAML file with explicit household
mappings. Use the real retained file hash and the reviewed household/profile choice:

```yaml
households:
  "<household UUID>":
    results_file: /absolute/path/to/scripts/backtest-data/results.json
    sha256: "<sha256 of that exact file>"
    profile: comed_time_of_day
    household_variant: solar_battery_ev
    wear_per_internal_kwh: 0.01
```

This example is a schema illustration, not an inferred mapping for a household.
Missing, invalid or mismatched mappings yield unavailable extrapolation. Files are
loaded once; restart after a reviewed change. The card labels plan estimates and
backtest extrapolation separately and retains negative values.

For browser checks, check out upstream ext-apps v2.0.0 at commit
`352f6ced4d80772e92b4e7a311854481a8d65b04` in `.tools/ext-apps-v2` (or set
`HIRZ_REFERENCE_HOST` to that checkout). The builder verifies its commit and refuses
renderer/bridge modifications. No upstream source changes are needed:

```sh
pnpm --filter mcp-app exec node reference-host.mjs
HIRZ_LLM=off uv run --locked python -m scripts.smoke_cards --artifacts-dir /tmp/new-card-fixtures
HIRZ_CARD_FIXTURES=/tmp/new-card-fixtures/fixtures.json pnpm --filter mcp-app test:browser
```

The scorecard screenshot selects one actual denied action for stable counts;
whole-window count semantics remain covered by PostgreSQL tests. The fixture smoke
uses disposable twin households, records all runtime changes
through Pipeline, and independently verifies private audit exports. Its fixtures
confer no security authority. For a real authenticated reference-host browser call,
install the pinned Playwright Chromium and run:

```sh
pnpm --filter mcp-app exec playwright install chromium
HIRZ_LLM=off uv run --locked python -m scripts.smoke_cards --artifacts-dir /tmp/new-card-live --browser-test
```

The optional `--serve` relay binds loopback 8082, accepts only the test origin
`http://localhost:8080`, holds OAuth tokens server-side and fixes the household in
`/home/mcp` or `/parents/mcp`. The unchanged host runs on 8080 with its sandbox on
8081. Production guards are unchanged. Stop the owned processes after manual use.

Generate/review baselines only in the pinned Linux Playwright image used by CI:
`mcr.microsoft.com/playwright:v1.57.0-noble@sha256:3bed4b1a12f2338642f3d8cba28e291deef3c66bd4a964bbeb3e57bbff511dbd`.
Mount the checkout at `/work` and the private fixture directory read-only at
`/fixtures`; run from `/work/apps/mcp-app` with `HIRZ_CARD_FIXTURES=/fixtures/fixtures.json`
and `CI=1`, using `node node_modules/@playwright/test/cli.js test`. Add
`--update-snapshots` only for an intentional, reviewed visual change. The fourteen
committed PNGs contain labeled synthetic data, not credentials or private case IDs.
Retain private fixture/audit artifacts locally; CI publishes only payload-free
summaries. Initial screenshot review and the authenticated CI latency/isolation
workflow_dispatch gates remain required before closing item 27.
