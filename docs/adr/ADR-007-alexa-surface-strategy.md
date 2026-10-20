# ADR-007 — Build to the real add-on contract; demo through an emulated host; one read-only clip through the community Skill bridge

**Status:** Accepted (2026-09-15); revised 2026-09-17 (the Skill-bridge alternative was rejected for a reason that was factually wrong; corrected below)

**Context:** Alexa+ add-on development is currently available to select partners working directly with Amazon. The hackathon rules explicitly accept "a self-hosted MCP server (spec 2025-11-25 or later, Streamable HTTP) or an Agent Skill, or a simulated experience" and say participants "can simulate experiences via web app". The author has no add-on access and no Alexa+ device.

**Decision:** Hirz's MCP server is built to the published add-on contract verbatim (Streamable HTTP, OAuth 2.1 PKCE S256, Protected Resource Metadata, `401` challenge, MCP Apps for visuals, tool and UX functional requirements, latency budget). The primary demo surface is the **Hirz Simulator**: a browser host that runs a genuine MCP client (a Strands agent on Bedrock, Claude Haiku 4.5 by default, Nova Lite selectable) against the genuine server, implements the MCP Apps host bridge, provides voice in/out, and switches between Echo Show and Echo Dot behavior. It is labeled as an emulation. Its generic parts (the MCP client with OAuth, the MCP Apps host bridge in an Echo Show frame, the voice-only mode, the transcript) are published as a separate open-source harness together with an add-on conformance checker, and the simulator is built on them. After the AWS deploy, the unmodified community Skill bridge is pointed at Hirz's public MCP endpoint for one read-only clip recorded in Amazon's developer-console simulator.

**Reasoning:**

- Building to the contract means the day access opens, the work is `alexa-ai new mcp`, metadata, and certification, not a rewrite. Every contract item is a test.
- An emulated host that actually speaks MCP to the real server proves more than a scripted video: the tool calls in the transcript are real.
- The emulator's model is a setting, not a claim. Nobody outside Amazon knows which model class Alexa+'s orchestrator runs, so "closest stand-in" is a guess, and the one thing the demo cannot survive is the emulator choosing the wrong tool on camera. The default is therefore the most reliable tool-caller available on Bedrock (Claude Haiku 4.5); Nova Lite remains selectable for anyone who wants the Nova-family behavior, and the honesty banner names whichever is in use. (Decision revised 2026-09-16; the original default was Nova Lite.)
- The simulator is also the product's own test bench and the fallback surface for any MCP-capable assistant.

**Alternatives considered:**

