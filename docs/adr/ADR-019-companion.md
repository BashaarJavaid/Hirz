# ADR-019 — Authenticated companion app

Date: 2026-09-25. Status: accepted scope; implementation and acceptance pending.

Item 28 uses six React routes and a same-origin FastAPI `/api` surface. Identity
comes from verified WebAuthn credentials and server sessions, never request fields
or simulated OAuth login. Python `webauthn` verifies registration/assertion with
required user verification, exact configured HTTPS origin and RP ID. Ceremonies
expire in five minutes and are single-use and browser-bound. Secure, HttpOnly,
SameSite cookies have 30-minute idle and 12-hour absolute limits; mutations check
origin and CSRF. Fresh assertions bind the credential, session and reviewed action.

The approved bookkeeping exception covers pre-login challenges, sessions and
explicit initial invitations for existing demo members only. It grants no device,
policy or recovery authority. Enrollment completion, credential/recovery changes,
policy activation and all household mutations require Pipeline decisions and audit
in the same transaction. Initial invitations cannot reset an enrolled member.
Recovery codes permit enrollment only, consume once, revoke old credentials,
sessions and unused votes, and rotate after successful replacement enrollment.
Owners without a passkey or recovery code have no in-product recovery. Owner
re-invitations cannot become owner recovery. Last-key revocation requires explicit
lockout confirmation; additional credentials are encouraged, including the caveat
that passkeys can sync across devices.

Reserved constitution, credentials, contacts and twin governance classes enforce
operation and role restrictions in Python and compiled native policy. Seed policy
versions remain v7/v1 on first activation. Runtime work requires active policy;
historical disposable scenarios remain explicitly isolated. Activation checks the
reviewed candidate/base, pending approvals and fresh passkey, then atomically
records artifacts, pointer and CONSTITUTION_ACTIVATED. Rollback creates a new
version. Unaffected approvals retain deadlines when reissued. Local mode is
`dogwood-local`, `not analyzed: local mode`; AWS activation awaits item 37.

English drafting only replaces complete autonomy rules using the existing patch
contract, validates the candidate and runs in the worker. Off means disabled;
recorded patches are explicitly labeled disposable demonstrations. Deterministic
review includes every changed rule, including unintended changes; more than three
summary lines requires opening the complete review. Models never activate rules.

Push uses `pywebpush`, encrypted private subscription material, generic text and
authenticated links. Notification interaction is not approval. Delivery needs a
communication.notify_member grant, retries at most three times before expiry,
and keeps the inbox usable. iPhone reception needs manual Home Screen installation
and permission. Private HTTPS uses Tailscale Serve and its actual hostname.

Rejected: simulated OAuth as companion authority; client passkey Booleans; reusable
fresh-auth flags; recovery as approval; direct SQL household mutation endpoints;
silent policy rebasing; binding-as-management declarations; contact or physical
lock simulation presented as real; polling overlaps; live paid drafting verification.

Check-in remains simulated (item 31 owns real delivery). Only twin unlock/read-back/
bounded relock is in scope. Simulator, recording Compose, AWS policy analysis,
Link, signer verification and tamper playground retain their scheduled items.
Development remains at migration 0005; tests migrate disposable databases only.
Item 28 cannot close without the browser, iPhone, signed audit and CI gates.

