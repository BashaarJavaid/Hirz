# Demo Script (under 3 minutes)

**Revised 2026-10-23 for the approved [Simulator submission scope](../ROADMAP.md#cut-line-and-fallbacks).**
The close is the locally refused unlock and its signed audit verification. No
AWS enforcement, Link replay, console footage or live-device shot appears.
Companion screens are opened directly, because push and email delivery are
unverified. Every device badge reads `simulated`; the rate is labeled
*published ComEd rate*. This is the recording plan, not evidence that the
recording exists.

One customer, two homes, one evening. Malik runs the smart home at his own place and set one up for his parents. The video opens cold on a person with a problem, shows one rule being written and then enforced, and closes on the door. Three beats and a close; each beat proves one thing.

Every number on screen, including every dollar figure, comes from the cited scenario runs (`scenarios/parents-scam-check.yaml` and `scenarios/demo-evening.yaml`, seed 20261013) and maps to an audit row. No savings figure is typed into a caption, the README, or the Devpost description; whatever the run says, the video says. Recorded from the Hirz Simulator in Echo Show mode, rendered at 1280×800 (Amazon's 768×480 base canvas × 1.667, `docs/design.md`), with a five-second switch to Echo Dot (voice-only) mode inside beat 2 to prove voice completeness.

Judges are not required to watch past 3:00 or to run anything, so the video must carry the whole case. What left the video on 2026-09-17 (the loop animation, the Dad/dishwasher provenance beat, a standalone Echo Dot beat, the morning scorecard as its own beat, the Cedar view as a running thread) is still built, still asserted in the scenario, and shown in the README and the image gallery.

**Rules honored:** no third-party trademarks beyond the sponsor's platform (the car is "the car"; no wearable appears), no copyrighted music, English, project shown functioning on the intended surface, a `live` or `simulated` badge wherever data appears, spoken headlines of about 20 words or fewer.

---

| Time | Beat | On screen | Spoken / captions | The one thing it proves |
|---|---|---|---|---|
| 0:00–0:50 | **The hook: "Is it really him?"** | No title card. Lower third: *Mom's home, 5:05 PM*. Simulator in Echo Show mode on Mom's linked account. Mom, phone still in hand: "Alexa, Malik just called from a strange number. He says he's in trouble and needs five hundred dollars. Is it really him?" Transcript rail: `assess_request_risk` → band CRITICAL, then `verify_trusted_identity`. Verification card: one headline ("This looks like a scam. Don't send anything yet."), three signals, status *checking with Malik*. Cut to Malik's phone: "Your mom is checking it's really you. Did you just call her from another number asking for $500?" He taps **No, that wasn't me.** The card moves, on its own, from *pending* to *Malik says it wasn't him*. Mom: "Alexa, is it him?" (Alexa cannot speak unprompted, and the video does not pretend it can.) If the cold open is at 0:47 or under: the doorbell rings at Mom's (5:25 PM, unexpected); the card adds a warning and Malik's phone gets a second notification. | Alexa: "This looks like a family-impersonation scam. Don't send anything yet. I'm checking with Malik on his own phone. Ask me again in a minute." … "Malik says that wasn't him. Don't send anything." Optional courier line: "An unexpected doorbell press followed your reported request. Don’t hand anything over. Hirz cannot identify the visitor." | Trust comes from the household's own records, never from the caller. Hirz gives Mom one thing to do: ask first |
| 0:50–1:50 | **The rule, then the evening inside it** | Lower third: *Malik's home, 5:31 PM*. Malik, just home, still rattled: "Alexa, from now on, never unlock the door for someone we're not expecting." Transcript: `propose_household_rule`. Phone: one English sentence, the derived situation lines (**Unexpected visitor: ask on phone → never**; *Expected arrival: still asks on your phone*; *Hirz does not identify the visitor*), a collapsed line with the compiled Cedar `forbid`. He taps **Activate** (passkey). Audit: `CONSTITUTION_ACTIVATED v8`. Then: "What's going on tonight?" The plan card (inline: one headline figure, three rows, one Approve button): in the peak window until 7, run the house off the battery, pre-warm the living room for Mom by 6:45, hold the car until after 9. Dollars saved tonight first, then the annualized figure from the backtest. `simulated` on every device and on the scenario's weather; the rate is labeled *published ComEd rate*. Malik: "Don't charge the car past 50, I'm not driving tomorrow." Alexa confirms the constraint at once; a second later the card re-renders, the EV bar moves, and the constraint shows "Malik, tonight". Malik: "Do it." Five seconds in Echo Dot mode: the same answer, voice only, no card. Time-lapse 5:35 → 6:40 with two audit rows (`EXECUTE energy.battery_dispatch`, `EXECUTE energy.hvac_adjust living_room 72`). | Alexa: "I've written that as a rule and sent it to your phone. It won't take effect until you approve it there." … "You're in the peak window until 7. I'll run the house off the battery, warm the living room for your mom, and hold the car until after 9." … "Got it, the car stops at 50. I'm updating the plan." … reads back the revised plan and confirms. Caption: "Anyone in the room can propose a rule. Only a person on their own phone can activate one." | The household writes the boundary, on camera; autonomy inside it is useful |
| 1:50–2:35 | **The door** | 6:40 PM. Doorbell card: snapshot, context "Nobody is expected right now". Malik: "Let them in." Transcript: `execute_household_action request_door_unlock` → `DENY_CONSTITUTION`, citing constitution v8. 7:04 PM. Doorbell card (twin doorbell, labeled simulated): "A vehicle arrived at 6:58. Mom is expected at 7:00." Malik: "That's my mom, let her in." Approval card with no Approve button: *approve on your phone*. Phone: the snapshot and "Someone is at the front door. Mom is expected now. Unlock for 10 minutes?" → **Approve** (passkey). Lock labeled `front door lock (simulated)`. Audit: `ASK → APPROVED (app, Malik) → EXECUTED unlock → EXECUTED relock`. | Alexa: "You added a rule tonight: I never unlock for someone who isn't expected." … "Unlocking the door needs your approval on your phone. I've sent it." … "Door unlocked for 10 minutes." Caption: "Same lock, two outcomes. Never, because the family said so. Ask, on a phone, never by voice." | The rule written at 5:31 changes behavior at 6:40; security is approved on a phone, never by voice |
| 2:35–2:55 | **Close** | Scorecard card: dollars saved tonight (the figure from the cited run), the annualized figure, peak kWh avoided, 1 request verified, 1 action blocked by tonight's rule. Five seconds: the companion Audit page on the 6:40 row, `DENY_CONSTITUTION` citing v8, directly above the 7:04 `APPROVED (app, Malik)` row. Five seconds: a terminal running `hirz verify-audit` on the household, reporting the signed chain verified with its row count. Tagline and repo URL. "Alexa+ track · AWS Builder · Open Source". | Caption: "Every decision is a signed row in a hash chain. Change one and verification fails." Closing line: "Hirz. House rules for the AI in your home, and your parents'." | The boundary is enforced locally and every decision is verifiable afterwards; no cloud enforcement or physical replay is claimed |

---

## Production notes

- Record the simulator at 1920×1080 with the Echo Show frame as the hero and the tool-call transcript as a slim rail; no split screens except the phone beside the Echo at the three phone moments.
- Use `hirz scenario step --to` to pause before each beat; the clock speed is 60× between beats and 1× during speech.
- The spine of the video is one rule: proposed by voice at 5:31, activated on a phone at 5:32, enforced at 6:40. The scenario activates v8 before the plan is approved, because activating new temporal policies starts a new policy session and re-issues pending approvals (`docs/constitution.md` §4).
- The through-line is one person: the Mom who asked at 5:05 is the Mom at the door at 7:04.
- Three motions only, all CSS transitions: the EV bar moving on re-plan, the verification card going from *pending* to *Malik says it wasn't him*, the door going locked → unlocked → relocked.
- Captions for every spoken line (accessibility and judges on mute). The captions spell the product name.
- Voice: the simulator's TTS for Alexa; the author's own voice for Malik, a second voice or captioned text turns for Mom.
- The phone is the companion app in a phone-width browser window.
- No Skill-bridge, AWS console or Link footage appears: items 38a and 41a are deferred beyond submission (2026-10-23).
- The video follows one promise: the family grants useful authority and sets a limit (5:31), Hirz does helpful work inside it (the plan), an ordinary request that crosses the limit is refused (6:40), a legitimate authenticated action succeeds and is verified (7:04), and every decision can be verified afterwards (the close).
- The courier moment goes in the video only if the cold open stays at 55 seconds or less; otherwise it lives in the scenario assertions, the gallery, and the description.
- Export with both scenario run ids in the description; the README links the runs' audit exports so anyone can verify the numbers.


## Recording and human-check gates — 2026-10-19

Use the [submission readiness review](submission.md#readiness-review--2026-10-19)
for current blockers. The script above is the intended recording, not evidence
that every shot exists. Record only after the cited scenario exports verify.
The live lamp and signed-command shots were removed on 2026-10-23 under the
approved scope; the close uses the local refusal and `hirz verify-audit`. Never
label a simulated result as an AWS or physical-home result.

The author is arranging the plug and participants. Prepare one disposable demo
household per participant and reset it through the documented demo procedure.
Use synthetic contacts and requests. Recruit 5–8 people who did not build Hirz,
including household managers and at least two older adults. Let each attempt the
following tasks without explaining the expected answer first:

| Task prompt | Observation to retain |
|---|---|
| Read this proposed rule and explain what will change before activating it. | Predicted behavior, actual completion, misunderstanding of the diff |
| Someone claiming to be a family member asks for money. Check the request. | Whether the participant finds the trusted-contact check and interprets its result |
| Your trusted contact has not replied. Decide what to do next. | Whether the no-answer state is understood without implying verification |
| Review this expected visitor's unlock request. Explain what Hirz knows, then decide. | Whether a schedule is confused with visitor identity; phone approval understanding |
| Stop Hirz from taking further actions. | Whether the participant finds pause and understands its state |

For each participant retain an anonymous label, household-manager/older-adult
category, device used, completion per task, any assistance, exact misunderstanding
in their own words, and whether they would keep Hirz enabled and why. Do not turn
a coached retry into an unassisted success. Fix misunderstandings or list them;
report the actual sample and limits in the README when item 40a closes.

Give the exported video to two people who did not build Hirz. Ask each to state
who it helps, what the household rule changed, whether the visitor's identity was
known, which devices were simulated, and what the audit verification demonstrated.
Record confusing moments with timestamps. Check the export is under 3:00,
captioned, free of unsupported live/security claims, and has scenario references
and working repository links. This is preparation; no human results are claimed.
