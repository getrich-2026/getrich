/**
 * Tests for the top-level <ErrorBoundary>.
 *
 * Verifies the two contracts that matter:
 *   1. Happy path — children render normally.
 *   2. A render-time throw in the children is caught and a
 *      recoverable fallback is shown (NOT a blank page).
 *
 * The class-component instance method `setState` is the production
 * recovery path: clicking "Try again" resets the state and re-renders
 * the children. We exercise that path here too.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "./ErrorBoundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }): ReactElement {
  if (shouldThrow) {
    throw new Error("Boom");
  }
  return <div>Everything is fine</div>;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ErrorBoundary", () => {
  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary>
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Everything is fine")).toBeInTheDocument();
  });

  it("shows a recoverable fallback when a child throws during render", () => {
    // Suppress React's noisy "uncaught error" log for this test.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    render(
      <ErrorBoundary>
        <Bomb shouldThrow={true} />
      </ErrorBoundary>,
    );

    // The fallback UI must surface, not the original children.
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText("Boom")).toBeInTheDocument();

    // Recovery buttons are wired.
    expect(screen.getByRole("button", { name: /Try again/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Go home/i })).toBeInTheDocument();

    consoleError.mockRestore();
  });

  it("recovers the tree when the user clicks 'Try again' (state reset)", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const user = userEvent.setup();

    // Use a stateful wrapper so the second render does NOT throw.
    let nextShouldThrow = true;
    function Toggle(): ReactElement {
      return <Bomb shouldThrow={nextShouldThrow} />;
    }

    const { rerender } = render(
      <ErrorBoundary>
        <Toggle />
      </ErrorBoundary>,
    );
    // First render: throws.
    expect(screen.getByText(/Something went wrong/i)).toBeInTheDocument();

    // Flip the flag and click "Try again" — the boundary resets and
    // the children re-render with the new (non-throwing) prop.
    nextShouldThrow = false;
    rerender(
      <ErrorBoundary>
        <Toggle />
      </ErrorBoundary>,
    );
    // The boundary instance is preserved across rerender, so its
    // state is still { hasError: true }. The user must click the
    // button to reset.
    await user.click(screen.getByRole("button", { name: /Try again/i }));

    expect(screen.getByText("Everything is fine")).toBeInTheDocument();

    consoleError.mockRestore();
  });
});