Contracts consulted: [WebAuthn](https://www.w3.org/TR/webauthn-3/),
[Python WebAuthn](https://duo-labs.github.io/py_webauthn/),
[WebKit push](https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/),
[Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve).

### Lifespan-scoped policy cache — 2026-10-06

Companion polling recompiled and validated the stored policy on every request.
Cache validated bundles per household by stored hash only while the native helper
is live, revalidating when that hash changes.
Capture whether the helper is live before awaiting validation, and only cache
bundles validated from that state so CLI validation cannot populate the cache.
Reject caching across CLI validation and helper startup because the helper has
not prepared those policy/schema pairs and must refuse their replay.
Reject lazy preparation in replay because the native-helper contract forbids
compilation during a warm call.

## Queued AWS activation amendment — 2026-10-17

AWS-managed households return pending after a passkey confirms the exact reviewed
candidate. Migration 0020 stores publication progress, engine readiness/generation,
and Gateway sessions. Worker ticks recheck the owner's current authority and
credential, candidate integrity, base version and pending approval blockers before
publication and commit. Every persisted transition requires a Pipeline grant and
audit. Native/local activation remains immediate.

The Constitution interface displays actual engine, publication state and raw AWS
findings associated with that candidate. Publication failures never activate it;
failed restoration keeps AWS actions blocked. Session replacement invalidates old
approvals and preserves their original expiry when reissued. Rejected: claiming
activation on queue acceptance, fabricating a new passkey verification in the worker,
hard-coded local labels for managed households, and extending consent on restart.

## Approved hard-deny analysis disclosure — 2026-10-18

For the narrow exception approved in ADR-003, the Constitution response and
activation audit describe strict validation for permits and conditional forbids,
and schema-only validation for approved hard-deny exceptions. This disclosure
persists across later publications that retain existing rules; raw AWS findings
remain in publication history. Pending and
failed publication behavior and local activation remain unchanged. Rejected:
showing an unqualified AWS validation success after skipping semantic analysis.

## Item 38 self-linked Cognito login — 2026-10-19

The author selected each member linking their own login from their authenticated
companion app. The backend verifies a short-lived Cognito human access token for
the exact configured issuer, client and Runtime resource, with read scope. A
fresh, single-use passkey ceremony binds its digest and provider/subject to the
current companion session. Completion verifies the same token again and resolves
the current member and credential; request fields cannot select a different member.
Child members cannot link, preserving the identity contract in architecture §7.

Linking uses the existing `governance.credentials` enrollment grant and stores the
mapping in the same transaction as its action and signed audit decision. The
action records the credential kind and provider/subject; bearer tokens stay out
of stored ceremonies, actions and audit. A transaction advisory lock serializes
the provider/subject across households. V1 refuses an existing mapping, including
one in another household, because Runtime has no household selector. The database
shape still permits future explicitly designed multi-household membership.

Rejected: owner assignment of someone else's login, token claims supplying roles,
email matching, an OAuth login replacing companion passkeys, reassignment of an
existing mapping, and household-only locks that allow concurrent ambiguous links.
No compiler grammar, bootstrap exception or migration is added. The worker starts
the same bounded key cache used by Runtime only after its resource is configured.

This amendment records the chosen identity model and locally verified backend.
Browser PKCE/redirect wiring and live Cognito acceptance remain pending; it does
not claim an end-to-end production login flow or an item 38 deployment.

### Browser self-link flow locally verified — 2026-10-19

Household now starts the chosen member's login flow. The browser generates random
OAuth state and an S256 PKCE verifier, retaining them for at most five minutes in
tab-scoped storage with the companion-session binding and exact login config.
On return it removes the code from the address bar and consumes that state before
exchanging the code. Changed sessions/issuers, expired or duplicate returns and
provider cancellation fail before exchange. A subsequent user gesture confirms
the same access token through the existing passkey ceremony. Access and refresh
tokens are never persisted; cancellation or failure requires starting again.

The worker serves only its configured human client, Runtime resource, callback
and HTTPS login origin. CSP permits that exact origin for token exchange. A new
`CompanionCallbackUrl` deployment parameter avoids a CloudFormation dependency
cycle: the second deployment registers the created companion origin plus
`/account-link`, preserving the acceptance CLI callback. Its initial local
placeholder leaves the browser flow unavailable. No resources or permissions are
added. Existing mappings remain non-reassignable; this adds no unlink/recovery path.

Contracts checked on 2026-10-19:
[Cognito authorization endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html)
and [token endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html).
The authorization request includes `resource`, `state`, `code_challenge_method=S256`
and `prompt=login`; the latter requires managed login and is not relied on as an
authorization guarantee. Token validation and the member's fresh passkey remain
mandatory. Local tests cover the browser protocol and virtual passkeys; actual
Cognito UI/CORS, hosted redirect, physical phone and live acceptance remain owed.

### Drafting cancellation retains ownership — 2026-10-19

The drafting worker now uses the existing bounded SDK-call helper, as plan
narration does. Cancellation waits for the already-started provider thread before
releasing the drafting advisory lock. The cancelled task does not publish its
result; the proposal remains queued for a later attempt. Rejected: releasing the
lock while a non-cancellable thread can still consume model service, or treating
that unfinished call as a completed draft. Model output validation, human review
and passkey activation remain unchanged.

### Drafting schema compatibility — 2026-10-19

Bedrock's [strict-output subset](https://docs.aws.amazon.com/bedrock/latest/userguide/structured-output.html)
requires closed objects, while the canonical Patch intentionally carries maps of
complete rule replacements. Send that exact schema as prompt guidance and request
plain JSON, then parse it with Patch and validate the resulting constitution as
before. Do not send the incompatible schema in `outputConfig`. Rejected: making
up a second patch language, broadening the constitution grammar, or trusting the
provider to enforce the grammar. Invalid or incomplete output still fails the
draft without activation; there is no repair prompt or additional model request.
