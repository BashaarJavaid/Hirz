# Friction Log

Every friction point hit while building Hirz against a third-party tool, API, SDK, doc, or CLI. Devpost awards up to a 10 percent judging bonus for these, applied at Stage One, so this is the cheapest score in the project. Entries are facts from a session: the doc URL, the exact error text, the date. Nothing invented, nothing padded. A short log of real entries beats a long one.

**Rule:** log at the moment friction happens, not at the end of the session. Trigger: a tool did not do what its docs said, cost more than about 15 minutes, or forced a workaround. Fields are the ones Devpost requires. Severity: `Blocker` (could not proceed without a workaround), `Major` (lost more than an hour or changed the design), `Minor` (annoyance, documented anyway).

Candidates are things expected to bite that have not been hit yet; they move up when they actually happen, with real steps and real output, or get deleted.

---

## Entries

| # | Date | Tool | Task | Steps taken | Expected | Actual | Severity | Workaround | Suggestion |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-17 | Alexa+ MCP Toolkit / simulator | Test account linking and MCP App rendering on the real Alexa+ surface | Read the docs ("Category SDK and MCP Toolkit are available to select partners only," [MCP Toolkit overview](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-overview.html), checked 2026-09-16); posted the question on the hackathon forum | Either toolkit/simulator access for participants, or an explicit confirmation there is none | Organizer reply, 2026-09-17: "No, there is no way for participants to get access to the toolkit or simulator. A self-built simulator or other front end for demoing are certainly options though!" | Minor | None needed — ADR-007 already committed to a self-built emulated host (the Hirz Simulator) as the primary demo surface before this answer; the reply confirms that path is the one Amazon expects, it doesn't change it | Ship toolkit/simulator access for hackathon participants (tracked below) |
| 2 | 2026-09-17 | Homebrew in the agent filesystem sandbox | Inspect and install Phase 0 tooling | Ran Homebrew inventory commands; see [Homebrew filesystem and cache settings](https://docs.brew.sh/Manpage) | Read installed tool versions | `Error: Operation not permitted @ dir_s_mkdir - /Users/bashaarjavaid/Library/Caches/Homebrew`; disabling API use instead attempted a tap and failed with `fatal: could not create work tree dir '/opt/homebrew/Library/Taps/homebrew/homebrew-core': Operation not permitted` | Minor | Ran the already-authorized installation through sandbox escalation; uv, pnpm, and Node 24 installed successfully. This was a sandbox permission limitation, not a Homebrew defect. | Document that inventory commands can need writable cache or tap directories in restricted environments |
| 3 | 2026-09-17 | pnpm / typescript-eslint | Resolve compatible scaffold tooling | Added latest stable tooling, then ran `pnpm peers check`; see [typescript-eslint dependency requirements](https://typescript-eslint.io/users/dependency-versions/) | A mutually compatible TypeScript/linter toolchain | `✕ unmet peer typescript`, `Installed: 7.0.2`, `">=4.8.4 <6.1.0"` required by `typescript-eslint@8.70.0` | Minor | Selected TypeScript 6.0.3, pinned it exactly, and reran the peer check: `No peer dependency issues found` | Surface the supported TypeScript range alongside installation instructions |
| 4 | 2026-09-17 | pnpm exact dependency saving | Pin Node type declarations | Used `pnpm add -DwE` with `@types/node@24`, then `@types/node@24.13.5`; see [save-exact](https://pnpm.io/cli/add#--save-exact--e) | An exact direct dependency as requested by `--save-exact` | The manifest retained `"@types/node": "^24.13.5"` after both commands; no CLI error was emitted | Minor | Set `"24.13.5"` explicitly in the manifest and regenerate the lockfile | Make `--save-exact` behavior consistent when a version is supplied explicitly |
| 5 | 2026-09-17 | FastAPI / Starlette TestClient | Test the Phase 0 liveness endpoint with the approved httpx dependency | Followed the [FastAPI testing guide](https://fastapi.tiangolo.com/tutorial/testing/) using FastAPI 0.141.1, Starlette 1.6.0, and httpx 0.28.1 | A supported TestClient using the guide's httpx installation | Tests passed but emitted ``StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.`` and `DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.` | Minor | Exercise the ASGI app directly with the already-approved httpx.AsyncClient and ASGITransport; no new dependency | Update the testing guide to match the current TestClient dependency transition |

| 6 | 2026-09-17 | Local tooling in the agent sandbox | Inspect Compose and verify item 3 | Ran [docker compose ps](https://docs.docker.com/reference/cli/docker/compose/ps/), [uv sync](https://docs.astral.sh/uv/reference/cli/#uv-sync), and pytest's existing localhost WebSocket checks | Read local service state, synchronize dependencies, bind a disposable test socket | `permission denied while trying to connect to the docker API at unix:///Users/bashaarjavaid/.docker/run/docker.sock`; `failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`; `PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted` | Minor | Authorized sandbox escalation allowed Compose inspection, uv synchronization, and the tests to pass. These were sandbox restrictions, not upstream defects. | Make daemon, cache, and loopback requirements explicit in restricted development environments |

| 7 | 2026-09-17 | GitHub CLI in the agent network sandbox | Inspect repository settings while planning Phase 0 CI | Ran [gh repo view](https://cli.github.com/manual/gh_repo_view) and [gh api](https://cli.github.com/manual/gh_api) for Actions permissions | Read repository metadata and Actions settings | `error connecting to api.github.com` followed by `check your internet connection or https://githubstatus.com` | Minor | Read-only sandbox escalation succeeded; confirmed public repository, main default branch, and Actions enabled. This was a sandbox network restriction, not a GitHub defect. | Distinguish network sandbox denial from upstream connectivity failures |

An earlier entry dated 2026-09-15 about unreachable design-guide links was removed on 2026-09-17: the pages loaded on 2026-09-16, and the entry had no URL and no HTTP status, so it did not meet this file's own rule.

| 8 | 2026-09-18 | GitHub lookup in the agent network sandbox | Fetch the pinned Dogwood CLI source for item 7 | Cloned [Dogwood revision 996d756](https://github.com/dogwood-policy/dogwood/tree/996d756de1013b7ae209a14f566a80375a59f2f0) | Read upstream source | `fatal: unable to access 'https://github.com/dogwood-policy/dogwood.git/': Could not resolve host: github.com` | Minor | Authorized read-only network escalation succeeded; checked out the exact revision in temporary storage. This is a sandbox DNS restriction, not a Dogwood defect. | Distinguish sandbox network failures from upstream defects |

| 9 | 2026-09-18 | Dogwood source build | Build the pinned native CLI reproducibly | Ran Cargo with `--locked` at [revision 996d756](https://github.com/dogwood-policy/dogwood/tree/996d756de1013b7ae209a14f566a80375a59f2f0) | Use an upstream dependency lock | `error: cannot create the lock file /private/tmp/hirz-item7-dogwood/Cargo.lock because --locked was passed to prevent this` | Minor | Built once without `--locked`, retained the generated `scripts/dogwood.Cargo.lock`, and use it for subsequent native/container builds. The source revision has no lockfile; this is packaging friction, not a temporal-semantics failure. | Publish a CLI dependency lock alongside pinned releases |

Item 8 follow-up to entry 6 (2026-09-18): `uv run --locked ruff format` hit:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

Using `UV_CACHE_DIR=/private/tmp/hirz-uv-cache` let the same command pass without
escalation. This is the same sandbox restriction, not a new upstream defect;
the [uv CLI reference](https://docs.astral.sh/uv/reference/cli/) is the tool reference.
The full pytest run also hit entry 6's existing loopback restriction:
`PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted`.
The suite was rerun with sandbox escalation for those disposable local sockets.

Item 9 follow-up to entries 6 and 8 (2026-09-18): adding the approved
`rfc8785==0.1.4` dependency first hit the same uv cache permission error quoted
above. A temporary cache then reached the sandbox DNS restriction:

```text
error: Request failed after 3 retries in 4.1s
  cause: Failed to fetch: `https://pypi.org/simple/pydantic/`
  cause: error sending request for url (https://pypi.org/simple/pydantic/)
  cause: client error (Connect)
  cause: dns error
  cause: failed to lookup address information: nodename nor servname provided, or not known
```

Authorized escalation installed the pinned dependency and updated the lockfile.
The first PostgreSQL test attempt hit `connection to server at "127.0.0.1", port 5432 failed: Operation not permitted`;
the disposable-database tests and local socket tests passed with escalation.
These are repeat environment restrictions, not new upstream defects. References:
[uv CLI](https://docs.astral.sh/uv/reference/cli/) and the
[approved canonicalizer](https://github.com/trailofbits/rfc8785.py).

Item 11 follow-up to entries 6 and 8 (2026-09-18): the existing sandbox restrictions
recurred:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
permission denied while trying to connect to the docker API at unix:///Users/bashaarjavaid/.docker/run/docker.sock
```

Using `UV_CACHE_DIR=/private/tmp/hirz-uv-cache` resolved the cache restriction;
authorized escalation allowed local PostgreSQL and socket verification. No Docker
service change was needed. These are repeats of the existing environment friction,
not new upstream defects. References: [uv CLI](https://docs.astral.sh/uv/reference/cli/)
and [Docker context/socket configuration](https://docs.docker.com/engine/manage-resources/contexts/).

Item 12 follow-up to entries 6 and 8 (2026-09-19): the same default uv cache
restriction recurred:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

`UV_CACHE_DIR=/private/tmp/hirz-uv-cache` and locked offline runs resolved it.
Local PostgreSQL tests also required sandbox escalation. The first escalated
attempt then reported the genuinely stopped prerequisite:

```text
connection failed: connection to server at "127.0.0.1", port 5432 failed: could not receive data from server: Connection refused
```

`docker compose -f compose.dev.yml ps --all` returned no services. Starting only
PostgreSQL with `up -d --no-deps --wait postgres`, preserving its volume, enabled
the disposable-database checks. These repeat environment restrictions and a stopped
local service are not a new upstream defect or a new scored friction entry.
References: [uv CLI](https://docs.astral.sh/uv/reference/cli/) and
[Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/).

Item 13 follow-up to entries 6 and 8 (2026-09-19): local Compose inspection
and the full suite again encountered the same sandbox restrictions:

```text
permission denied while trying to connect to the docker API at unix:///Users/bashaarjavaid/.docker/run/docker.sock
PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted
```

Authorized escalation allowed service inspection and disposable socket/database
checks; PostgreSQL was already healthy and no service change was required.
The isolated wheel install's first offline attempt also reported:

```text
error: No solution found when resolving dependencies
  cause: Because rfc8785 was not found in the cache and hirz==0.0.0 depends on rfc8785==0.1.4, we can conclude that hirz==0.0.0 cannot be used.
```

An authorized online install into a disposable `/private/tmp` environment supplied
that existing dependency; the source manifest/lockfile were unchanged. These are
repeat environment/cache restrictions, not upstream defects or new scored entries.
References: [uv offline behavior](https://docs.astral.sh/uv/reference/cli/#uv-pip-install--offline)
and [Docker Compose ps](https://docs.docker.com/reference/cli/docker/compose/ps/).

## Item 14 energy research — 2026-09-20

| # | Date | Tool / service | Goal | Steps / reference | Expected | Actual | Severity | Workaround | Feature request |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 2026-09-20 | ComEd day-ahead chart feed | Read credential-free day-ahead history safely | Inspected [price page](https://hourlypricing.comed.com/live-prices/) and its [2026-08-01 request](https://hourlypricing.comed.com/rrtp/ServletFeed?type=daynexttoday&date=20260801) | A documented timestamped data contract | HTTP 200 begins `[[Date.UTC(2026,7,1,0,0,0), 2.8]`; the page calls `eval(series)` and the [public API documentation](https://hourlypricing.comed.com/hp-api/) covers five-minute/current-hour feeds, not this format | Minor | Retain raw responses/page and parse only a restricted grammar; never execute JavaScript | Publish a versioned JSON day-ahead endpoint with UTC timestamps, units and publication time |
| 11 | 2026-09-20 | ComEd day-ahead DST labels | Map Chicago hours to unambiguous intervals | Read [fall 2025-11-02](https://hourlypricing.comed.com/rrtp/ServletFeed?type=daynexttoday&date=20251102) and [spring 2026-03-08](https://hourlypricing.comed.com/rrtp/ServletFeed?type=daynexttoday&date=20260308) | Distinguishable repeated hours | Fall HTTP 200 includes `[Date.UTC(2025,10,2,1,0,0), 3.3]` once; spring skips hour 2. The fall label supplies neither offset nor fold; no error response or upstream guarantee was observed | Minor | Interpret chart labels as local hours; omit both ambiguous fall intervals and report a two-hour gap | Return UTC timestamps or explicit offset/fold per row |
| 12 | 2026-09-20 | ComEd delivery PDF | Pin the correct billed-distribution vintage | Reviewed [delivery guide](https://www.comed.com/cdn/assets/v3/assets/blt3ebb3fed6084be2a/blt7904befea93c3525/6a74ab1af8608b565710881f/A_Guide_to_the_Retail_Customer_s_Billed_Delivery_Service_Charges.pdf) pages 1–2 as rendered images and extracted text | One effective-period heading | Tables retain “Resultant Charge beginning with April 2026” alongside “June 2026”; no HTTP error on direct download | Minor | Preserve PDF/hash and record the June label, older heading and calendar-month approximation explicitly in the tariff metadata | Publish unambiguous effective-from/through fields with each billed-charge table |

Sandbox follow-up to entry 8: the initial public-PDF download failed with exact
`curl: (6) Could not resolve host: www.comed.com`; authorized network escalation
succeeded. The browsing tool separately returned `Internal Error ()` for the same
PDF URL, while direct curl succeeded. Neither is evidence of a ComEd outage.

## Item 15 HA demo contract — 2026-09-20

| # | Date | Tool / service | Goal | Steps / reference | Expected | Actual | Severity | Workaround | Feature request |
|---|---|---|---|---|---|---|---|---|---|
| 13 | 2026-09-20 | Home Assistant 2026.9.2 demo climate | Verify the planned 72 °F single-target write on ecobee without mode changes | Read `/api/states/climate.ecobee` and `/api/config`; checked the [climate contract](https://developers.home-assistant.io/docs/core/entity/climate/) and [REST API](https://developers.home-assistant.io/docs/api/rest/) | Planning assumed a scalar target on ecobee | HTTP 200: `state: heat_cool`, `target_temp_low: 70`, `target_temp_high: 75`, `supported_features: 442`; no scalar `temperature` or per-state `temperature_unit`. No upstream error occurred; the planning assumption was wrong | Minor | Author approved ecobee read-only and `climate.heatpump` at 72 °F in its existing heat mode; fetch the instance unit system from `/api/config` | Include a single-target/ranged-target example and the instance-unit lookup in REST climate examples |
| 14 | 2026-09-21 | SciPy 1.18.0 / HiGHS timed MILP | Reproduce the annual planner study exactly | Repeated the archived study with concurrent annual replications, `time_limit=5.0` and `mip_rel_gap=0.001`; see the [milp contract](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html) | Identical retained schedules apart from measured timing | One solve returned `Time limit reached. (HiGHS Status 13: Time limit reached)` with gap 0.0036811719670481616; its repeat reached optimal status with gap 0.0007238771401596331, changing the schedule and failing exact reproduction. Investigating and repeating the full study took more than 15 minutes. This is documented timeout behavior, not a solver defect | Minor | Remove concurrent study solves and compression during timed solves; load the comparison archive after solving. Preserve the five-second limit, strict comparison and both diagnostic outcomes; record the subsequent verification in the [evidence log](./verification-log.md#independent-reproduction-failure-and-isolation--2026-09-21) | Clarify beside the determinism note that wall-time limits can select different incumbents under different machine loads |

The existing sandbox restriction from entry 6 recurred: `permission denied while
trying to connect to the docker API at unix:///Users/bashaarjavaid/.docker/run/docker.sock`
and uv's `Operation not permitted (os error 1)` opening its cache. Authorized
escalation started the existing HA service and ran the checks; no upstream outage
or new defect is claimed.

## Item 16 environment follow-up — 2026-09-20

The previously recorded sandbox/cache restrictions recurred (Minor; no new scored
upstream defect). The initial uv invocation returned:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

Using a writable temporary `UV_CACHE_DIR` plus the existing locked environment
allowed source checks. Existing socket/database tests required authorized local
access after these exact errors:

```text
PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted
psycopg.OperationalError: connection is bad: connection to server at "127.0.0.1", port 5432 failed: Operation not permitted
```

The temporary cache did not contain all wheel dependencies; offline installation
reported `Because websockets==17.1 needs to be downloaded from a registry`.
Authorized access to the existing uv cache completed the same **offline** install
into the disposable venv; no dependency or lockfile changed. No service restart,
network fetch, or upstream outage is claimed. References:
[uv cache configuration](https://docs.astral.sh/uv/concepts/cache/) and
[offline installation](https://docs.astral.sh/uv/reference/cli/#uv-pip-install--offline).

Phase 2 cleanup batch 1 follow-up to entry 6 (2026-09-20, Minor): the initial
`uv run pytest` again returned:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

Authorized sandbox escalation used the existing cache successfully; this repeats
the recorded sandbox restriction, not an upstream defect. Reference:
[uv cache configuration](https://docs.astral.sh/uv/concepts/cache/).

Doorbell approval correction follow-up to entry 6 (2026-09-20, Minor): the
initial regression command hit the same sandbox cache restriction:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

Authorized sandbox escalation used the existing cache and local PostgreSQL;
no upstream defect or dependency change. Reference:
[uv cache configuration](https://docs.astral.sh/uv/concepts/cache/).

## Candidates (not yet hit)

- No documented way for an add-on to receive Alexa-side context (device modality, locale, timezone) or to be invoked proactively.
- AgentCore Runtime serves the Protected Resource Metadata at a path-shaped URL under the runtime ARN; whether Alexa's client follows `resource_metadata` from `WWW-Authenticate` or only looks at the origin root is unverified.
- AgentCore Policy temporal quotas (25 policies per engine, 3 operators per policy, 24-hour window) versus a constitution's `ask` classes; changing temporal policies returns 409 on open sessions. Designed around with one generic temporal permit per TTL.
- AgentCore Runtime cold start: a new session is a fresh microVM, so the first Alexa call after an idle gap cannot meet the 500 ms round-trip requirement; measure and record the figure in Phase 7 (`ROADMAP.md` item 38). Related: the Runtime exposes only the invocation path, so the companion API and Ring webhooks needed a separate always-on service (ADR-008).
- No local library performs Cedar automated-reasoning analysis (always-allow, never-satisfiable); `cedarpy` evaluates only. The analysis exists in AgentCore Policy via `validationMode` on create/update, so it is AWS-mode only.
- Ring sandbox: webhook signature details and synthetic-device event coverage; whether sandbox credentials are issued without a physical Ring device (the getting-started page lists "at least one Ring device for testing" as a prerequisite); partner-initiated OAuth is invitation-only, so the linking flow is the Ring-driven HMAC-nonce pattern.
- Smartcar sandbox versus Tesla Fleet API onboarding cost for a non-fleet developer.
- Home Assistant long-lived access tokens cannot be scoped (a token inherits the creating user's full permissions; [feature request open since 2020](https://community.home-assistant.io/t/support-for-permissions-on-long-lived-access-tokens/190504)); the `system-read-only` group exists but can be assigned only by editing `.storage/auth`. Designed around with a home-side agent that keeps the token in the house (ADR-009).
- The community Alexa Skill MCP bridge has no OAuth account linking and always returns `visual: null`, so identity and MCP App cards cannot be exercised through the Alexa developer console (ADR-007).
- The add-on design guide gives a 768×480 base canvas and a 1.667 scale for Echo Show 8 and 15 but no per-device viewport table; confirm when the cards are built.

---

## Feature requests

Priority per Devpost: `Critical`, `Important`, `Nice-to-have`.

| Request | Impact | Priority |
|---|---|---|
| Add-on context in `_meta` on every tool call: device modality, locale, timezone | Tools cannot tell a voice-only device from a screen; the add-on has to guess or ask | Critical |
| Recognized-speaker identity for MCP add-ons, as classic Skills get via `context.System.person.personId` with `authenticationConfidenceLevel` ([docs](https://developer.amazon.com/en-US/docs/alexa/custom-skills/add-personalization-to-your-skill.html)); the add-on docs define no equivalent | Every tool call carries only the linked account's token, so per-person rules (a teen may not unlock the door) cannot be enforced by voice on a shared Echo; Hirz has to route every security approval to the phone instead. A speaker id with a confidence level would let add-ons lower authority per person safely | Critical |
| Proactive add-on invocation or a notifications API | A household agent cannot tell the member a scheduled action came due or an approval is waiting | Important |
| Alexa+ simulator access for hackathon participants | Participants have no simulator access, so each builds an emulated host to test against. Hirz's host harness and an add-on conformance checker are published as a separate open-source project so the next developer does not start from zero | Important |
| AgentCore Policy natural-language authoring exposed via API for third-party UIs | A household app could draft Cedar through the same path the console uses | Nice-to-have |

Item 17 follow-up to entries 6 and 8 (2026-09-21): the pinned SciPy install and
packaging command again encountered uv's existing cache sandbox restriction:
`error: Failed to initialize cache at /Users/bashaarjavaid/.cache/uv`, caused by
`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`.
Authorized escalation completed both operations. Public archive fetching first
returned `httpx.ConnectError: [Errno 8] nodename nor servname provided, or not known`
in the network sandbox; the authorized sequential download then succeeded.
The initial full test run's local WebSocket fixtures returned
`PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted`;
local-socket escalation resolved it. These reuse the existing sandbox workarounds,
not new upstream defects. References: [uv CLI](https://docs.astral.sh/uv/reference/cli/),
[HTTPX exceptions](https://www.python-httpx.org/exceptions/), and
[asyncio servers](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.loop.create_server).
No new ComEd, Open-Meteo or SciPy API incompatibility was observed in this task.


Item 18 follow-up to the existing sandbox entries (2026-09-21, **Minor**): uv again returned
`Failed to initialize cache at /Users/bashaarjavaid/.cache/uv` and
`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`.
Using `UV_CACHE_DIR=/tmp/hirz-uv` reused the installed environment without a new
install. The initial disposable PostgreSQL checks returned
`connection to server at "127.0.0.1", port 5432 failed: Operation not permitted`;
authorized local-socket escalation resolved it. The subsequent tests use
`--tb=short` to avoid third-party traceback locals containing connection parameters.
These repeat sandbox workarounds, not new upstream defects. References:
[uv cache directory](https://docs.astral.sh/uv/reference/cli/#uv--cache-dir) and
[pytest traceback styles](https://docs.pytest.org/en/stable/how-to/output.html#modifying-python-traceback-printing).
