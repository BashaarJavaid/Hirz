# ADR-022 — Trusted contacts and real check-ins

Date: 2026-10-07. Status: approved scope; implementation and acceptance pending.

Item 31 reuses Pipeline, companion passkeys, the worker, notification queue and
canonical verification cases. Item 34's access gate is recorded separately in the
[verification log](../verification-log.md#item-34--ring-access-gate--2026-10-07).
No model makes or alters a check-in decision.

An owner creates contacts and confirms trust changes with fresh operation-bound
passkeys. App invitations are single-use, expire after 24 hours, and are shared
through an independently known channel. An enrolled owner/adult accepts in their
own household; the initiating owner confirms before activation. Neither acceptance
nor a reply grants membership or a session in the requesting household. Email
verification uses an explicit confirmation of a 15-minute mailbox capability,
followed by owner confirmation of the intended contact out of band. Phone hashes
confirmed in the contact's authenticated app are labeled contact-confirmed, not
proof of possession. App withdrawal does not revoke independently verified email.
Revocation invalidates outstanding permissions, preserves evidence, and closes
pending checks with an explicit reason.

Private storage holds encrypted destinations, delivery tokens, channel versions,
proofs and receipts. A separate explicitly initialized Fernet key refuses malformed
existing values. Graph and audit contain no raw channels, tokens or safe words.
Links carry 32 random token bytes in a fragment; opening or scanning a GET changes
nothing. Only explicit POSTs consume capabilities. Tokens never enter server URLs,
referrers or analytics. Email links authorize exactly one enrollment or request.

Safe words use NFC, outer-whitespace trimming and case preservation, 8–128
characters, five guesses per contact per fifteen minutes. Python's
[scrypt](https://docs.python.org/3.12/library/hashlib.html#hashlib.scrypt) uses
N=131072, r=8, p=1, a random 16-byte salt and 32-byte output; parameters accompany
the hash, compared in constant time. Legacy plain hashes require owner reset.
A match supplies evidence only in the initiating member's private app view; it
never changes the risk band, closes a case as genuine, or grants an action.

Twelve MCP tools remain. Start/status callers remain supported; retry explicitly
selects app/email and creates a linked case for the same reported request.
Starts/retries require exact confirmation and a grant bound to household, member,
contact, channel version, case and request. Approval reuses the existing flow;
the two-minute app or fifteen-minute email deadline begins only when queued.
Policy/channel validity are checked before delivery. Network work runs outside
MCP calls and database transactions. Recipient passkeys bind the exact request and
answer; their own Pipeline records a scoped receipt for the initiating worker.
Mailbox proof is distinct from authenticated app proof. Server acceptance before
expiry counts even if worker processing is delayed. Receipt, timeout and revocation
serialize so one terminal answer wins; duplicates are idempotent, conflicts and
late/revoked replies are refused. Simulated controls only answer twin cases.

Delivery uses the approved temporary Gmail sender, bashaar.230102@gmail.com, and a
private app password. Standard-library [SMTP](https://docs.python.org/3.12/library/smtplib.html)
runs via asyncio.to_thread, smtp.gmail.com:587, certificate-verified mandatory
STARTTLS, ten-second socket timeout, at most three attempts before expiry, and one
operation/token across retries. Caps are three per contact per fifteen minutes and
twenty per household per day. [Gmail settings](https://support.google.com/mail/answer/7104828?hl=en).
No domain purchase or paid mail service. Generic push/email disclose the recorded
requester and exact quoted request only in the authenticated/restricted view.
Push failure leaves the app inbox usable. Permanent email failure means no_answer.

The companion Check-ins route shows received requests and private initiated cases,
method/provenance, safe-word evidence, and explicit retries. Answers remain No,
Yes, and I'll call; Yes confirms only the request, and I'll call records intent.
Fallback tells the member to call the contact saved in their own phone, without
showing a number or dialing link. Pending polling never overlaps, stops at terminal
status, and never initiates speech. No supplied number means no comparison claim.

Rejected: shared household logins, voice replies as proof, callbacks/SMS presented
as verified, safe-word authority, automatic email activation on GET, domain buying,
network calls in tools/transactions, hidden retries, model-generated paraphrases,
and simulated replies to real cases. Organization verification, assessment changes,
courier correlation and public AWS deployment retain their roadmap items.

Closure requires the no-answer scenario, authenticated HTTP/MCP security and
isolation checks, real iPhone Home Screen push and real email replies, independent
signed audit verification for both households, browser/conformance checks, both CI
latency gates and combined coverage ≥80%. Any missing gate leaves item 31 Partial.

## Acceptance deferrals — 2026-10-07

The author deferred iPhone push on the available older phone and real email
acceptance after SMTP reachability failed both in the agent and their own Terminal.
These are acceptance deferrals, not waived gates or approval for another sender,
port, service or TLS downgrade. Item 31 remains Partial until the original real
push and reply requirements are demonstrated; see the verification log.
