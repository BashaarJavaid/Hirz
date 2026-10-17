# ADR-008 — AgentCore topology and cost posture

**Status:** Accepted (2026-09-15); amended 2026-09-16 (two roles) and 2026-09-17 (the worker holds no device credential; KMS signing key and S3 anchor bucket added, see ADR-009; the worker is driven by a one-minute tick and calls the Gateway with a machine token; policies are scoped per household)

**Decision:** In AWS, the Hirz image runs in two roles. The **`mcp` role** (MCP server, pipeline stages 1–6, no adapter or Gateway calls) runs on **AgentCore Runtime** with `protocol: MCP` and a `CUSTOM_JWT` authorizer backed by a Cognito user pool (PKCE S256). The **`worker` role** (scheduler sweep, pollers, the relay endpoints for Hirz Link, Executor, companion API including the hosted demo, Ring webhook endpoint, web push) runs as one small always-on **App Runner** service (Fargate behind an ALB as fallback). Tools that act write the action as `scheduled` for now and return `status: executing`; the worker executes within seconds. The Executor's action tools are exposed through an **AgentCore Gateway** target (`hirz-actions` Lambda) with a **Policy engine** holding the Cedar/Dogwood set compiled from the active constitution; the Executor calls the Gateway with a policy session id so temporal approval rules apply. **AgentCore Memory** holds conversational and extracted-preference memory; **AgentCore Identity** holds outbound adapter credentials; **Bedrock** serves Claude Haiku 4.5 and Sonnet 5 for Hirz and the emulator (Haiku 4.5 by default, Nova Lite selectable, ADR-007); **EventBridge Scheduler** plus a tick Lambda (targeting the worker) drive scheduled actions; **RDS Postgres** is the graph of record; observability flows through AgentCore Observability to CloudWatch. Infrastructure is AWS CDK (TypeScript). The `hirz-actions` Lambda does not call devices in the home: on a permit it signs the command with a **KMS asymmetric key** only its role can use, and the home-side agent, Hirz Link, executes only signed commands (ADR-009); for cloud adapters it executes with write-capable credentials that only its role can read. The audit chain head is anchored to an **S3 bucket with Object Lock** (governance mode, so `cdk destroy` still works), put-only for the worker. Everything except RDS and the worker service is pay-per-use, the KMS key and the anchor bucket included (about a dollar a month together, approved by the author on 2026-09-17); the stack is deployed for recording and judging and destroyed after, with a $40 budget alarm.

**Why two roles (added 2026-09-16):** a Runtime session is an isolated microVM that exists only while an invocation or its background task runs (15 min idle, 8 h maximum), and only the invocation path is reachable from outside. That fits the MCP server and nothing else in Core: a scheduler sweep, adapter pollers, the long-poll endpoints Hirz Link dials into, a Ring webhook receiver, and a browser-facing companion API all need a process that is always running and an HTTPS endpoint that is not the JWT-guarded invocation path. Putting execution inside a tool call would also route the Gateway and a third-party network call into Alexa's 500 ms budget, which the design forbids. The worker is the one always-on line item besides RDS, accepted explicitly by the author on 2026-09-16 for the judging window.

**Tick-driven worker, machine token, household scoping (added 2026-09-17):** App Runner throttles an instance's CPU while no request is in flight, so a sweep on a background thread is not guaranteed to run on an idle service. All periodic work therefore runs inside a request: an EventBridge rule fires the tick Lambda every minute and the sweep and any due poller run in `/internal/tick`. `ROADMAP.md` item 36 tests a quiet half hour, and Fargate behind an ALB remains the fallback. The worker calls the Gateway with its own Cognito machine token, since a scheduled action comes due long after the member's token expired; the requester's role is therefore an input Hirz supplies, and the docs no longer call it independently evaluated. Every policy is scoped to its household, and hosted-demo households are evaluated by the local Dogwood evaluator only, so throwaway households never touch the engine's 25-temporal-policy quota.

**Reasoning:**

