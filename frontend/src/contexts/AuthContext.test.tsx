/** Tests for the AuthContext provider + useAuth hook. */

import { act, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserInfo } from "../api/auth";
import {
  clearAccessToken,
  clearRefreshToken,
  clearStoredUser,
} from "../api/client";
import { AuthProvider, useAuth } from "./AuthContext";

// All the in-memory + sessionStorage + localStorage keys touched by the
// auth helpers. Clearing them in `beforeEach` is the only way to keep
// the module-level caches (`_cachedToken`, `_cachedUser`,
// `_cachedRefreshToken`) and the storage layers in sync between tests,
// because both layers are read on AuthProvider mount and the module
// cache is NOT reset by `sessionStorage.clear()` alone.
beforeEach(() => {
  clearAccessToken();
  clearRefreshToken();
  clearStoredUser();
  sessionStorage.clear();
  localStorage.clear();
  clearAccessToken();
  clearRefreshToken();
  clearStoredUser();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const STUB_USER: UserInfo = {
  id: "user-42",
  email: "alice@example.com",
  name: "Alice",
};

/** A small consumer component that renders the auth state as text. */
function AuthStateProbe() {
  const { user, isAuthenticated } = useAuth();
  return (
    <div>
      <span data-testid="user-id">{user?.id ?? "—"}</span>
      <span data-testid="is-auth">{String(isAuthenticated)}</span>
    </div>
  );
}

describe("AuthProvider — initial state", () => {
  it("starts with empty state when no session is stored", () => {
    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    );
    expect(screen.getByTestId("user-id")).toHaveTextContent("—");
    expect(screen.getByTestId("is-auth")).toHaveTextContent("false");
  });

  it("hydrates user and isAuthenticated from sessionStorage on mount", () => {
    // Seed sessionStorage with both an access token and a serialized
    // user, then mount a fresh AuthProvider.
    sessionStorage.setItem("getrich_access_token", "token-abc");
    sessionStorage.setItem("getrich_user", JSON.stringify(STUB_USER));

    render(
      <AuthProvider>
        <AuthStateProbe />
      </AuthProvider>,
    );

    expect(screen.getByTestId("user-id")).toHaveTextContent("user-42");
    expect(screen.getByTestId("is-auth")).toHaveTextContent("true");
  });
});

describe("AuthProvider — login/logout via useAuth", () => {
  it("login() sets state and writes to sessionStorage (access token + user)", () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();

    act(() => {
      result.current.login("new-access-token", STUB_USER);
    });

    expect(result.current.isAuthenticated).toBe(true);
    expect(result.current.user).toEqual(STUB_USER);

    // sessionStorage is the source of truth for page reload — confirm
    // the token + user are written so a refresh would re-hydrate.
    expect(sessionStorage.getItem("getrich_access_token")).toBe(
      "new-access-token",
    );
    expect(sessionStorage.getItem("getrich_user")).toBe(
      JSON.stringify(STUB_USER),
    );
  });

  it("login() with a refreshToken also writes to localStorage", () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    act(() => {
      result.current.login("access-1", STUB_USER, "refresh-1");
    });

    expect(localStorage.getItem("getrich_refresh_token")).toBe("refresh-1");
  });

  it("login() without a refreshToken does NOT touch localStorage", () => {
    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });

    act(() => {
      result.current.login("access-only", STUB_USER);
    });

    expect(localStorage.getItem("getrich_refresh_token")).toBeNull();
  });

  it("logout() clears module state, sessionStorage, and localStorage", () => {
    // Seed a full session first.
    sessionStorage.setItem("getrich_access_token", "token-abc");
    sessionStorage.setItem("getrich_user", JSON.stringify(STUB_USER));
    localStorage.setItem("getrich_refresh_token", "refresh-abc");

    const { result } = renderHook(() => useAuth(), {
      wrapper: AuthProvider,
    });
    expect(result.current.isAuthenticated).toBe(true);

    act(() => {
      result.current.logout();
    });

    expect(result.current.isAuthenticated).toBe(false);
    expect(result.current.user).toBeNull();
    expect(sessionStorage.getItem("getrich_access_token")).toBeNull();
    expect(sessionStorage.getItem("getrich_user")).toBeNull();
    expect(localStorage.getItem("getrich_refresh_token")).toBeNull();
  });
});

describe("useAuth", () => {
  it("throws a clear error when used outside an AuthProvider", () => {
    // renderHook with no wrapper invokes the hook at the top of the
    // tree with no Provider context — this exercises the guard.
    // Suppress React's expected console.error for the boundary-less
    // throw.
    const consoleErrorSpy = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    expect(() => renderHook(() => useAuth())).toThrow(
      /useAuth must be used within an AuthProvider/,
    );
    consoleErrorSpy.mockRestore();
  });
});