- *Wait for add-on access.* Not available on the hackathon timeline.
- *Alexa Skill (ASK) with hand-written intents.* Would demonstrate on hardware but would not be an MCP add-on, would not exercise MCP Apps, and would fail the "actually calls the required technology" check for the Alexa+ track as specified.
- *Community Skill bridge ([KayLerch/alexa-skill-mcp-bridge](https://github.com/KayLerch/alexa-skill-mcp-bridge)) as the primary surface.* The original reason recorded here, "requires an Echo the author does not own", was wrong: the bridge's README says the Alexa developer console's Test simulator runs the deployed Skill in the browser and a device is optional. The real reasons it is not the primary surface: (1) no OAuth account linking (it authenticates to the server with one static secret, so Hirz's token-`sub` → member → role model cannot flow through it and every request arrives as one fixed identity); (2) no visuals (`visual` is always null, so no MCP App card renders); (3) a different orchestrator (Nova 2 Lite, which this project moved its own emulator away from for tool-calling reliability); (4) Skill-style invocation ("Alexa, open …"), which is not the add-on experience. It is also another entrant's hackathon project (Apache-2.0). It is used for credibility, not compliance: the rules explicitly allow a simulated Alexa+ experience. Whether it works on classic (non-Alexa+) Echo devices is unverified; no hardware is bought on that basis.
- *Claude/ChatGPT as the demo host.* Real MCP Apps hosts, but they are not Alexa and would confuse the track story; useful only as a secondary interoperability check.

**The bridge clip, bounded.** Gallery only since 2026-09-17 (its five seconds in the video's close went to the refused command replay, because the organizers had confirmed a simulator is an accepted path and the replay shows the lead claim). One short gallery clip and one image: the Alexa developer console answering one read-only question ("what's going on tonight?") with Hirz's `speakable`, labeled on screen "Alexa developer console, via a community Skill bridge. Identity and cards are not available on this path." The bridge holds a static secret and cannot identify anyone, so under Hirz's own model it must never be able to act: its token carries the `hirz:read` scope only, and the verify step is that an act tool called with that token is refused. The bridge is used as it is, with attribution, never forked into this repo; its stack is deployed for the recording and destroyed after (cents, approved 2026-09-17). If the clip looks bad it moves to the gallery only. Nothing else depends on it.

**Interoperability proof.** One gallery and README screenshot of the same server and the same cards rendering in a second real MCP Apps host, to show the cards are standard MCP Apps and not something that works only in Hirz's simulator. Kept out of the video so the track story stays clean.

**Access.** The MCP Toolkit is "available to select partners only" (Alexa+ docs, checked 2026-09-16). The author asked the organizers on the hackathon forum whether participants can get toolkit or simulator access; the organizers confirmed on 2026-09-17 that no participant access exists and that a self-built simulator is an accepted path (`docs/friction-log.md` entry 1). This closes the question this ADR was written under uncertainty of, without changing the decision above.

**Consequences:** The simulator must be honest (banner, transcript, badges) and must enforce Alexa+'s voice-only and option-count rules so the preview is faithful. `HIRZ_LLM=off` swaps the emulator for a scripted host so CI and credential-less judges can run the demo.

## Household tools amendment — 2026-09-23

The local authenticated server now registers twelve household tools with structured native-rendering data and no UI resources. A pinned Strands headless host consumes actual tools/list, keeps conversation context and requires explicit confirmation for commitments. The $1-capped live selection gate remains distinct from deterministic SDK execution. Full contract and rejected alternatives: [ADR-015](./ADR-015-household-tools.md).

## Simulator submission scope — 2026-10-20 (author approved)

The author approved the Simulator submission plan and requested the roadmap be
updated after the final item 37 acceptance failed. This amendment supersedes
the earlier requirement to finish items 37–38a before submission and the
AWS/signed-command video close. It changes submission scope, not the original
verification gates or completed evidence.

The [official rules, §4](https://amazonappdev2026.devpost.com/rules), checked on
2026-10-20, explicitly permit an Alexa+ simulation built with an AI or agentic
tool, without a prescribed framework or MCP interface. Its source must be in
the submitted repository and its functioning simulation shown in the video.
Hirz retains its existing real MCP server/client and local deterministic
pipeline. The no-credential judge path uses `HIRZ_LLM=off` with the scripted
host and labeled twin devices; it must be verified from the final release.
Already verified model integrations remain documented with their measured
scope. This decision grants no new model-call budget or deployment permission.

The submission keeps both households, the scam check, proposed rules activated
through the passkey companion app, planning/re-planning, local rule refusal,
phone-gated simulated actions, source labels and signed local audit evidence.
Human testing, two video reviewers, source/run instructions and release checks
remain required work. The physical plug is an optional addition once its real
state/power and restoration gates pass; it does not block the Simulator entry.
Unverified push/email delivery must not be depicted as working; the verified
companion-app path can be opened directly.

Full AWS acceptance (37–38), production Link (38a), anchors (38b), public hosted
demo (38c), boundary passkeys (38d), tamper playground (38e), new judging-stack
deployment/alarm work (39) and credibility clips (41a) are deferred beyond
submission. Local preparation is retained, not relabeled complete. Cost
reconciliation and verified cleanup remain obligations. There is no fifth
item 37 run. The completed item 36 and other verified AWS integrations may be
documented for AWS Builder; the separate conformance-checker/host-harness
contribution remains the Open Source entry. Neither entry permits unearned
cloud, identity or physical-device claims.

The roadmap owns the revised order and dates. Items 40–41 must align the
recording script, README, gallery and submission checklist with this scope;
the close uses the local rule decision and signed audit rather than an
unverified cloud-signed command or physical replay refusal. Threat-model rows
stay at their earned status, and deferred items retain their original checks.

Rejected: another full AWS retry (the author has no time and authorized no
fifth window); weakening acceptance or calling publication alone completion
(would misstate enforcement); presenting a simulated result as live AWS or
physical execution (would misstate the demo); deleting the unfinished work
(it remains useful after submission).
