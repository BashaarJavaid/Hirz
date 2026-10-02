# ADR-021: Extracted local MCP host harness

Date: 2026-10-01. Status: implemented; acceptance complete with the approved shutdown follow-up below.

## Decision

Item 29a publishes `addon-host@0.1.0` on npm and `addon-host==0.1.0` on PyPI
(`addon_host` import), both Apache-2.0, from the existing independent
`BashaarJavaid/addon-check` repository. The checker remains independently
installable. npm workspaces contain the React library and explicit tool-runner
example; a separate uv-built Python package contains the OAuth/MCP primitives.

The author approved Python 3.12, Node 24, React 19, the existing SDK versions,
separate CSS, React peers and Safari 15.4-compatible application output.
Python exports `OAuthConfig`, in-memory `OAuthSession` and `connect_mcp`,
returning the official SDK's `ClientSession`. React exports `McpAppFrame`,
`Transcript`, `useVoice` and CSS. Protocol objects remain SDK types; no new
Hirz Action, Decision, Plan or audit shape is introduced.

OAuth uses the SDK's protected-resource and OAuth/OIDC discovery helpers,
pre-registered public clients, PKCE S256, exact resource/redirect binding and
server-memory tokens. The author additionally approved restricting discovered
metadata and authorization/token endpoints to the configured MCP/issuer origins.
There is no automatic registration or anonymous fallback for a failed link.
Refresh failure removes the affected connection's authority until relinking;
tool calls are never automatically retried by the host.

Hirz owns its existing browser/HTTP/SSE session surface, account checks, household
JWT validation, consent and elicitation policy, request identities, model/scripted
selection, scenario clocks, source badges, account switch and companion authority.
The extracted libraries neither make a household decision nor own device access.

The independent FastAPI/React runner binds to loopback and accepts target URLs
only at startup (HTTP loopback or HTTPS). It discovers tools, validates explicit
JSON arguments and reviews every exact call, including card requests. Scalar MCP
elicitation uses native labeled inputs. Voice input fills a selected string field
or answers a scalar prompt; output reads ordinary MCP text only after an explicit
foreground call. No model chooses calls or interprets structured results.

Cards are discovered through MCP UI resource metadata. They retain the opaque
`allow-scripts` sandbox and no-network CSP; v0.1 supports self-contained bundles.
The independent proof uses the unchanged published
`@modelcontextprotocol/server-basic-vanillajs@2.0.0` (`get-time`), whose `gitHead` is
`352f6ced4d80772e92b4e7a311854481a8d65b04`, through a small loopback HTTP launcher.
The upstream CLI binds all interfaces; the launcher changes no server/card source.

## Verification and release

The author requires package checks, independent OAuth/browser evidence, all four
fresh scripted scenario cells, repeated physical voice/phone-passkey checks,
ordinary Hirz regression and both latency CI gates. Package Python coverage keeps
the 80% gate. Publication is followed by exact Hirz pins and clean registry-install
verification. Item 29a stays partial while any required gate remains outstanding.

### Release-order amendment — 2026-10-01

The author approved publishing after independent package CI and full local Hirz
checks pass, then requiring Hirz regression and both latency CI gates against the
released versions before closure. Requiring Hirz registry-install CI before the
initial upload is circular; local artifacts are temporary verification inputs,
and the final Hirz dependencies remain exact registry versions.

The author explicitly approved **no new paid inference** for this extraction.
Prior Haiku evidence remains historical; no claim of a fresh live-model matrix
is made. Nova remains item 29b, and neither inference ledger changes. This amends
the item 29a reuse of item 29 acceptance, not the historical item 29 results.

### Closure and shutdown deferral — 2026-10-01

The author approved closing item 29a while tracking the unresolved intermittent
companion smoke shutdown timeout separately in
[issue #7](https://github.com/BashaarJavaid/Hirz/issues/7). The
[closure evidence](../verification-log.md#item-29a-closure-with-shutdown-follow-up--2026-10-01)
links the accepted package, reference-server, scripted, physical, regression and
normal latency results, including the retained failed runs and their limits.
The temporary three-session diagnostic returns to one ordinary companion run;
timeout diagnostics and failure propagation remain in place.

Keeping extraction open until that separate defect is reproduced and repaired
was offered and declined. Reclassifying the failed runs as passes or calling
later successful diagnostics a fix is rejected: the shutdown cause is unknown.
No authorization, signed-export or latency requirement is relaxed; this amendment
only removes the unresolved cleanup defect as a blocker for item 29a closure.

## Rejected alternatives

- A TypeScript OAuth backend would add a local service and rewrite the verified
  Python transport boundary; narrow Python/React libraries reuse it instead.
- UI-only extraction would omit the roadmap's OAuth/MCP clause.
- Extracting the HTTP host, Hirz selectors or scenario controls would widen the
  reusable API and pull domain behavior into the independent project.
- Browser-held tokens, persistent token storage, arbitrary browser-entered URLs,
  networked cards, automatic registration and model-driven generic tool selection
  are outside the approved v0.1 boundary.
- Local-only or mutable Git dependencies do not meet the approved release gate.
- Historical Haiku or phone evidence cannot be described as a new test run.

## Sources

- [MCP 2025-11-25 authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
- [MCP 2025-11-25 elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)
- [Pinned official reference server](https://github.com/modelcontextprotocol/ext-apps/tree/352f6ced4d80772e92b4e7a311854481a8d65b04/examples/basic-server-vanillajs)

Commands, results and any remaining limitations belong in the item 29a entry in
`docs/verification-log.md`.
