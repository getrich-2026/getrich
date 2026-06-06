/** Tests for the <PublicRoute> route guard. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { UserInfo } from "../api/auth";
import { AuthContext } from "../contexts/AuthContext";
import PublicRoute from "./PublicRoute";

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
 * Render <PublicRoute> inside a stub AuthContext provider so we can
 * drive `isAuthenticated` / `isLoading` independently of the real
 * AuthProvider. The real provider hardcodes `isLoading: false`, so
 * the only way to exercise the loading branch is to inject a context
 * value directly — same workaround as ProtectedRoute.test.tsx.
 */
function renderPublicRoute({
  initialEntries = ["/login"],
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
            path="/"
            element={<div data-testid="home-page">Home</div>}
          />
          <Route
            path="/login"
            element={
              <PublicRoute>
                <div data-testid="login-content">login form</div>
              </PublicRoute>
            }
          />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("PublicRoute", () => {
  it("renders children when the user is NOT authenticated", () => {
    renderPublicRoute({ isAuthenticated: false });
    expect(screen.getByTestId("login-content")).toBeInTheDocument();
    expect(screen.getByText("login form")).toBeInTheDocument();
    // No redirect happened — the home page is not in the DOM.
    expect(screen.queryByTestId("home-page")).not.toBeInTheDocument();
  });

  it("redirects authenticated users to /", () => {
    renderPublicRoute({
      isAuthenticated: true,
      user: STUB_USER,
    });
    // The / route renders; the public children (login form) do not.
    expect(screen.getByTestId("home-page")).toBeInTheDocument();
    expect(screen.queryByTestId("login-content")).not.toBeInTheDocument();
  });

  it("renders null while auth is loading (neither children nor redirect)", () => {
    const { container } = renderPublicRoute({
      isAuthenticated: false,
      isLoading: true,
    });
    // The loading branch returns null — no public content, no
    // redirect to / (the <Navigate> hasn't fired yet).
    expect(screen.queryByTestId("login-content")).not.toBeInTheDocument();
    expect(screen.queryByTestId("home-page")).not.toBeInTheDocument();
    // The container should be empty of user content (the
    // <MemoryRouter> + <Routes> + <AuthContext.Provider> wrappers
    // are not user content).
    expect(container.querySelector("[data-testid]")).toBeNull();
  });
});
