import { describe, it, expect } from "vitest";
import { errorMessage } from "./client";

/**
 * What the user is shown when the server refuses a write.
 *
 * A refusal the backend raises itself carries a sentence in `detail` and
 * reads fine. A *validation* failure does not: FastAPI answers those with
 * `detail` as an array of error objects, and `new Error([...])` stringifies
 * to "[object Object]". Every page renders `e.message`, so that is what
 * appeared on screen -- for nine different refusals reachable from the
 * forms, on fields where nothing in the UI says what the limit is either.
 *
 * The bodies below are real ones, captured from the running services.
 */
describe("errorMessage", () => {
  it("passes a hand-written refusal through unchanged", () => {
    expect(errorMessage({ detail: "Portfolio not found" }, "fallback"))
      .toBe("Portfolio not found");
    expect(errorMessage({ detail: "Only an income can be marked as a refund" }, "fallback"))
      .toBe("Only an income can be marked as a refund");
  });

  it("turns a validation error into a sentence naming the field", () => {
    const body = {
      detail: [{
        type: "string_too_long",
        loc: ["body", "ticker"],
        msg: "String should have at most 20 characters",
        input: "A".repeat(25),
        ctx: { max_length: 20 },
      }],
    };
    expect(errorMessage(body, "fallback"))
      .toBe("ticker: String should have at most 20 characters");
  });

  it("handles the real bodies each reachable refusal produces", () => {
    const cases: Array<[string, unknown, string]> = [
      ["name too long",
       { detail: [{ loc: ["body", "name"], msg: "String should have at most 200 characters" }] },
       "name: String should have at most 200 characters"],
      ["bad currency",
       { detail: [{ loc: ["body", "base_currency"], msg: "Value error, must be a 3-letter currency code, e.g. EUR" }] },
       "base_currency: Value error, must be a 3-letter currency code, e.g. EUR"],
      ["explicit null",
       { detail: [{ loc: ["body", "name"], msg: "Value error, can't be set to null -- omit this field to leave it unchanged" }] },
       "name: Value error, can't be set to null -- omit this field to leave it unchanged"],
      ["future date",
       { detail: [{ loc: ["body", "entry_date"], msg: "Value error, entry_date can't be in the future" }] },
       "entry_date: Value error, entry_date can't be in the future"],
      ["non-finite amount",
       { detail: [{ loc: ["body", "amount"], msg: "Value error, must be a real number" }] },
       "amount: Value error, must be a real number"],
      ["bad query parameter",
       { detail: [{ loc: ["query", "limit"], msg: "Input should be a valid integer" }] },
       "limit: Input should be a valid integer"],
    ];
    for (const [label, body, expected] of cases) {
      expect(errorMessage(body, "fallback"), label).toBe(expected);
    }
  });

  it("joins several field errors", () => {
    const body = {
      detail: [
        { loc: ["body", "name"], msg: "Field required" },
        { loc: ["body", "amount"], msg: "must be positive" },
      ],
    };
    expect(errorMessage(body, "fallback")).toBe("name: Field required; amount: must be positive");
  });

  it("keeps an index inside a nested location", () => {
    const body = { detail: [{ loc: ["body", "items", 0, "name"], msg: "Field required" }] };
    expect(errorMessage(body, "fallback")).toBe("items.0.name: Field required");
  });

  it("never produces [object Object]", () => {
    const shapes: unknown[] = [
      { detail: [{ loc: ["body", "x"], msg: "bad" }] },
      { detail: [{ loc: ["body", "x"] }] },
      { detail: [{ msg: "no location" }] },
      { detail: [{}] },
      { detail: [] },
      { detail: 42 },
      { detail: "" },
      { detail: null },
      {},
      null,
      undefined,
      "a bare string",
      [],
    ];
    for (const body of shapes) {
      const message = errorMessage(body, "Unprocessable Entity");
      expect(message, JSON.stringify(body)).not.toContain("[object Object]");
      expect(typeof message).toBe("string");
      expect(message.length).toBeGreaterThan(0);
    }
  });

  it("falls back to the whole body when nothing usable is in it", () => {
    expect(errorMessage({ detail: [] }, "fallback")).toBe('{"detail":[]}');
    expect(errorMessage({ oops: true }, "fallback")).toBe('{"oops":true}');
  });

  it("uses an entry's field name when it has no message", () => {
    expect(errorMessage({ detail: [{ loc: ["body", "ticker"] }] }, "fallback")).toBe("ticker");
  });

  it("uses the message alone when there is no field", () => {
    expect(errorMessage({ detail: [{ msg: "Something went wrong" }] }, "fallback"))
      .toBe("Something went wrong");
  });
});
