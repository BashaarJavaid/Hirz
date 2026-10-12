# ADR-023 — Organization number comparison

Date: 2026-10-11. Status: implemented and verified ([evidence](../verification-log.md#item-33--2026-10-11)).

Item 33 preserves the twelve-tool surface: `assess_request_risk` receives
`party="organization"`, an optional `claimed_party` name and `presented_number`.
Only approved display names and aliases resolve, using case folding and outer
whitespace trimming. No fuzzy matching, inferred utility, or lookalike names.

The packaged `hirz/protect/organizations.yaml` initially contains ComEd, alias
Commonwealth Edison, public number +18003347661, revision/review 2026-10-11, and
[ComEd's official contact guidance](https://poweringlives.comed.com/comed-customers-have-the-power-to-stop-energy-scams/).
That page was reviewed on 2026-10-11 and publishes 800-334-7661. The immutable
process cache validates the registry at app startup, rejecting malformed entries
and duplicate identities/names/aliases. Updates are reviewed and shipped manually;
no runtime network lookup, expiry, background updater or new dependency.

Owners save only a server-derived registry contact through the existing fresh
passkey ceremony. Its binding includes organization ID and registry revision;
arbitrary destinations and stale revisions are refused. The existing owner-app
create/confirm grants and Pipeline/audit transaction authorize every save,
re-save and removal. Compiled policy rules remain unchanged. Household serialization permits one active record per
organization. Unchanged re-saves preserve graph versions. Removal archives both
contact and channel, preserving historical evidence.

Contact JSON attributes add `party` (legacy default person) and optional
`organization_id`. Phone channels add `registry-confirmed` provenance and
`registry_revision`, retaining normalized hashes only. No migration/backfill.
A saved record contributes only at the current revision; a registry revision
change requires owner review and re-save. Archived records cannot contribute.
Person lookup, pairing, delivery, safe words and check-ins exclude organizations,
including direct backend requests. A person named ComEd remains a person.

The canonical VerificationCase adds optional `organization_comparison`: identity,
display name, source URL, review date, current/saved revision and independent
saved-contact/registry results. Evidence is omitted without a supplied number or
recognized name. No supplied number means null comparison and no number claim.
Unknown names mean insufficient information. Either usable source matching means
matches; usable records with no match mean does_not_match. A current saved record
alone sets subject.trusted: this describes a record, never caller identity.
Registry-only matches do not confer trust. Existing phone validation applies.

Speech identifies matching sources, explains that caller ID can be forged and
that matching does not establish identity or endorse payment, and fits warning
advice and the extractor notice within three details. Contacting the utility
independently and a separately named trusted-person check remain available at all
bands. No organization case becomes a genuine/not-genuine person check. Risk
weights, keywords and scam_pattern remain unchanged. Background enrichment retains
comparison evidence and refreshes warning advice; stored receipts and historical
cases replay without recomputation.

Household setup shows the published phone, clickable official source, review date,
saved status and owner save/re-save/remove controls. Check-ins and the existing
verification card display “Published ComEd contact” while retaining the simulated
assessment badge. Tools and speech never gain saved phone values. The tool schema
size guard moves from 120,000 to 122,000 bytes to accommodate the explicit evidence;
the twelve tools and established latency corpus are unchanged.

Rejected: trusting caller-provided contacts, public-registry matches as caller
identity, automatic trust refresh, live directory searches, custom organization
destinations, fuzzy names, model judgments, runtime fallback, a thirteenth tool,
new storage tables, and a separate acceptance app. Courier correlation, Ring,
item 31 email/push acceptance and risk scoring changes remain outside this item.

Acceptance uses recorded/scripted responses, existing companion/card smokes,
independent conformance, disposable database tests and both normal CI latency
gates. No paid Bedrock or real-phone gate; no development database migration.
Manually reviewed registry data may become stale; matching cannot authenticate a
caller. The combined impersonation threat row remains Planned.
