# ADR-014: Local OAuth and member mapping

Date: 2026-09-23. Status: accepted; local implementation, verification status in
[item 24 evidence](../verification-log.md#item-24--2026-09-23).

## Decision

Use the installed MCP SDK's authorization and token handlers with a small,
loopback-only provider. This is a **simulated login**, not real authentication of
a person. It offers the five member/home choices derived from the canonical
seeds, displays requested scopes, and requires explicit Approve or Deny.
No production account linking, companion login, household tools or AWS resources
are introduced. The existing Compose app remains the anonymous generic preview.

The local issuer is `http://127.0.0.1:8001`; the MCP resource is exactly
`http://127.0.0.1:8000/mcp`. The pre-registered public client is `hirz-dev-sdk`,
with exact callback `http://127.0.0.1:8765/callback`. Test/smoke constructors accept
allocated loopback ports. No dynamic registration, secret or revocation endpoint
is exposed. Only an explicit `scripts/dev_oauth.py init` may create a missing
RSA-2048 signing key in the regular, nonsymlink, `0600` `.env`; a present empty or
malformed entry is refused, and the audit key is never used. `serve` only reads.

**Approved temporary-state exception:** consent transactions, codes and refresh
families may change in this dev issuer's memory without Pipeline decisions.
They create no graph rows, account links, device actions or fabricated audit
events. Restart loses these grants; existing signed access tokens retain their
normal validation/expiry. Disposable test seed bootstrap remains the existing
item 6 exception. Membership-change tests roll back their synthetic changes.

| Bound | Value |
|---|---|
| Consent / code / access lifetime | 5 minutes / 60 seconds / 5 minutes |
| Refresh family | 8 hours from issue, never extended |
| JWT skew | 30 seconds |
| Pending consents / codes / refresh families | 1,024 each; purge expiry first |
| Request and fetched-document size | 1 MiB |
| Metadata/JWKS fetch | startup and every 60 seconds, 2-second deadline per document |
| Key cache | expires 5 minutes after last successful metadata + JWKS fetch |

Consent uses a random transaction, hidden CSRF value and HttpOnly SameSite=Strict
cookie; consumption is one-time. The consent page uses same-origin referrer
policy so browser form POSTs retain a checkable Origin; its CSP permits only
self and the exact registered callback for form navigation. Children cannot approve. Scopes are exactly the
requested supported set; omission defaults to `hirz:read`. PKCE requires S256.
Codes bind client, exact redirect and resource. Refresh preserves subject,
household and resource; omission of refresh `resource` preserves the original.
Scopes may decrease but cannot increase. Rotation has no await between validation
and mutation in the single-process issuer. Authenticated generation counters keep
replay detection bounded in memory; a valid spent token revokes its whole family.
An unauthenticated forged generation cannot revoke a family. Access tokens already
issued remain valid until expiry; this local issuer has no access-token denylist.

## Resource server and SDK adaptations

Use `uvicorn --factory hirz.api.app:create_local_oauth_app` for authentication.
Both `/.well-known/oauth-protected-resource` and its `/mcp`-suffixed variant
publish identical PRM; challenges reference the root. S256 is advertised in
**authorization-server** metadata, not misrepresented as a PRM property.

A narrow gate runs after the existing bounded transport checks, ahead of SDK
protocol dispatch. Anonymous setup, discovery and `what_can_you_do` remain
available. Other tools require authentication by default, with an explicit
required scope (default `hirz:read`); registration without authentication wiring
is refused. The diagnostic `oauth_probe` exists only in tests and the smoke.
Supplied credentials in generic-preview mode return 503.

The SDK 1.30.0 authorization handler checks scopes and S256 and its token handler
checks code expiry, client, redirect and PKCE. The token handler parses `resource`
but does not compare it to the stored grant; its error literals also omit
`invalid_target`. Hirz checks exact redirect, explicit S256, PKCE syntax,
duplicate parameters and canonical resource **before** these handlers, returning
RFC 8707 `invalid_target` for invalid/missing resource. It supplies metadata with
`none` client authentication, JWKS, and no registration/revocation endpoint.
The SDK's global RequireAuth middleware would block anonymous onboarding, so the
gate reuses its `AccessToken`, `AuthenticatedUser` and authentication ContextVar
while applying authorization per request. The household identity ContextVar is
set/reset in the same request, including across concurrent stateless calls.

PyJWT 2.14.0 is pinned directly with crypto support. Accept only RS256, a known
`kid`, `typ=at+jwt`, and required typed `iss`, `sub`, scalar exact `aud`, integer
`iat`/`exp`, `client_id`, `scope`, and UUID `household_id`. Validate issuance,
expiry, optional `nbf`, and maximum 300-second lifetime. Ignore token-supplied
role, provider, surface, speaker and passkey authority. The configured local
issuer maps to provider `demo`; the shared indexed account lookup joins current
`member_accounts` and `members` by signed household and subject. It produces the
existing internal Principal on surface `alexa`, with no speaker or passkey claim.
No Action, Decision or Plan shape changes.

Metadata/JWKS retrieval has no redirects, uses only the configured issuer and
same-origin JWKS, and never runs in a tool call. Token-supplied key URLs cannot
trigger requests. Fresh-cache unknown key and invalid tokens return 401; expired
or unavailable keys and required database failure return 503, never guest access.
Missing protected credentials return 401 with PRM challenge; insufficient scope
returns 403 with `insufficient_scope`, required scope and friendly JSON. Unmapped
or child accounts get 403 for protected tools and generic onboarding only.
Policy refusals remain MCP tool results when household tools are added.

## Rejected alternatives

- Cognito, real login or persistent dev grants now: production identity belongs to
  later roadmap items; this local exercise needs no AWS spend or new migration.
- Reusing the audit key: independent purposes require separate keys/algorithms.
- Handwriting the whole OAuth flow: reuse SDK validation and adapt only missing
  resource binding and the explicit local contract.
- Global required-auth middleware: removes the required guest experience.
- A network JWKS fetch on unknown `kid`: creates attacker-driven I/O and violates
  the tool latency boundary. Unknown keys wait for the periodic refresh.
- Role claims or cached member roles: stale/forged authority must not bypass the
  current household account mapping.
- Dynamic Inspector registration: unnecessary for the pre-registered SDK flow;
  Inspector OAuth registration remains deferred. Anonymous Inspector is retained.

## Official references

- [Amazon account linking](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-account-linking.html)
- [MCP 2025-11-25 authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [RFC 8707 resource indicators and invalid_target](https://www.rfc-editor.org/rfc/rfc8707.html)
- [MCP Python SDK authorization handler](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/auth/handlers/authorize.py)
- [MCP Python SDK token handler](https://github.com/modelcontextprotocol/python-sdk/blob/v1.30.0/src/mcp/server/auth/handlers/token.py)

The public contract pages were fetched on 2026-09-23; SDK adaptations were checked
against the installed pinned source and exercised through the handlers.

## Household tools amendment — 2026-09-23

Household tools consume request-local linked member identity and the existing four scopes. Anonymous onboarding remains generic; a valid read grant permits contextual capabilities only when current member resolution succeeds. HTTP 401/403/503 behavior remains at the OAuth gate; tool validation failures are typed MCP execution errors. Full contract and rejected alternatives: [ADR-015](./ADR-015-household-tools.md).
