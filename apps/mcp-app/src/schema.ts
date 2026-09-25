import { z } from "zod";

const text = z.string().min(1).max(2000);
const date = z.iso.datetime({ offset: true });
const number = z.number().finite();
const row = z.object({ action_id: text, label: text, at: date.nullable() });
const annualized = z.object({ usd: number, eligible_days: z.number().int().positive(), total_days: z.number().int().positive(), sha256: text, profile: text, household_variant: text, wear_per_internal_kwh: number, period: text, label: text }).nullable();
const base = { as_of: date, valid_until: date, source: z.enum(["live", "simulated"]) };
const presentation = z.discriminatedUnion("kind", [
  z.object({ ...base, kind: z.literal("plan"), rows: z.array(row).max(3), timeline: z.array(row), annualized, car_limit: number.min(0).max(80).nullable(), can_approve: z.boolean(), can_revise_car: z.boolean(), rate_label: text.nullable() }),
  z.object({ ...base, kind: z.literal("approval"), label: text, rule: text, risk_band: text, can_respond: z.boolean(), phone_required: z.boolean(), plan_id: text.nullable(), version: z.number().int().positive().nullable() }),
  z.object({ ...base, kind: z.literal("verification"), signals: z.array(text).max(3), status: z.enum(["assessed", "pending", "genuine", "not_genuine", "will_call", "no_answer"]), contact_name: text.nullable(), can_check: z.boolean() }),
  z.object({ ...base, kind: z.literal("doorbell"), context: z.array(text), snapshot: z.literal("twin").nullable(), lock_state: z.enum(["locked", "unlocked", "unknown"]), can_request: z.boolean(), room: text.nullable() }),
  z.object({ ...base, kind: z.literal("scorecard"), counts: z.object({ autonomous: z.number().int().nonnegative(), asked: z.number().int().nonnegative(), blocked: z.number().int().nonnegative(), verified: z.number().int().nonnegative() }), annualized, window_start: date, window_end: date }),
]);
export const resultSchema = z.object({
  speakable: z.object({ headline: text, details: z.array(text).max(3), options: z.array(text).max(5) }),
  data: z.object({
    status: z.enum(["ok", "clarification", "queued", "preparing", "failed", "unavailable", "denied", "recorded", "phone_required"]),
    presentation: presentation.nullish(),
    plan: z.object({ plan_id: text, version: z.number().int().positive(), status: text, horizon: z.object({ start: date, end: date }), summary: z.object({ estimated_savings_usd: number.nullable(), peak_kwh_avoided: number.nullable() }), comparison_validity: z.object({ valid: z.boolean() }), alternatives: z.array(z.object({ label: text, cost_delta_usd: number.nullable(), why_rejected: text, validity: z.object({ valid: z.boolean() }) })) }).nullish(),
    decision: z.object({ action_id: text, decision: z.enum(["execute", "ask", "deny", "verify"]), approval: z.object({ approval_id: text, expires_at: date }).nullish() }).nullish(),
    case: z.object({ case_id: text, verification: z.object({ status: text, expires_at: date }).nullish() }).nullish(),
    audit: z.array(z.object({ at: date, summary: text })).default([]),
    cursor: text.nullish(),
  }),
});
export type Result = z.infer<typeof resultSchema>;
export type Card = z.infer<typeof presentation>;
export function readResult(value: unknown): Result {
  const envelope = z.object({ isError: z.boolean().optional(), structuredContent: z.unknown() }).parse(value);
  if (envelope.isError) throw new Error("The request failed. Retry or link your account again.");
  const result = resultSchema.parse(envelope.structuredContent);
  const { presentation: card, plan, decision, case: caseData } = result.data;
  if (card?.kind === "plan" && !plan || card?.kind === "approval" && card.can_respond && !decision?.approval || card?.kind === "verification" && (!caseData || card.can_check && !card.contact_name)) throw new Error("Incomplete card data");
  if (card?.kind === "approval" && card.can_respond && decision?.decision !== "ask" || card?.kind === "verification" && card.can_check && card.status !== "assessed") throw new Error("Inconsistent card data");
  return result;
}
export const money = (value: number | null | undefined) => value == null ? "Unavailable" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
