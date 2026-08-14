import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

// Reset all global stubs (`vi.stubGlobal`, `vi.stubEnv`) at the end of every
// test so a test that flips `import.meta.env` or replaces `window.fetch` does
// not leak into the next test in the same file. Without this, ordering
// artifacts and shared `vi` instances can cause flaky failures that only show
// up when tests are run in a particular order.
afterEach(() => {
  vi.unstubAllGlobals();
});
