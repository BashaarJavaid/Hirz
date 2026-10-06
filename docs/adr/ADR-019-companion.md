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
