import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Pure functions only: number parsing, formatting, date arithmetic and
    // the translation of a server error into a sentence. Anything that needs
    // a browser is covered by the Playwright suite in tests/e2e instead --
    // a jsdom double for the real thing would test the double.
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
