# ADR-004 — Table-driven risk bands, no formula, no model

**Status:** Accepted (2026-09-15)

**Decision:** Risk is a static per-class profile (impact, reversibility, base band) plus a fixed list of dynamic factors that can only raise the band. No numeric formula such as Impact × Uncertainty × Irreversibility, no learned model, no LLM.

**Reasoning:**

- A household must be able to read why an action was asked about or refused. "Door unlock is HIGH; a guest is present, so it's CRITICAL" is a sentence. A product of three estimated numbers is not, and nobody can defend the numbers.
- Bands map directly onto the constitution's three modes and to floors the constitution can tighten but not loosen. That is the property that makes "safe autonomous action" a system guarantee.
- Deterministic scoring is testable exhaustively and cannot be steered by injected text.
- The original concept's formula was useful as a mental model; as code it would be false precision.

**Alternatives considered:**

- *Weighted numeric score with thresholds* (as in the author's gateway). Works there for a security operator audience; rejected here because the audience is a family and the classes are few enough to enumerate.
- *LLM-assessed risk.* Rejected: non-deterministic, injectable, unexplainable. The one place a model touches risk is Protect's signal *extraction*, which is schema-validated and then weighted by code.
- *Learned per-household risk.* Rejected for v1; the consent-gated memory path can later propose per-household tightening, never loosening.

**Consequences:** Adding an action class is a code change with a risk profile, a Cedar action, a tool mapping, and a test. Bands are compared in exactly one function.

## Item 7 catalog amendment — 2026-09-18 (author-approved)

The closed catalog now lives in [`hirz/risk/classes.yaml`](../../hirz/risk/classes.yaml).
It preserves the fourteen documented profiles and adds the seven approved classes:
`energy.optimize_cost`, `environment.comfort_profile`, `environment.shades`,
`security.arm_disarm`, `health.comfort_preferences`, `health.medical_decisions`, and
`communication.contact_trusted_contact`. The catalog is the single source for
static validation and compiler action names. Item 7 enforces HIGH/CRITICAL
no-auto validation; dynamic factors and runtime risk scoring remain item 8.

## Item 8 amendment — 2026-09-18 (author-approved)

The standalone scorer, its typed factual inputs, canonical risk result, and
factor semantics are specified in [architecture §5.3](../../ARCHITECTURE.md#53-risk-engine).
The author approved these choices during item 8 planning:

- Accept explicit typed facts; graph extraction and runtime enforcement remain
  item 9. Raw `ContextSnapshot` extraction and extending the constitution's
  loosely structured `PolicyFacts` were rejected for this item: neither is
  needed for the standalone scorer, and both would expand the current boundary.
- Accumulate distinct factors, retain evidence after saturation, and fail closed
  for missing applicable facts. Taking only the largest increment or treating
  unknown facts as merely stale would weaken the approved risk behavior.
- Store freshness policy in the existing catalog, retain the existing profiles,
  and reuse constitution guards and Decimal comparisons. A separate risk table
  or bounds implementation would introduce competing policy definitions.
- Return a floor constraint, not a pipeline outcome. Resolving DENY versus VERIFY,
  authenticating callers, selecting observations, and granting authority belong
  to the later pipeline; no new risk CLI is needed.
- Include verification in deterministic scam escalation, following the factor
  table rather than the contradictory old Protect prose. Model-assisted advice
  never supplies the decision flag. Structured extraction remains item 32.
- Preserve the canonical risk wire shape and represent scoring failures as a
  final diagnostic factor; a separate diagnostics field was unnecessary.

The scorer's tests prove its arithmetic, fail-closed behavior and floor contract,
not that a running pipeline enforces those floors. Runtime threat-model rows
remain Planned. The [development procedure](../development.md#standalone-risk-scoring-item-8)
provides a local API smoke run without any execution or persistence.

## Item 9 amendment — 2026-09-18

The catalog adds reserved LOW-risk pause/resume controls, with no observation or
spend requirement. Explicit NEVER/hard guards precede scoring; overrides that need
risk facts resolve afterward, and any resulting NEVER still wins over CRITICAL.
Only `finance.verify_request` maps CRITICAL to VERIFY, which creates no contact
operation. Automatic risk inference from names, incomplete occupancy, or ambiguous
temperature preferences was rejected; the pipeline's extraction contract is in
[architecture §3.4](../../ARCHITECTURE.md#34-internal-pipeline-contract-item-9).

## Missing HVAC baseline amendment — 2026-09-18 (author-approved)

**Decision:** A missing/null `baseline_target_f` is not applicable, not an
unknown required fact. HVAC scoring skips `deviation_from_baseline` without
adding a factor when no baseline exists. `action.params.target_f` remains
required and numeric; every other applicable required fact still fails closed
to CRITICAL when missing. Supplied baselines retain the >6 °F deviation factor.
The canonical factor set and demo seeds are unchanged.

**Reasoning:** A missing preference is missing information, not a hazard. The
previous CRITICAL behavior denied instead of asking and blocked any new member
without a stored preference from the thermostat, including Malik's demo pre-warm.

**Rejected alternatives:**

- Keep CRITICAL: it treats absence of a preference as a hazard and prevents
  thermostat use by members who have not saved a preference.
- Add a +1 `state_stale`-style factor: absence of a preference is neither stale
  device state nor evidence of increased risk.
- Seed preferences for everyone: it hides the contract problem and leaves newly
  added members subject to the same denial.

## Protect evidence amendment — 2026-10-11

Item 32's hypothetical `finance.verify_request` uses `PreviewEvidence` with
`source=twin`, scoped to the assessed household and time. Only keyword matches for
financial/access, reported unfamiliarity and explicit urgency set its trusted
scam flag. An unfamiliar financial request alone is CRITICAL **advice** under the
approved override; this does not change the risk table. Model signals union into
advice only and cannot revise the retained Decision, authorize contact or execute
anything. The rejected alternative—feeding enriched warnings into risk—would make
a deterministic authority decision depend on untrusted model output. Lifecycle,
privacy and budget details live in [ADR-015](./ADR-015-household-tools.md#protect-assessment-and-enrichment-amendment--2026-10-11).
