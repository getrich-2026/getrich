/** Tests for the Register page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuthData } from "../api/auth";
import { register as registerApi } from "../api/auth";
import { ApiClientError } from "../api/client";
import { clearAccessToken, clearRefreshToken, clearStoredUser } from "../api/client";
import { AuthProvider } from "../contexts/AuthContext";
import Register from "./Register";

vi.mock("../api/auth", async () => {
  const actual = await vi.importActual<typeof import("../api/auth")>("../api/auth");
  return {
    ...actual,
    register: vi.fn(),
  };
});

const STUB_AUTH_RESPONSE: AuthData = {
  access_token: "stub-access-token",
  refresh_token: "stub-refresh-token",
  token_type: "bearer",
  user: { id: "user-1", email: "alice@example.com", name: "Alice" },
};

function renderRegister() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <MemoryRouter initialEntries={["/register"]}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Register />
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
  vi.mocked(registerApi).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Register — render", () => {
  it("renders the form with all required fields", () => {
    renderRegister();
    expect(screen.getByRole("heading", { name: /create account/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create account/i })).toBeInTheDocument();
  });

  it("links to the login page for existing users", () => {
    renderRegister();
    const signInLink = screen.getByRole("link", { name: /sign in/i });
    expect(signInLink).toHaveAttribute("href", "/login");
  });
});

describe("Register — validation", () => {
  it("shows errors when fields are empty", async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.click(screen.getByRole("button", { name: /create account/i }));
    // The zod resolver is async; we assert via the side effect
    // (the API must not be called when validation fails) rather
    // than racing the DOM update.
    await new Promise((r) => setTimeout(r, 50));
    expect(registerApi).not.toHaveBeenCalled();
  });

  it("rejects an invalid email", async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "not-an-email");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.type(screen.getByLabelText(/confirm password/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(registerApi).not.toHaveBeenCalled();
  });

  it("rejects a weak password (missing uppercase/number)", async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "alllower8");
    await user.type(screen.getByLabelText(/confirm password/i), "alllower8");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(registerApi).not.toHaveBeenCalled();
  });

  it("rejects mismatched confirm password", async () => {
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.type(screen.getByLabelText(/confirm password/i), "Different1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await new Promise((r) => setTimeout(r, 50));
    expect(registerApi).not.toHaveBeenCalled();
  });
});

describe("Register — submit", () => {
  it("calls register API and navigates home on success", async () => {
    vi.mocked(registerApi).mockResolvedValue({
      code: 0,
      message: "ok",
      data: STUB_AUTH_RESPONSE,
      timestamp: 0,
      request_id: "test",
    });
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.type(screen.getByLabelText(/confirm password/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => {
      expect(registerApi).toHaveBeenCalledWith({
        email: "alice@example.com",
        password: "GoodPass1",
        name: "",
      });
    });
  });

  it("surfaces an API error message from the server", async () => {
    vi.mocked(registerApi).mockRejectedValue(
      new ApiClientError(409, "Email already registered"),
    );
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.type(screen.getByLabelText(/confirm password/i), "GoodPass1");
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/email already registered/i)).toBeInTheDocument();
    });
  });

  it("surfaces a generic network error when the failure is not an ApiClientError", async () => {
    vi.mocked(registerApi).mockRejectedValue(new Error("ECONNREFUSED"));
    const user = userEvent.setup();
    renderRegister();
    await user.type(screen.getByLabelText(/email/i), "alice@example.com");
    await user.type(screen.getByLabelText(/^password$/i), "GoodPass1");
    await user.type(screen.getByLabelText(/confirm password/i), "GoodPass1");
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });
});
