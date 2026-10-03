import { describe, expect, it } from "vitest";
import { errorText } from "./errors";

describe("errorText", () => {
  it("shows an Error's message", () => {
    expect(errorText(new Error("Portfolio not found"))).toBe("Portfolio not found");
  });

  it("shows a thrown value that isn't an Error as itself", () => {
    expect(errorText("offline")).toBe("offline");
  });

  it("falls back to the error itself when its message is empty", () => {
    expect(errorText(new Error(""))).toBe("Error");
  });
});
