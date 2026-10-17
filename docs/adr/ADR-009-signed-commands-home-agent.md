# ADR-009 — The home obeys only commands the boundary signed (Hirz Link)

**Status:** Accepted (2026-09-17); amended the same day after a second review (hash recomputed by the signer, `home_id`, single use, reverts owned by Link, the claim scoped to bugs and bypass paths)

**Context:** The README's lead claim was that the constitution is enforced "at the AWS tool boundary, outside Hirz's process" by "an engine the agent cannot reach", and ARCHITECTURE §5.16 said the Executor "never calls an adapter directly in AWS". A review on 2026-09-16 found that this was a coding convention, not a boundary. The worker held the Home Assistant WebSocket subscription, which needs a Home Assistant token, and Home Assistant long-lived tokens cannot be scoped: a token inherits the full permissions of the user who created it (scoped tokens have been an open feature request since 2020). The process that was supposed to be unable to act without the Gateway held a credential that could unlock the door. The docs also never said which IAM role may read credentials from AgentCore Identity, and never said how a Lambda in AWS reaches a Home Assistant and a smart plug on a home network for a twelve-day judging window.

**Decision:** A small home-side agent, **Hirz Link** (`hirz/link/`), runs next to Home Assistant and holds the Home Assistant token locally; the token never leaves the house. Link makes outbound-only HTTPS connections to the worker (long-poll): observations flow up, commands flow down. When the AgentCore policy engine permits an action on a home device, the `hirz-actions` Lambda builds a command envelope (`action_id`, class, target, params, `content_hash`, `expires_at` no more than 60 seconds out, nonce) and signs it with a KMS asymmetric key (ECC P-256, ECDSA) whose `kms:Sign` permission belongs to that Lambda's role alone. The worker relays the envelope; Link verifies it against the pinned public key, checks expiry and the nonce against a replay cache, executes on Home Assistant, and returns the read-back state. Anything unsigned, tampered, expired, or replayed is refused, reported, and audited as `LINK_REJECTED`. For cloud adapters (EV, calendar) the Lambda executes directly, and write-capable credentials in AgentCore Identity are readable by its role only; the worker's role is explicitly denied them and gets read-only credentials for polling.

**Amendment (2026-09-17).** A signature proves the signer authorized particular bytes; the chain also has to establish why those bytes were authorized. Four gaps in the first version, each now closed with a test: (1) the `action_hash` the approval is matched on came from the worker, so the Lambda now recomputes it from the class, target, params, and scheduled time and refuses on a mismatch; (2) the envelope named no home, so a command could be relayed to another home with the same entity name: it now carries `home_id` and Link checks it; (3) an approval within its TTL could be redeemed by a second, freshly signed envelope: Link refuses a `content_hash` it has already executed in the last 24 hours; (4) the relock after a ten-minute unlock was a second command the cloud promised to send, and "fail closed" does not relock a door: the envelope now carries the revert, and Link stores it durably and runs it from its own clock, offline and across restarts. Link also reports `OUT_OF_BAND_CHANGE` when a governed device changes with no command from Hirz. **The claim is scoped:** this design stops a bug or a bypass path in Hirz's own processes. It does not stop a fully compromised worker, which can still tell the boundary that an approval happened and can supply false context facts. Verifying the member's passkey inside the signer closes the first of those for `security.*` classes and is ADR-010.

**Reasoning:**

- The worker becomes an untrusted relay for actuation: it can delay or drop a command, never forge one. A bug or a bypass path in Hirz's own processes has nothing to act with. The claim becomes literally true and testable: *Hirz's own processes hold no credential that can act on a device; only commands the policy engine authorized are signed, and the home obeys only signed commands.*
- It answers reachability with no tunnel, no port forwarding, and nothing exposed to the internet, which is also the only architecture a real customer would accept.
- It turns the lead claim into an adversarial test and a five-second demo moment instead of a sentence.
- KMS keeps the private key out of every Hirz process, and the key policy is a one-line statement of who may authorize an action.

**Alternatives considered:**

