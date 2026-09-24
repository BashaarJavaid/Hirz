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

Item 19 follow-up to the existing sandbox entries (2026-09-21, **Minor**): uv again
reported `Failed to initialize cache at /Users/bashaarjavaid/.cache/uv` and
`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`;
`UV_CACHE_DIR=/tmp/hirz-uv` allowed reuse of the installed environment. PostgreSQL
initially returned `connection to server at "127.0.0.1", port 5432 failed: Operation not permitted`;
authorized localhost access resolved it. Subsequent database tests use `--tb=short`
to suppress third-party traceback locals. These are the same sandbox workarounds,
not new upstream API defects. References: [uv cache directory](https://docs.astral.sh/uv/reference/cli/#uv--cache-dir)
and [pytest traceback styles](https://docs.pytest.org/en/stable/how-to/output.html#modifying-python-traceback-printing).

Item 20 follow-up to the existing sandbox entries (2026-09-21, **Minor**): uv
reported `Failed to initialize cache at /Users/bashaarjavaid/.cache/uv` and
`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`.
Using the installed `.venv/bin` tools and `UV_CACHE_DIR=/tmp/hirz-uv` for builds
avoided a new dependency install. Disposable PostgreSQL tests initially returned
`connection to server at "127.0.0.1", port 5432 failed: Operation not permitted`;
the existing WebSocket tests also could not bind localhost. Authorized local
socket access resolved both. Database reruns used `--tb=short` to suppress
third-party traceback locals. These repeat sandbox workarounds, not new upstream
API defects. References: [uv cache directory](https://docs.astral.sh/uv/reference/cli/#uv--cache-dir)
and [pytest traceback styles](https://docs.pytest.org/en/stable/how-to/output.html#modifying-python-traceback-printing).


Item 21 follow-up to entry 6 (2026-09-22, **Minor**): installing the approved
Boto3 dependency with `uv add 'boto3==1.43.90'` encountered the same sandbox cache
restriction: `error: Failed to initialize cache at /Users/bashaarjavaid/.cache/uv`
and `failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`.
[uv cache contract](https://docs.astral.sh/uv/concepts/cache/). Authorized escalation
installed and locked the dependency; repository-local tool binaries handled focused
checks, and escalated uv handled full-suite loopback/database checks. This is the
existing sandbox limitation, not an SDK or uv defect; no live Bedrock call was made.


Item 22 solver output (2026-09-22, **Minor**): the overnight replay emitted
`HighsMipSolverData::transformNewIntegerFeasibleSolution tmpSolver.run();`
on stdout even with SciPy's default `disp=False`. This was diagnostic output,
not a solver failure, but it made redirected CLI stdout unsuitable as a JSON
file. [SciPy's MILP options](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html)
document console status output as opt-in. The scenario CI job now reads the
existing exclusive-create `--output` report, which is written independently of
native solver output. Feature request: route all native diagnostics through the
configured logging flag or stderr so stdout remains usable by structured CLIs.


Phase 3 Batch C2 follow-up to entry 6 (2026-09-22, **Minor**): `uv run pytest`
repeated the existing agent-sandbox cache restriction:

```text
error: Failed to initialize cache at `/Users/bashaarjavaid/.cache/uv`
  cause: failed to open file `/Users/bashaarjavaid/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
```

Authorized sandbox escalation allowed the existing cache and disposable local
PostgreSQL verification. This is the previously recorded environment limitation,
not a new upstream defect. Reference: [uv cache configuration](https://docs.astral.sh/uv/concepts/cache/).


HA smoke CI investigation (2026-09-22, **Minor**):
`gh run view 35825693255 --job 107066790316 --log` refused to read the completed
scenario job while another job remained active:
`run 35825693255 is still in progress; logs will be available when it is complete`.
The [CLI reference](https://cli.github.com/manual/gh_run_view) supports selecting
an individual job's logs. Workaround: `gh api repos/BashaarJavaid/Hirz/actions/jobs/107066790316/logs`
returned the completed job's diagnostics through the documented
[job-log endpoint](https://docs.github.com/en/rest/actions/workflow-jobs#download-job-logs-for-a-workflow-run).
Feature request: let `gh run view --job --log` retrieve a completed job without
waiting for the whole run. This was a CLI limitation, not a failed Actions service.

## Item 23 local transport and Inspector — 2026-09-23

- **Tool/task:** MCP Python SDK 1.30.0, implement stateless JSON without persistent
  event streams. **Steps/expected:** inspect the documented
  [stateless JSON setup](https://py.sdk.modelcontextprotocol.io/v1/server/#streamable-http-transport).
  **Actual:** the pinned `_handle_get_request` still creates an SSE response even
  when `json_response=True`; no exception is emitted. **Severity:** Minor.
  **Workaround:** the author explicitly approved a GET `/mcp` 405 guard; other
  protocol handling remains in the SDK. **Suggestion:** document GET streaming
  separately from JSON POST responses and offer an explicit disable switch.
- **Tool/task:** Inspector 2.7.0, start an isolated authenticated UI.
  **Steps/expected:** set `MCP_CATALOG_PATH` to a temporary catalog and pass
  `--transport http --server-url http://127.0.0.1:8000/mcp`.
  **Actual:** `Error: --catalog cannot be combined with an ad-hoc server URL/command.`
  **Severity:** Minor. **Workaround:** launch only the isolated catalog and enter
  the server URL in the UI. **Suggestion:** name the environment variable in the
  error when no `--catalog` flag was supplied. Reference:
  [Inspector environment variables](https://github.com/modelcontextprotocol/inspector/blob/2.7.0/docs/environment-variables.md).
- **Tool/task:** browser connection for Inspector UI verification.
  **Actual:** `No browser is available` and an empty browser list, including after
  the author enabled the connection and requested a retry. **Severity:** Minor.
  **Workaround:** the author explicitly authorized a temporary standalone Playwright
  browser. Its sandboxed Chrome launch exited with `signal=SIGABRT`; the same
  temporary browser was launched with authorized sandbox escalation. Reference:
  [Playwright browser launch](https://playwright.dev/docs/api/class-browsertype#browser-type-launch).
  These are local tooling restrictions, not an Inspector or MCP failure.

The uv cache, Docker socket and loopback-binding restrictions from entry 6 also
recurred. Initial focused tests reported `2 failed, 92 passed` because the two
existing WebSocket checks could not bind `127.0.0.1`; the full service-free rerun
with authorized loopback access passed. No upstream defect is claimed for these
repeated sandbox restrictions.

Inspector UI follow-up (2026-09-23, **Minor**): installed Chrome reported
`97.0.4692.71` and rendered the main content beneath the header/footer; Playwright
reported `TimeoutError: locator.click: Timeout 30000ms exceeded.` with the header
intercepting pointer events. Using Playwright 1.63.0's bundled Chromium
153.0.8010.12 restored the layout. The connection switch's styled track also
intercepted pointer clicks, so keyboard focus + Space connected normally. The
browser-control process needed loopback access outside the sandbox after
`WebSocket error: connect EPERM 127.0.0.1:63888 - Local (0.0.0.0:0)`.
Reference: [Playwright browser compatibility](https://playwright.dev/docs/browsers).
Suggestion: show a browser compatibility warning for unsupported browser engines.
No Hirz code or security rule was changed to work around these UI/environment issues.

## Item 24 local OAuth — 2026-09-23

- **Tool/task:** MCP Python SDK 1.30.0, bind local authorization-code/refresh
  exchange to the canonical MCP resource. **Steps/expected:** inspected the
  installed [token handler](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/auth/handlers/token.py)
  against [RFC 8707](https://www.rfc-editor.org/rfc/rfc8707.html).
  **Actual:** the handler parses `resource` but does not compare it with the
  grant; its `TokenErrorCode` omits `invalid_target`. No upstream exception was
  emitted; this is a provider integration gap, not a claim that the SDK promises
  automatic resource enforcement. **Severity:** Minor. **Workaround:** validate
  resource before the SDK handler and return `invalid_target`; regression tests
  verify omitted/wrong code-exchange resources are rejected before issuing tokens.
  **Suggestion:** pass requested resource to provider exchange methods or document
  the required HTTP-boundary adaptation alongside the provider protocol.
- **Tool/task:** browser-plugin consent-page and Inspector verification.
  **Steps/expected:** initialized the installed browser runtime, selected the local
  harness URL, read its bootstrap troubleshooting guide and listed browsers;
  retried after the author enabled the connection. **Actual:** both attempts
  returned `No browser is available`; discovery returned `[]`. **Severity:** Minor.
  **Workaround:** the author approved temporary standalone Playwright; Chromium
  153.0.8010.12 completed the SDK consent and callback checks.
  **Suggestion:** distinguish disconnected browser integration from disabled
  integration and expose recovery status. This repeats the item 23 local browser
  limitation; [Playwright browser launch](https://playwright.dev/docs/api/class-browsertype#browser-type-launch)
  is the proposed fallback reference, not evidence of a Playwright defect.

The entry 6 uv-cache restriction recurred during `uv lock --offline`:
`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`.
Authorized escalation resolved it without a dependency change beyond the approved
PyJWT direct pin. No new upstream defect is claimed.

Item 25 follow-up to entry 6 (2026-09-23): the existing sandbox uv-cache
restriction recurred (`failed to open file /Users/bashaarjavaid/.cache/uv/sdists-v9/.git: Operation not permitted (os error 1)`).
`UV_CACHE_DIR=/tmp/hirz-uv-cache` resolved it. A service-free suite rerun also hit
`PermissionError: [Errno 1] error while attempting to bind on address ('127.0.0.1', 0): [errno 1] operation not permitted`
in the two WebSocket contract tests; authorized loopback access is required.
These are sandbox restrictions, not new upstream defects. Reference:
[uv cache configuration](https://docs.astral.sh/uv/concepts/cache/).
The Bedrock selection attempt lacked local credentials (`NoCredentialsError`)
and stopped before inference; this is a pending access gate, not an SDK defect.

## Item 25 Bedrock token counting and model access — 2026-09-23

- **Tool/task:** Bedrock runtime CountTokens for the pinned US Haiku 4.5 host.
  **Steps/expected:** authenticate with the supplied `hirz` profile and count a
  one-message request before reserving any inference spend.
  **Actual:** `ValidationException: The provided model doesn't support counting tokens.`
  **Severity:** Blocker. **Workaround:** none verified; fail closed before inference.
  AWS's [counting guide](https://docs.aws.amazon.com/bedrock/latest/userguide/count-tokens.html)
  documents a separate Mantle Anthropic counter for cross-region-only models.
  A SigV4-signed request there returned HTTP 403 `permission_error`:
  `anthropic.claude-haiku-4-5 is not available for this account. You can explore other available models on Amazon Bedrock. For additional access options, contact AWS Sales at https://aws.amazon.com/contact-us/sales-support/`
  **Suggestion:** expose counting support and endpoint requirements in model
  discovery, with actionable agreement/access status in counting errors.
- **Access diagnosis:** the use-case form exists; the model availability API
  reports authorization, entitlement and region available, but agreement
  `NOT_AVAILABLE`. No agreement was created or inference invoked. The
  [access procedure](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
  requires provider terms for model use. These observations do not prove that
  accepting an agreement alone resolves the separate Mantle denial.

Follow-up on 2026-09-23: the user requested a retry after the setup wait. The US
inference profile still failed CountTokens, but the underlying foundation model
ID succeeded (24 counted tokens). The host had passed the inference profile to
both APIs; that was our integration mistake. CountTokens now uses the foundation
model ID, while Converse retains the US profile. A bounded Converse probe then
succeeded (8 input, 16 output tokens) without manual account changes. Mantle's
model metadata still reports an account restriction, with compatible retention
settings, so that separate denial is not evidence of runtime unavailability.
Our earlier suggestion to find an "enable access" button was misleading under
AWS's current automatic first-invocation subscription procedure.

## Item 25 interrupted Bedrock selection run — 2026-09-23

- **Tool/task:** Bedrock-backed Strands host, complete 31-case live selection gate.
  **Steps/expected:** run `smoke_household_tools.py --live-selection` with working
  `hirz` credentials and the retained budget ledger; collect all selections.
  **Actual:** after 16 passing selections, the retained error was
  `LIVE_GATE_PENDING InternalServerException`. The harness retained the exception
  class only, so no endpoint-specific message or request ID is claimed.
  **Severity:** Minor. **Workaround:** retain the interrupted report and budget
  history, then retry the full gate within the approved ceiling; no partial-run
  result substitutes for a complete passing gate.
  **Reference:** [Bedrock Converse error contract](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html).
  This is a transient service error documented by the API, not evidence of an
  incorrect API contract. **Suggestion:** structured SDK diagnostics should make
  request IDs easy to retain without logging prompts, credentials or tool data.

Follow-up: the complete retry passed all 31 selections within the same $2 ledger;
the interrupted report and reservations remain retained. See the [completion evidence](./verification-log.md#item-25-completion-within-approved-scope--2026-09-23).

## Item 25 CI fix verification: local uv cache — 2026-09-23

- **Tool/task:** [uv pip install](https://docs.astral.sh/uv/reference/cli/#uv-pip-install),
  install the built wheel into a disposable environment for the CI smoke check.
  **Expected:** install dependencies and run the packaged catalog assertion.
  **Actual:** sandbox networking first returned ``Failed to fetch: `https://pypi.org/simple/pydantic/` ``
  and `failed to lookup address information: nodename nor servname provided, or not known`.
  After network escalation, the existing temporary cache returned
  `error: Failed to install: pydantic-2.13.5-py3-none-any.whl (pydantic==2.13.5)` and
  ``cause: failed to open file `/private/tmp/hirz-uv-cache/archive-v0/5nGQ-lFiHwIYjaeD/pydantic-2.13.5.dist-info/WHEEL`: No such file or directory (os error 2)``.
  **Severity:** Minor. **Workaround:** rerun with a fresh disposable `UV_CACHE_DIR`;
  installation and the exact CI smoke step passed. The cause of the missing cache
  file was not established. **Suggestion:** identify incomplete cache entries and
  offer a targeted refetch in installation diagnostics.

## Item 25a: Amazon and MCP authentication guidance conflict — 2026-09-23

- **Tool/task:** implement independent add-on checks using the
  [Amazon authentication guidance](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html)
  and [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization).
  **Steps/expected:** read both current documents; expect consistent discovery guidance.
  **Actual:** Amazon's “What isn't supported” list includes
  “`WWW-Authenticate` headers in 401 responses”; MCP says
  “MCP clients MUST be able to parse `WWW-Authenticate` headers”.
  No runtime error is involved; these are the exact conflicting documentation excerpts.
  **Severity:** Minor. **Workaround:** label the check as scoped MCP evidence,
  document Amazon's differing guidance, preserve Hirz's existing authentication,
  and make no Amazon certification claim ([ADR-016](./adr/ADR-016-add-on-conformance-checker.md)).
  **Suggestion:** publish a reconciled discovery contract and explain whether the
  restriction concerns the Alexa client or server behavior.

## Item 25a: npm publishing authentication — 2026-09-23

- **Tool/task:** npm CLI; publish the tested `addon-check@0.1.0` tarball after
  interactive login, following the [publication procedure](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
  **Steps/expected:** verify `npm whoami`, confirm the name is absent, and run
  `npm publish ./addon-check-0.1.0.tgz --access public`; expect an interactive
  publishing authorization or publication.
  **Actual:** `E403`, with exact message:
  `403 Forbidden - PUT https://registry.npmjs.org/addon-check - Two-factor authentication or granular access token with bypass 2fa enabled is required to publish packages.`
  **Severity:** Blocker at this attempt. **Workaround:** ask the author to complete
  [npm's documented 2FA setup](https://docs.npmjs.com/configuring-two-factor-authentication/)
  and publish the same tested artifact interactively; no credentials/OTP are copied
  into chat and no account security setting is changed by the agent.
  This is npm's documented account requirement, not an upstream defect.
  **Suggestion:** after web login, show publishing readiness and a direct 2FA setup
  link before a tarball upload is attempted.

Follow-up: the author completed interactive publishing authentication and published
the tested artifact; its registry checksum matched and both installed CLI fixture
checks passed. See the [completion evidence](./verification-log.md#publication-and-completion).

## Item 26: nested JSON index reflection — 2026-09-23

- **Tool/task:** Alembic 1.20.0 / SQLAlchemy 2.0.54; compare a migrated PostgreSQL
  schema with application metadata using
  [Alembic schema comparison](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).
  **Steps/expected:** declare the nested JSON budget index, migrate a disposable
  database, and run the existing schema-consistency check; expect no difference.
  **Actual:** metadata rendered `((payload['budget']) ->> 'class')`, while
  PostgreSQL reflected `(payload['budget'::text] ->> 'class'::text)`.
  `compare_metadata` proposed `remove_index` and `add_index` for
  `audit_budget_usage`; Hirz consequently raised the exact error
  `Schema is inconsistent; restore the database before key setup.`
  **Severity:** Minor. **Workaround:** declare the fixed nested index expressions
  as SQL text matching the migration/reflection, retaining the full consistency
  guard. Migration roundtrip and budget-equivalence checks then passed.
  Alembic documents that autogeneration needs manual review; this is an observed
  expression-normalization limitation, not a claim of perfect-detection support.
  **Suggestion:** normalize redundant JSON-subscript parentheses before comparing
  index expressions, or explain the differing normalized expressions in diagnostics.

## Item 26: repeated native compilation in local replay — 2026-09-23

- **Tool/task:** pinned Dogwood CLI
  [`996d756d`, replay implementation](https://github.com/dogwood-policy/dogwood/blob/996d756de1013b7ae209a14f566a80375a59f2f0/dogwood-cli/src/ops.rs),
  used for the local authenticated tool-latency gate. **Steps/expected:** authorize
  successive requests under the same validated policy, within the project's
  250 ms warm tool budget. **Actual:** each CLI replay creates a process and calls
  `lower_internal` again. There is no persistent/prepared replay CLI option, and
  `Authorizer::new` consumes a `LoweredPolicySet` that does not implement `Clone`.
  No CLI error occurs; the observed problem is repeated work, with timing evidence
  in [item 26 verification](./verification-log.md#approved-budget-indexes-and-terminal-plan-filtering--2026-09-23).
  **Severity:** Major. **Workaround:** author-approved private helper and pinned
  artifact-cloning patch, retaining the unmodified CLI as the equivalence reference;
  implementation and verification are tracked in
  [ADR-017](./adr/ADR-017-tool-latency-and-isolation.md#native-helper-amendment--2026-09-23).
  **Suggestion:** expose reusable compiled artifacts with fresh authorizer history,
  or a prepared replay mode, without requiring consumers to retain temporal state.


## Item 26: latency measurement method unspecified — 2026-09-24

- **Tool/task:** reconcile the partner-only
  [MCP Toolkit quickstart, Performance](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html#performance)
  with the [hackathon rules](https://amazonappdev2026.devpost.com/rules) for the
  item 26 checkpoint. **Steps/expected:** read the Performance section and search
  the rules for latency, performance, response time and 500; expect a defined
  measurement method and a statement of hackathon applicability.
  **Actual:** “Your MCP server must meet a round-trip query response latency of
  less than 500 ms.” The section supplies no percentile, measurement point or
  consequence, and the hackathon rules do not reference the requirement. No
  runtime error occurred; this is documentation ambiguity.
  **Severity:** Minor. **Workaround:** retain Hirz's explicitly defined local
  proxy and distinguish it from submission requirements in the
  [deferral amendment](./adr/ADR-017-tool-latency-and-isolation.md#deferral-amendment--2026-09-24);
  participant toolkit access is already recorded in entry 1.
  **Suggestion:** publish the measurement method (percentile, endpoints and
  conditions), consequences, and whether it applies to hackathon submissions.

## Item 26b: interrupted MCP latency measurement — 2026-09-24

- **Tool/task:** MCP Python SDK 1.30.0
  [Streamable HTTP client](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/client/streamable_http.py),
  HTTPX 0.28.1 and the authenticated loopback latency measurement.
  **Steps/expected:** run the unchanged Time-of-Day corpus once, with five warmups
  and 100 measured calls per case. **Actual:** after 102 complete lifecycle rounds,
  the next round stopped with `httpcore.ReadError`, propagated as `httpx.ReadError`
  inside `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`;
  pytest reported `1 failed in 2630.78s (0:43:50)`. The report retained 40 cases
  with 97 or 98 samples each; the later cases, startup checks and full-run signed
  exports were not reached. The retained exception does not establish whether
  the server, socket, SDK or another local component caused the disconnect.
  **Severity:** Major. **Workaround:** preserve the partial raw report and retained
  disposable database, report incomplete evidence explicitly, and honor the
  author's no-rerun instruction; no transport or corpus change was made.
  **Suggestion:** retain the originating request context when a transport error
  surfaces through task-group cleanup. Evidence and exact private artifact paths:
  [item 26b](./verification-log.md#item-26b--2026-09-24).

  **2026-09-24 diagnosis and harness follow-up:** the recorded failure occurred
  while receiving headers for `get_household_plan` after the worker following
  `stale-approval-cheapest` in round 103: the Uvicorn/httpcore keep-alive close
  race, with Uvicorn's default five-second timeout inside the worker's two-to-seven
  second client idle gap. The smoke harness now sets
  [`timeout_keep_alive=120`](https://www.uvicorn.org/settings/#timeouts); runtime
  server settings are unchanged. The prescribed pooled authenticated SDK probe
  completed 200 six-second idle intervals before the change and 200 afterward,
  with **0 failures before and 0 after**. Thus this probe did not reproduce the
  race and does not independently prove that diagnosis; no failure was injected
  and the client's pooling settings were unchanged. Private raw counts and logs
  are retained under `/tmp/hirz-item26b-third-step/` and recorded in the evidence
  follow-up.

## Item 26b: SDK per-call schema validation — 2026-09-24

- **Tool/task:** MCP Python SDK 1.30.0,
  [`src/mcp/client/session.py:441`](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/client/session.py#L441),
  `ClientSession._validate_tool_result` (starts at line 417).
  **Steps/expected:** compare `await session.call_tool("what_can_you_do", {})`
  with the identical authenticated raw JSON-RPC POST, expecting the measured
  round trip to reflect server/transport work. **Actual:** the established floor
  probe measured 58 ms versus 4 ms, a **54 ms** difference; each successful call
  executes `validate(result.structuredContent, output_schema, registry=registry)`,
  rechecking the schema against the metaschema and building a validator anew.
  No exception or error text occurred; this is repeated client validation cost.
  **Severity:** Minor. **Workaround:** time raw HTTP through receipt of the full
  body, then retain SDK schema validation and the existing assertions outside the
  timer, with separate SDK reference columns. **Suggestion:** cache a checked
  validator per tool/output-schema version and invalidate it when the schema
  changes. [Finding and measurement scope](./verification-log.md#scheduling-and-harness--2026-09-24),
  [author's decision](./adr/ADR-017-tool-latency-and-isolation.md#server-round-trip-amendment--2026-09-24).
