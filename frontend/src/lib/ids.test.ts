import { afterEach, describe, expect, it, vi } from "vitest";
import { newIdempotencyKey } from "./ids";

const V4_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("newIdempotencyKey", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a v4 UUID", () => {
    expect(newIdempotencyKey()).toMatch(V4_UUID);
  });

  it("still returns a fresh v4 UUID outside a secure context, where randomUUID is missing", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: real.getRandomValues.bind(real) });
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first).toMatch(V4_UUID);
    expect(second).toMatch(V4_UUID);
    expect(first).not.toBe(second);
  });
});
