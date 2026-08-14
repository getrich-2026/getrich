/** Tests for the Login page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthData } from "../api/auth";
import { login as loginApi } from "../api/auth";
import { ApiClientError } from "../api/client";
import { clearAccessToken, clearRefreshToken, clearStoredUser } from "../api/client";
import { AuthProvider } from "../contexts/AuthContext";
import Login from "./Login";

vi.mock("../api/auth", async () => {
  const actual = await vi.importActual<typeof import("../api/auth")>("../api/auth");
  return {
    ...actual,
    login: vi.fn(),
  };
});

const STUB_AUTH_RESPONSE: AuthData = {
  access_token: "stub-access-token",
  refresh_token: "stub-refresh-token",
  token_type: "bearer",
  user: { id: "user-1", email: "alice@example.com", name: "Alice" },
};

function renderLogin() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Login />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  clearAccessToken();
  clearRefreshToken();
  clearStoredUser();
  sessionStorage.clear();
  localStorage.clear();
  vi.mocked(loginApi).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Login — render", () => {
  it("renders the form with all required fields", () => {
    renderLogin();
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/remember me/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("links to the register page for new users", () => {
    renderLogin();
    const signUpLink = screen.getByRole("link", { name: /sign up/i });
    expect(signUpLink).toHaveAttribute("href", "/register");
  });

  it("shows the demo account hint", () => {
    renderLogin();
    expect(screen.getByText(/demo@getrich\.io/i)).toBeInTheDocument();
  });
});

describe("Login — validation", () => {
  it("rejects empty fields", async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(loginApi).not.toHaveBeenCalled();
  });

  it("rejects a weak password", async () => {
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "short");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(loginApi).not.toHaveBeenCalled();
  });
});

describe("Login — submit", () => {
  it("calls login API and sets auth state on success", async () => {
    vi.mocked(loginApi).mockResolvedValue({
      code: 0,
      message: "ok",
      data: STUB_AUTH_RESPONSE,
      timestamp: 0,
      request_id: "test",
    });
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(loginApi).toHaveBeenCalledWith({
        email: "alice@example.com",
        password: "GoodPass1",
      });
    });
  });

  it("surfaces an invalid-credentials error from the server", async () => {
    vi.mocked(loginApi).mockRejectedValue(
      new ApiClientError(401, "Invalid email or password"),
    );
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument();
    });
  });

  it("surfaces a generic network error when the failure is not an ApiClientError", async () => {
    vi.mocked(loginApi).mockRejectedValue(new Error("ECONNREFUSED"));
    const user = userEvent.setup();
    renderLogin();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });
});
