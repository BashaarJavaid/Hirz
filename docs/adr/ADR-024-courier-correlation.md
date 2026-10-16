# ADR-024: Courier correlation

Date: 2026-10-11. Status: accepted; implementation verification tracked in item 33a.

A reported request and a later doorbell press can justify a warning, never visitor
identification. The user confirmed the following scope before implementation.

The shared worker `hirz/protect/courier.py` runs after persisted observations and
on subsequent worker ticks. It correlates every household case whose latest
persisted band is CRITICAL when `created_at <= press_at <= created_at + 60 minutes`.
All check-in statuses qualify, including genuine; enrichment can qualify a case
while the press remains fresh. Both the available doorbell observation and press
must be at most 60 seconds old and not in the future. No downtime backfill occurs.
Arrival windows are evaluated at press time, start inclusive and end exclusive.
Claimed names and visitor identity play no part.

A nullable canonical courier state records the observation, asset, press time and
source, initiating member, selected contact/channel, and independent member/contact
action IDs, outcomes and deadlines. Legacy documents need no backfill. Household
serialization makes correlation/publication once per case; a retry is a new case
with no inherited courier state. Courier bookkeeping updates only that JSON field;
extraction and replies retain the rest of the case under the same household lock.

The member and contact actions are separately evaluated as
`communication.notify_member` and `communication.contact_trusted_contact`, with
`operation=courier`, under the initiating member's scheduler identity. No requester
confirmation is invented. Each action binds the household, case, member, asset,
press and selected channel. Approval dispatch never starts a check-in for these
actions. The worker revalidates the grant, policy and current authority before
publication. Unsent work stops on denial, revocation or expiry, five minutes after
detection at the latest (or earlier approval expiry). Real app deadlines use wall
time, even for a twin press; fixture delivery uses scenario time.

A saved person contact requires an active verified app link, without a prior
check-in or reply. Explicit disposable verified twin channels remain simulated.
Real link history prevents falling back to fixtures. Organizations and cases
without an eligible contact retain an independently authorized member warning and
record that no contact notification was sent. There is no later rerouting.
Contact publication shares the three-per-contact/15-minute and twenty-per-household/
day delivery caps with check-ins and enrollment attempts; retries stop at expiry.

Publication and its EXECUTED audit evidence commit in one transaction. The private
case is the durable inbox record; no new table is needed. Contact projections show
only the saved member name, approved wording, event time and provenance, and remain
readable only while the bound app link is active. Generic push uses existing bounded
transport retries and `/checkins`; a queue or provider success never proves phone
reception. A failed push leaves the published inbox warning available.

Approved member text:

> An unexpected doorbell press followed your reported request. Don’t hand anything over. Hirz cannot identify the visitor.

Approved contact text:

> [Member] reported a suspicious request. An unexpected doorbell press followed at their home. Please check on them. Hirz cannot identify the visitor.

Non-real presses carry “Simulated doorbell event.” Real app transport does not make
the triggering event real. Cards poll through their 60-minute case window or until
a member warning arrives, using server/scenario time, with existing hidden-tab,
non-overlap and teardown behavior. Publication and polling never initiate speech;
a later member request can return warning speech within existing limits. The
original check-in result is retained. Contact warnings have no acknowledgment or
dismissal workflow; empty inboxes retain push/Refresh discovery.

Rejected alternatives: a new MCP tool or table; inference-based correlation;
recovery of stale presses; using reply status or claimed visitor identity as a
filter; sending to everyone in the household; suppressing the member warning when
contact permission fails; email or inferred recipients; treating a push queue as
reception; requiring physical/iPhone/Ring acceptance for this increment. No new
paid inference, dependency or Ring integration is introduced. Item 35 and existing
email, iPhone push and Ring limitations remain unchanged.
