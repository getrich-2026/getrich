import { apiFetch } from "./client";
import type { ApiResponse } from "./client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Channels {
  app_push: boolean;
  sms: boolean;
  email: boolean;
  wechat_service: boolean;
  websocket: boolean;
}

export interface QuietHours {
  enabled: boolean;
  start: string;
  end: string;
}

export interface GlobalSettingsFields {
  confidence_threshold: number;
  urgency_filter: string[];
  quiet_hours: QuietHours;
  trading_hours_only: boolean;
}

export interface StrategyOverride {
  strategy_id: string;
  push_enabled: boolean;
  confidence_threshold: number | null;
  notify_entry_only: boolean;
}

export interface UserSignalSettings {
  push_enabled: boolean;
  channels: Channels;
  global_settings: GlobalSettingsFields;
  strategy_overrides: StrategyOverride[];
}

export interface StrategySignalSettings {
  strategy_id: string;
  enabled: boolean;
  channels: Channels;
  urgency_filter: string[];
  confidence_threshold: number;
  notify_entry_only: boolean;
}

// PUT request bodies — all fields optional (PATCH semantics)

export interface UpdateGlobalSettingsBody {
  push_enabled?: boolean;
  channels?: Partial<Channels>;
  global_settings?: {
    confidence_threshold?: number;
    urgency_filter?: string[];
    quiet_hours?: Partial<QuietHours>;
    trading_hours_only?: boolean;
  };
}

export interface UpdateStrategySettingsBody {
  enabled?: boolean;
  confidence_threshold?: number;
  notify_entry_only?: boolean;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/** Get global signal notification settings + strategy overrides. */
export function getUserSignalSettings(): Promise<ApiResponse<UserSignalSettings>> {
  return apiFetch<ApiResponse<UserSignalSettings>>("/user/signal-settings");
}

/** Update global signal notification settings (PATCH-style, only send changed fields). */
export function updateUserSignalSettings(
  body: UpdateGlobalSettingsBody,
): Promise<ApiResponse<{ updated: boolean }>> {
  return apiFetch<ApiResponse<{ updated: boolean }>>("/user/signal-settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

/** Get per-strategy notification settings. */
export function getStrategySignalSettings(
  strategyCode: string,
): Promise<ApiResponse<StrategySignalSettings>> {
  return apiFetch<ApiResponse<StrategySignalSettings>>(
    `/strategies/${encodeURIComponent(strategyCode)}/signal-settings`,
  );
}

/** Update per-strategy notification settings (PATCH-style). */
export function updateStrategySignalSettings(
  strategyCode: string,
  body: UpdateStrategySettingsBody,
): Promise<ApiResponse<{ strategy_id: string; updated: boolean }>> {
  return apiFetch<ApiResponse<{ strategy_id: string; updated: boolean }>>(
    `/strategies/${encodeURIComponent(strategyCode)}/signal-settings`,
    { method: "PUT", body: JSON.stringify(body) },
  );
}