- The AWS Builder criterion rewards "multi-service pipeline (Bedrock + AgentCore + Strands)" and "agentic architecture with Claude", and penalizes "single Bedrock call". Here AWS operates Hirz's enforcement (Policy), state (Memory), identity (Identity), and hosting (Runtime); it is the backbone, not decoration.
- AgentCore Runtime's MCP hosting serves the `401` challenge and the Protected Resource Metadata document, which is exactly what Alexa+ account linking discovers. Cognito supports PKCE S256 and `code_challenge_methods_supported`, satisfying the add-on requirement.
- AgentCore Policy is the only managed service in the design that gives an out-of-process, auditable, temporal enforcement point for the constitution (independent about policy; context facts come from Hirz, hash-bound, per ADR-003). Its CloudWatch decisions become audit evidence.
- The $150 credit is finite. Pay-per-use services cost cents at demo scale; RDS is the one always-on line item, so it lives only during the judging window. Local Compose is the everyday path.

**Alternatives considered:**

- *ECS Fargate or App Runner for the MCP server.* Simpler ops for a plain FastAPI service, but loses the Runtime's PRM/JWT integration and the "AgentCore runs Hirz" story, and Fargate is always-on cost. Kept for the worker role only, where always-on is the requirement.
- *Everything in the Runtime container (the original decision).* Rejected on 2026-09-16: no home for long-lived work, no reachable companion API or webhook endpoint, a tick Lambda that must mint a JWT and pay a microVM cold start per tick, and execution inside the tool-call budget.
- *Lambda-only worker (scheduled Lambda for the sweep and pollers, API Gateway + Lambda for the companion API and webhooks).* Pay-per-use and within the original cost convention, but it cannot hold Hirz Link's long-poll connections, and it spreads one process across four resources. Rejected for fidelity and moving-part count; it remains the fallback if App Runner and Fargate both fail.
- *Lambda for everything.* Streamable HTTP with SSE and stateful elicitation fit poorly on Lambda; rejected.
- *Skip Gateway; evaluate Cedar only in-process.* Cheaper, but then "enforced at the AWS boundary" is untrue. Rejected (see ADR-003).
- *DynamoDB instead of RDS to be fully serverless.* Rejected in ADR-002.
- *Terraform.* Fine, but CDK is TypeScript-native, matches the surfaces' language, and is what Amazon's own Alexa tooling references.

**Consequences:** `hirz doctor --aws` must verify PRM, `401`, a Runtime tool call, an "act" tool executed by the worker within 10 s, a Gateway policy decision, a signed command accepted by Hirz Link and an unsigned one refused, an audit anchor written and verified, the companion API over HTTPS, and a scheduler tick before any AWS claim appears in the README. Runtime cold start on a new session is measured and reported separately from the warm latency budget, never folded into it. Temporal policies require the Gateway role to have `bedrock-agentcore:GetWorkloadAccessToken`, and all AgentCore resources must sit in one account and region (us-east-1). Changing temporal policies invalidates open sessions; activation starts a new plan session.

## Item 36 acceptance amendment — 2026-10-16

The approved acceptance deployment uses account `661550216013`, profile `hirz`,
region `us-east-1`, application stack `HirzItem36`, and dedicated toolkit
`HirzItem36Toolkit` with qualifier `hirzitem36`. It uses one ARM64 Fargate task
(0.25 vCPU, 512 MiB), private subnets in `10.36.0.0/16`, one NAT gateway/EIP,
and an internal ALB reached through a CloudFront VPC origin. NAT and ALB are
explicit exceptions to the always-on restriction for this acceptance window.
The generated CloudFront hostname is the companion's exact origin and RP ID;
there is no purchased domain or hosted zone. Application caching is disabled;
cookies, authorization and query strings pass through. Only the private
CloudFront–ALB hop uses HTTP. The approved zones are `us-east-1a`/`use1-az1` and
`us-east-1b`/`use1-az2`; their account mapping must be checked before deployment.