- *Credential split plus a tunnel (the minimum).* The worker gets a Home Assistant token from a user in the `system-read-only` group; the write token lives in AgentCore Identity for the Lambda only; a Cloudflare-style tunnel exposes Home Assistant. Rejected as the primary design: assigning that group requires editing `.storage/auth` by hand, the evidence that it blocks `call_service` over REST and WebSocket is thin (2019 documentation and one community thread), Home Assistant ends up exposed through a third party, and the house still obeys anyone who holds the write token. The IAM half of this option is kept for cloud adapters. It is also the documented fallback if Link slips past the cut line: the README claim is then reworded to exactly what exists and the threat-model rows stay Planned.
- *Leave it as a convention and reword the claim.* Honest, free, and it gives up the project's lead differentiator.
- *Sign in the worker.* Pointless: the process being distrusted would hold the key.
- *Boundary-sign observations too.* Would not help: facts originate in the home, and the limit recorded in ADR-003 (independent about policy, not about facts) is inherent.

**Consequences:** A new component with its own tests: unsigned, tampered, expired, and replayed commands are each refused and audited; `hirz doctor --aws` sends one signed and one unsigned command. New AWS resource: one KMS key, pay-per-use, about a dollar a month, approved by the author on 2026-09-17. New failure modes, all fail-closed for actuation: Link offline (domain `unavailable`, twin fallback labeled simulated), KMS unavailable (no signature, no action). Local mode has no Link and no outside boundary and says so. Link's verification code is pure and runs in CI against a local development key behind the same signer interface. The same-trust-domain caveat stands: one AWS account and one developer deploy the Gateway, the Lambda, and the key, and `THREAT_MODEL.md` keeps "Compromised AWS account: No". Friction-log candidate: Home Assistant tokens cannot be scoped.

## Item 36 infrastructure secret exception — 2026-10-16

For the explicitly disposable AWS acceptance deployment, Secrets Manager holds
database credentials, the audit signing key, the tick bearer secret and Cognito's
machine-client secret. This is an approved **infrastructure-secret exception**;
operational adapter credentials still belong to AgentCore Identity and no Home
Assistant credential enters AWS. The synthetic Identity provider is backed by an
explicit Secrets Manager secret containing a nonfunctional marker, registered
through the native EXTERNAL secret-reference contract. It has no working device
credential. A separate workload identity lets the signer-role positive-control
probe exercise the Identity API. All of these resources are owned by the
acceptance stack and removed at teardown.

The worker, setup and MCP roles explicitly deny `kms:Sign`, Identity credential
retrieval, and direct/BatchGetSecretValue access to the synthetic provider's backing
secret. Among runtime roles, only `hirz-actions` may sign or read that credential.
The MCP role also has no Gateway execution, Lambda execution or scheduling
authority. [Identity's resource-scoping contract](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/scope-credential-provider-access.html)
requires the provider, token vault, workload identity and directory resources.
The [Gateway policy role](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-permissions.html)
needs authorization, partial authorization and policy-engine read permissions.
Policies are synthesized and checked offline; actual IAM denials and signer-role
positive controls are still live acceptance gates, not earned claims.

RDS master credentials are granted only to the setup task. It creates a separate
`hirz` login without superuser, database-creation, role-creation or replication
privileges, owning the disposable database's application schema so migrations and
materialized-view refresh work. Every connection uses `sslmode=verify-full` and
the vendored AWS us-east-1 RDS CA bundle. [RDS certificate verification](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/PostgreSQL.Concepts.General.SSL.html)
is required; disabling TLS or accepting any server certificate was rejected.
The audit key is generated only by explicit initialization against an empty,
consistent schema, then fetched and validated in memory at startup. Missing or
malformed existing keys fail; startup never generates or replaces one. Environment
variables carry secret ARNs, not values. One-off invitations and audit exports
are sealed to the local runner's ephemeral recipient key before entering logs.

The S3 anchor bucket has 30-day governance retention and runtime put-only access.
The approved deployment-cleanup role may bypass governance solely to remove this
owned deployment, including retained versions, after evidence export. The command
key has a seven-day pending-deletion window. Neither resource claims audit anchoring
or signed device execution yet; those remain items 38b and 38a/38d respectively.
Storing adapter credentials in worker environment variables, sharing the RDS master
login, silently repairing signing keys, and treating the LOG_ONLY placeholder as
policy enforcement were rejected. See the [acceptance procedure](../development.md#item-36-aws-acceptance).
