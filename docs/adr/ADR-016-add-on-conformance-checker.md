# ADR-016: Independent add-on conformance checker

Date: 2026-09-23. Status: accepted; item 25a remains incomplete until publication and verification.

## Decision

Publish `BashaarJavaid/addon-check` as an independent Apache-2.0 repository and
`addon-check@0.1.0` npm CLI. Node 24, strict TypeScript, the MCP SDK 1.30.1 wire
validators, Ajv 8.20.0, native fetch, npm lockfile, ESLint and Node's test runner
are sufficient. No Hirz imports, server implementation knowledge or hosted service.

URL-only use initializes and discovers tools and metadata. Only an explicit
version-1 cases file permits tool calls. Every case names exact arguments, JSON
Pointers into the complete CallToolResult, repeatability, expected error state,
and permission for missing/malformed-token probes. Annotations do not authorize
execution. Preflight validates all arguments before the first call. Unsupported
input schemas skip execution. Cases run sequentially; repeatable cases authorize
one warm-up plus 20 measured calls. The checker never infers safe mutations.

Native fetch keeps a 10-second deadline and 1 MiB response cap over headers and
streamed bodies, disables redirects and retries, and supports POST JSON/SSE without
a GET stream. The bearer comes only from a named environment variable and goes
only to the exact MCP endpoint. Metadata requests never carry it. Reports retain
check results, tool names and metrics, never tokens, arguments or raw payloads.
The SDK validates protocol/result objects; Ajv supports default 2020-12 and explicit
draft-07, local references only, with formats treated as annotations.

Checks identify MCP requirements, Amazon guidance or checker policy. Missing tool
descriptions/output schemas and naming style warn. Hirz's flat inputs, speakable
shape, options and headline limits remain Hirz-specific. Every selected returned
speech field must resolve to strings; a joined English whitespace-word estimate
at 150 words/minute fails at 75 words. This is not measured Alexa audio. Formatting
checks inspect selected strings only. UI checks follow actual MCP Apps metadata
and resources/read; data-only tools are not applicable, and browser behavior is
manual review. No made-up display-mode declaration belongs to tools/list.

Exit 0 means passing requested checks, 1 means failures, and 2 means invalid
configuration or incomplete `--require-complete` evidence. Completeness requires
successful output/speech evidence for every discovered tool, a passing protected
auth probe plus successful authorized call, a passing repeatable latency case,
and no skipped required check. Warnings and manual UI review remain visible.
Reports name exactly the timed tools and retain all 20 measured samples.

## Source distinctions and authentication conflict

Sources read on 2026-09-23:

- [MCP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports),
  [tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and
  [authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
  define the protocol, schemas, resource metadata and challenge behavior.
- [Amazon's quickstart](https://www.developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-quickstart.html)
  publishes a round-trip threshold below 500 ms. Its
  [functional guidance](https://developer.amazon.com/docs/alexaplus/add-ons/functional-requirements.html)
  calls speech under 30 seconds a best practice; the 150-word/minute estimate and
  75-word gate are explicit checker policy.
- [Amazon authentication](https://developer.amazon.com/docs/alexaplus/add-ons/mcp-toolkit-authentication.html)
  lists WWW-Authenticate in 401 responses as unsupported, whereas MCP specifies
  challenge discovery. Exact excerpts are recorded once in the
  [friction log](../friction-log.md#item-25a-amazon-and-mcp-authentication-guidance-conflict--2026-09-23).
  We test scoped MCP challenges, preserve Hirz's authentication, and claim neither
  Amazon authentication compatibility nor certification. Client credentials,
  actual PKCE exchanges, refresh and production authorization remain outside scope.
- [MCP Apps 2026-01-26](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx)
  associates tools through `_meta.ui.resourceUri`; browser `ui/initialize` exchanges
  supported display modes. HTML rendering and actual security enforcement require
  manual review.

## Hirz integration and verification ownership

`scripts/smoke_household_tools.py --conformance-cli <built-cli>` records the first
successful known-valid arguments for each of the twelve tools, serializing them
with the SDK's Pydantic JSON conversion. Mutation request IDs are retained for
durable retries. An explicit what_can_you_do call closes discovery coverage.
Only what_can_you_do and get_household_context are timed; only context gets auth
probes. After the restart assertion, while the restarted issuer/server are alive,
the smoke invokes the external checker with `--require-complete`, a private
transient cases file and an environment token. Signed audit export/independent
verification follows the checker. Reports are retained beside the audit at mode
0600; temporary cases are deleted. Development migrations and the Bedrock budget
ledger are untouched. Generic assertions move only after replacement coverage
passes; runtime validators, security/transport regressions and Hirz behavior stay.

CI checks out the independent checker at a full commit SHA, installs the lockfile,
builds it and runs the same disposable smoke using native Dogwood and Bedrock off.
Public repository publication, CI evidence, packed-artifact installation and npm
registry installation are separate gates. npm publication uses the reviewed,
tested tarball after the author logs in interactively; see the
[npm procedure](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
Item 26 owns the complete per-tool latency/isolation gate; 27–29 own cards/hosts.

## Rejected alternatives

- Inferring calls or repeats from annotations would grant unintended authority.
- Importing Hirz validators or special-casing its output would defeat black-box reuse.
- Requiring persistent SSE GET would reject valid Streamable HTTP servers.
- SDK automatic retries/reconnects would obscure exact authorized call counts.
- Fetching external schema references would add uncontrolled network dependencies.
- Scanning serialized results as speech would flag private data and JSON syntax.
- Synthesizing UI display-mode fields would check an invented server contract.
- Treating warnings/manual review as a certification verdict would overstate evidence.
- Absorbing the simulator harness or item 26 suite would pull forward separate work.
