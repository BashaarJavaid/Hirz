# Architecture Decision Records

One file per consequential decision, each with the alternatives that were rejected and why. Load the specific ADR relevant to what you're working on rather than all of them.

- [`ADR-001-python-core-typescript-surfaces.md`](./ADR-001-python-core-typescript-surfaces.md) — Python core, TypeScript for MCP App, companion app, simulator, and CDK
- [`ADR-002-postgres-over-dynamodb.md`](./ADR-002-postgres-over-dynamodb.md) — PostgreSQL as the graph of record; AgentCore Memory for conversational memory; item 18 audited constraint history; item 20 private sessions and consent-gated preferences
- [`ADR-003-constitution-yaml-to-cedar.md`](./ADR-003-constitution-yaml-to-cedar.md) — YAML constitution with a constrained grammar, compiled to Cedar and enforced twice
- [`ADR-004-no-ml-risk-scoring.md`](./ADR-004-no-ml-risk-scoring.md) — Table-driven risk bands, no formula, no model
- [`ADR-005-deterministic-planner.md`](./ADR-005-deterministic-planner.md) — MILP on HiGHS; the LLM only narrates; item 17 read-only proposals, strict comparison gates, shared causal simulation controls and archived historical experiment; item 18 coordination, comfort preferences and manual holds; item 20 accepted preference windows; item 22 planned-device approval resumption
- [`ADR-006-twin-first-adapters.md`](./ADR-006-twin-first-adapters.md) — Every adapter ships real and twin behind one interface; the twin is product, not test scaffolding; credential-free energy feeds with explicit coverage and tariff provenance; local HA single-attempt execution and scenario-only read fallback; item 22 disposable executable scenarios
- [`ADR-007-alexa-surface-strategy.md`](./ADR-007-alexa-surface-strategy.md) — Build to the real add-on contract; demo through an emulated host; one read-only clip through the community Skill bridge
- [`ADR-008-agentcore-topology.md`](./ADR-008-agentcore-topology.md) — Runtime hosts the MCP server; Gateway + Policy is the second enforcement point; cost posture
- [`ADR-009-signed-commands-home-agent.md`](./ADR-009-signed-commands-home-agent.md) — The home obeys only commands the boundary signed; Hirz Link holds the Home Assistant token in the house
- [`ADR-010-passkey-verified-approvals.md`](./ADR-010-passkey-verified-approvals.md) — Security approvals proven to the signer by the member's passkey, so the worker can relay an approval and cannot make one (below the cut line)

- [`ADR-012-explainer.md`](./ADR-012-explainer.md) — validated narration, selected facts, fixed Converse contract and audited persistence; live Bedrock remains item 38
- [`ADR-013-mcp-transport.md`](./ADR-013-mcp-transport.md) — fixed local guards, stateless JSON transport and generic onboarding; OAuth and household tools remain later work

- [`ADR-014-local-oauth.md`](./ADR-014-local-oauth.md) — simulated local consent, SDK PKCE linking, resource-bound JWTs, bounded key cache and current member mapping

- [`ADR-015-household-tools.md`](./ADR-015-household-tools.md) — partial local twelve-tool contract, durable retries, private simulated trust checks and bounded headless host

- [`ADR-016-add-on-conformance-checker.md`](./ADR-016-add-on-conformance-checker.md) — independent explicit-case MCP checker, source distinctions, scoped evidence and disposable Hirz integration
- [`ADR-017-tool-latency-and-isolation.md`](./ADR-017-tool-latency-and-isolation.md) — authenticated local timing protocol, audited lifecycle corpus and concurrent household-isolation gate
