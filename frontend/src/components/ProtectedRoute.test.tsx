/** Tests for the <ProtectedRoute> route guard. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { type ReactNode } from "react";
import { describe, expect, it } from "vitest";

import type { UserInfo } from "../api/auth";
import { AuthContext } from "../contexts/AuthContext";
import ProtectedRoute from "./ProtectedRoute";

const STUB_USER: UserInfo = {
  id: "user-42",
  email: "alice@example.com",
  name: "Alice",
};

type AuthOverride = Partial<{
  user: UserInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: () => void;
  logout: () => void;
}>;

/**
 * Render <ProtectedRoute> inside a stub AuthContext provider so we can
 * drive `isAuthenticated` / `isLoading` independently of the real
 * AuthProvider. The real provider hardcodes `isLoading: false` (no
 * token-validation API call yet), so the only way to exercise the
 * loading branch is to inject a context value directly.
 */
function renderProtectedRoute({
  initialEntries = ["/protected"],
  isAuthenticated = false,
  isLoading = false,
  user = null,
}: {
  initialEntries?: string[];
  isAuthenticated?: boolean;
  isLoading?: boolean;
  user?: UserInfo | null;
} = {}) {
  const ctx: AuthOverride = {
    user,
    isAuthenticated,
    isLoading,
    login: () => undefined,
    logout: () => undefined,
  };
  return render(
    <AuthContext.Provider value={ctx as never}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route
            path="/login"
            element={<div data-testid="login-page">Login</div>}
          />
          <Route
            path="/protected"
            element={
              <ProtectedRoute>
                <div data-testid="protected-content">secret</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("ProtectedRoute", () => {
  it("redirects unauthenticated users to /login", () => {
    renderProtectedRoute({ isAuthenticated: false });
    // The /login route renders; the protected children do not.
    expect(screen.getByTestId("login-page")).toBeInTheDocument();
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
  });

  it("renders children when the user is authenticated", () => {
    renderProtectedRoute({
      isAuthenticated: true,
      user: STUB_USER,
    });
    expect(screen.getByTestId("protected-content")).toBeInTheDocument();
    expect(screen.getByText("secret")).toBeInTheDocument();
    // No redirect happened — the login page is not in the DOM.
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
  });

  it("renders null while auth is loading (neither redirect nor children)", () => {
    const { container } = renderProtectedRoute({
      isAuthenticated: false,
      isLoading: true,
    });
    // The loading branch returns null — no protected content, no
    // redirect to /login (the <Navigate> hasn't fired yet).
    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
    expect(screen.queryByTestId("login-page")).not.toBeInTheDocument();
    // The container should be empty (the <MemoryRouter> + <Routes> +
    // <AuthContext.Provider> wrappers are not user content).
    expect(container.querySelector("[data-testid]")).toBeNull();
  });
});

// Keep imports tree-shake-safe across builds.
void (null as unknown as ReactNode);
