/** Tests for the SignalSettings page. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { UserSignalSettings } from "../api/signalSettings";
import type { ApiResponse } from "../api/client";

vi.mock("../api/signalSettings", async () => {
  const actual = await vi.importActual<typeof import("../api/signalSettings")>(
    "../api/signalSettings",
  );
  return {
    ...actual,
    getUserSignalSettings: vi.fn(),
    updateUserSignalSettings: vi.fn(),
    updateStrategySignalSettings: vi.fn(),
  };
});

import {
  getUserSignalSettings,
  updateUserSignalSettings,
  updateStrategySignalSettings,
} from "../api/signalSettings";
import SignalSettings from "./SignalSettings";

const getMock = vi.mocked(getUserSignalSettings);
const updateMock = vi.mocked(updateUserSignalSettings);
const updateStrategyMock = vi.mocked(updateStrategySignalSettings);

const FIXED_SETTINGS: UserSignalSettings = {
  push_enabled: true,
  channels: {
    app_push: true,
    sms: false,
    email: false,
    wechat_service: false,
    websocket: true,
  },
  global_settings: {
    confidence_threshold: 0.5,
    urgency_filter: ["normal", "high", "critical"],
    quiet_hours: { enabled: false, start: "22:00", end: "08:30" },
    trading_hours_only: false,
  },
  strategy_overrides: [
    {
      strategy_id: "s-1",
      push_enabled: true,
      confidence_threshold: 0.7,
      notify_entry_only: false,
    },
  ],
};

function wrapSettings(s: UserSignalSettings): ApiResponse<UserSignalSettings> {
  return {
    code: 0,
    message: "ok",
    data: s,
    timestamp: 0,
    request_id: "test",
  } as ApiResponse<UserSignalSettings>;
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <SignalSettings />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  updateMock.mockReset();
  updateStrategyMock.mockReset();
  getMock.mockResolvedValue(wrapSettings(FIXED_SETTINGS));
  updateMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: { updated: true },
    timestamp: 0,
    request_id: "test",
  });
  updateStrategyMock.mockResolvedValue({
    code: 0,
    message: "ok",
    data: { strategy_id: "s-1", updated: true },
    timestamp: 0,
    request_id: "test",
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SignalSettings — render", () => {
  it("renders the loading state while the query is pending", () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByText(/Loading settings…/i)).toBeInTheDocument();
  });

  it("renders channel labels and the urgency filter after data loads", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/App Push/)).toBeInTheDocument();
    });
    expect(screen.getByText(/WebSocket/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^low$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^normal$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^high$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^critical$/i })).toBeInTheDocument();
  });

  it("renders one row per strategy override", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("s-1")).toBeInTheDocument();
    });
  });

  it("shows the empty-state hint when there are no strategy overrides", async () => {
    getMock.mockResolvedValueOnce(
      wrapSettings({ ...FIXED_SETTINGS, strategy_overrides: [] }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/No strategy-level overrides/i)).toBeInTheDocument();
    });
  });

  it("shows an error message when the query rejects", async () => {
    getMock.mockRejectedValueOnce(new Error("Boom"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/boom/i)).toBeInTheDocument();
    });
  });
});

describe("SignalSettings — save", () => {
  it("calls updateUserSignalSettings after toggling push and clicking save", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/App Push/)).toBeInTheDocument();
    });
    // Toggle the master push switch off.
    const pushSwitch = screen.getByRole("checkbox", { name: /Enable Push/i });
    await user.click(pushSwitch);
    await user.click(screen.getByRole("button", { name: /Save Global Settings/i }));
    await waitFor(() => {
      expect(updateMock).toHaveBeenCalledTimes(1);
    });
    const body = updateMock.mock.calls[0][0] as { push_enabled: boolean };
    expect(body.push_enabled).toBe(false);
  });

  it("shows a success feedback after a successful save", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/App Push/)).toBeInTheDocument();
    });
    const pushSwitch = screen.getByRole("checkbox", { name: /Enable Push/i });
    await user.click(pushSwitch);
    await user.click(screen.getByRole("button", { name: /Save Global Settings/i }));
    await waitFor(() => {
      expect(screen.getByText(/Settings saved/i)).toBeInTheDocument();
    });
  });
});