AWS [stopped accepting new App Runner customers on 2026-04-30](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html).
No App Runner deployment attempt was made in this implementation session.
Fargate is therefore selected for the approved deployment, rather than waiting
for the quiet-window test to trigger the fallback. ECS Express Mode was rejected:
the reviewed stack needs explicit control of its private origin and allocation.
A public ALB, a second NAT gateway, a domain purchase and a larger task were not
approved. [CloudFront's VPC origin prerequisites](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-vpc-origins.html)
include an internet gateway; the VPC has one, without assigning application
or database public addresses.

RDS is encrypted, Single-AZ PostgreSQL 16.15, `db.t4g.micro`, 20 GiB gp3, without
a final snapshot for this disposable deployment. `WorkerDesiredCount` accepts
only 0 or 1 and defaults to 0. Explicit one-off tasks initialize secrets, migrate,
and seed; a second deployment starts the worker, and an identical deployment
must then be repeated. Startup never migrates. The fixed `FixtureStart` parameter
makes the 24-hour twin input and configuration hash stable across task restarts.
Real enrollment and phone activation are required; bootstrap never activates a
constitution. Hosted observations remain `twin`, enforcement `dogwood-local`.

The Runtime exposes generic onboarding only under CUSTOM_JWT. Cognito disables
public signup, uses five-minute access tokens, a public authorization-code client
with callback `http://localhost:8765/callback`, and native `hirz/read`, `hirz/plan`,
`hirz/act`, `hirz/verify` scopes. Existing local colon-separated scopes are unchanged.
The machine client has only `hirz-gateway/invoke`. Cognito validates supplied
PKCE S256 but does not require every authorization request to supply it; this
amendment does **not** claim mandatory PKCE. Household mapping remains item 38.
Gateway Policy is LOG_ONLY and its sole no-input tool, `boundary_unavailable`,
always raises a Lambda error. [Gateway reports target errors as tool errors](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-debug-messages.html).
It has no command-signing code, action execution or fabricated audit result.
The signer role is exercised separately by a temporary synthetic positive control.
Real Gateway contracts remain item 37.

Ticks are bodyless, constant-time bearer authenticated and limited to 50 seconds
of processing; cancellation settles SDK/solver threads before returning failure.
CloudFront response, tick HTTP, ALB idle and tick Lambda timeouts are respectively
60, 65, 70 and 75 seconds. A successful tick returns 204, processing failure 503.
Due actions and bounded endings run first, then awaited extraction, contact
advancement, drafting, plan preparation, refresh/polling and twin work. No AWS
background service loop is started. Existing database locks and claims remain
authoritative. One-time schedules are a deterministic projection of persisted
active action rows, with no flexible window, empty input and deletion after firing;
the minute rule repairs missing schedules and removes obsolete ones. There is no
scheduler outbox or new scheduling migration. Inference is disabled in acceptance.
Memory has no strategies and three-day event expiry; log groups retain seven days.

The financial prerequisite is unresolved: the supplied account report said
$149.96 promotional credits remaining, expiring 2028-08-31, on a paid plan.
That is a prior report, not a fresh billing verification. Approved services include
Fargate under ECS and Scheduler under CloudWatch Events. The approval remains
**zero out-of-pocket**, a **$10 incremental budget**, and **24 hours maximum**
from the first deployment attempt, including failures. Alerts and the runner's
clearance record are not spending caps. Taxes, unreported usage, deployed capacity
and successful deletion have not been verified. No live deployment is authorized
until account-specific exposure is resolved consistently with that constraint.
The detailed [procedure](../development.md#item-36-aws-acceptance) owns deployment
and teardown steps; [verification](../verification-log.md#item-36) owns results.

### Tax exception — 2026-10-16

The author subsequently accepted taxes as an exception to the zero-out-of-pocket
requirement ("dont worry about taxes"). This supersedes the tax prerequisite above;
it does not authorize uncovered service charges, a larger incremental budget, or
a longer deployment. The $10 service budget and 24-hour maximum remain unchanged.
Credit eligibility, competing usage and the deployment estimate still require
verification. Requiring tax clearance after this instruction is rejected; treating
it as unrestricted spending approval is also rejected. The acceptance runner's
clearance record must cite this exception explicitly when resolving service-charge
exposure. A credit balance or clearance file still provides no hard spending cap.
