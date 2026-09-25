import { describe, expect, it } from "vitest";
import { money, readResult } from "./schema";

describe("card trust boundary", () => {
  const result = { speakable: { headline: "The request is pending.", details: [], options: [] }, data: { status: "ok" } };
  it("requires structured output and refuses MCP errors", () => {
    expect(readResult({ structuredContent: result }).data.status).toBe("ok");
    for (const value of [{}, { structuredContent: result, isError: true }, { structuredContent: { ...result, data: { status: "unknown" } } }]) expect(() => readResult(value)).toThrow();
  });
  it("refuses unknown or malformed card presentations", () => {
    for (const presentation of [{ kind: "unknown" }, { kind: "plan", can_approve: true }, { kind: "approval", phone_required: false }]) expect(() => readResult({ structuredContent: { ...result, data: { ...result.data, presentation } } })).toThrow();
  });
  it("retains negative values and marks unavailable estimates", () => {
    expect(money(-1.25)).toBe("-$1.25");
    expect(money(null)).toBe("Unavailable");
  });
});
