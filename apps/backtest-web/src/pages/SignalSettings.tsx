import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getUserSignalSettings,
  updateUserSignalSettings,
  updateStrategySignalSettings,
  type Channels,
  type GlobalSettingsFields,
  type StrategyOverride,
} from "../api/signalSettings";
import { ApiClientError } from "../api/client";

const URGENCY_LEVELS = ["low", "normal", "high", "critical"] as const;

const CHANNEL_LABELS: Record<keyof Channels, string> = {
  app_push: "App Push",
  sms: "SMS",
  email: "Email",
  wechat_service: "WeChat",
  websocket: "WebSocket",
};

// ---------------------------------------------------------------------------
// Helper: toggle urgency level in array
// ---------------------------------------------------------------------------

function toggleUrgency(arr: string[], level: string): string[] {
  return arr.includes(level) ? arr.filter((u) => u !== level) : [...arr, level];
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SignalSettings() {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["signal-settings"],
    queryFn: () => getUserSignalSettings(),
  });

  const settings = data?.data;

  // ---- Form state (mirrors server state, editable) ----
  const [pushEnabled, setPushEnabled] = useState(true);
  const [channels, setChannels] = useState<Channels>({
    app_push: true,
    sms: false,
    email: false,
    wechat_service: false,
    websocket: true,
  });
  const [globalSettings, setGlobalSettings] = useState<GlobalSettingsFields>({
    confidence_threshold: 0.5,
    urgency_filter: ["normal", "high", "critical"],
    quiet_hours: { enabled: false, start: "22:00", end: "08:30" },
    trading_hours_only: false,
  });
  const [dirty, setDirty] = useState(false);

  // Sync form state when server data loads
  const [synced, setSynced] = useState(false);
  if (!synced && settings) {
    setPushEnabled(settings.push_enabled);
    setChannels({ ...settings.channels });
    setGlobalSettings({
      confidence_threshold: settings.global_settings.confidence_threshold,
      urgency_filter: [...settings.global_settings.urgency_filter],
      quiet_hours: { ...settings.global_settings.quiet_hours },
      trading_hours_only: settings.global_settings.trading_hours_only,
    });
    setSynced(true);
  }

  // ---- Global settings save mutation ----
  const saveGlobalMut = useMutation({
    mutationFn: () =>
      updateUserSignalSettings({
        push_enabled: pushEnabled,
        channels,
        global_settings: {
          confidence_threshold: globalSettings.confidence_threshold,
          urgency_filter: globalSettings.urgency_filter,
          quiet_hours: globalSettings.quiet_hours,
          trading_hours_only: globalSettings.trading_hours_only,
        },
      }),
    onSuccess: () => {
      setFeedback({ type: "success", msg: "Settings saved." });
      setDirty(false);
      queryClient.invalidateQueries({ queryKey: ["signal-settings"] });
    },
    onError: (err: unknown) => {
      setFeedback({
        type: "error",
        msg: err instanceof ApiClientError ? err.detail : "Save failed",
      });
    },
  });

  // ---- Per-strategy toggle mutation ----
  const toggleStratMut = useMutation({
    mutationFn: ({
      code,
      body,
    }: {
      code: string;
      body: { enabled?: boolean; confidence_threshold?: number; notify_entry_only?: boolean };
    }) => updateStrategySignalSettings(code, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["signal-settings"] });
    },
  });

  const markDirty = () => {
    if (!dirty) setDirty(true);
  };

  // ---- Render ----

  if (isLoading) return <div className="loading">Loading settings…</div>;
  if (error || !settings) {
    return (
      <div className="error-box">
        {error instanceof Error ? error.message : "Failed to load settings"}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 720 }}>
      <h1 className="section-title">Signal Notification Settings</h1>

      {feedback && (
        <div
          style={{
            padding: "8px 12px",
            borderRadius: "var(--radius)",
            background: feedback.type === "success" ? "var(--success, #22c55e)" : "var(--danger)",
            color: "#fff",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {feedback.msg}
        </div>
      )}

      {/* ================================================================ */}
      {/* Global Settings                                                   */}
      {/* ================================================================ */}

      <div className="card" style={{ marginBottom: 20 }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>Global Settings</h2>

        {/* Push enabled */}
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 16,
            cursor: "pointer",
            fontSize: 14,
          }}
        >
          <input
            type="checkbox"
            checked={pushEnabled}
            onChange={(e) => {
              setPushEnabled(e.target.checked);
              markDirty();
            }}
          />
          <strong>Enable Push Notifications</strong>
        </label>

        {/* Channels */}
        <fieldset
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "12px 16px",
            marginBottom: 16,
          }}
        >
          <legend style={{ fontWeight: 600, fontSize: 13, padding: "0 6px" }}>Channels</legend>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            {(Object.keys(CHANNEL_LABELS) as (keyof Channels)[]).map((k) => (
              <label
                key={k}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                <input
                  type="checkbox"
                  checked={channels[k]}
                  onChange={(e) => {
                    setChannels((prev) => ({ ...prev, [k]: e.target.checked }));
                    markDirty();
                  }}
                />
                {CHANNEL_LABELS[k]}
              </label>
            ))}
          </div>
        </fieldset>

        {/* Urgency filter */}
        <div style={{ marginBottom: 16 }}>
          <span style={{ fontWeight: 600, fontSize: 13, marginRight: 10 }}>
            Urgency Filter:
          </span>
          <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            {URGENCY_LEVELS.map((level) => {
              const active = globalSettings.urgency_filter.includes(level);
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => {
                    setGlobalSettings((prev) => ({
                      ...prev,
                      urgency_filter: toggleUrgency(prev.urgency_filter, level),
                    }));
                    markDirty();
                  }}
                  style={{
                    padding: "4px 12px",
                    fontSize: 12,
                    fontWeight: 500,
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    background: active ? "var(--primary)" : "var(--card-bg)",
                    color: active ? "var(--primary-foreground)" : "var(--foreground)",
                    cursor: "pointer",
                  }}
                >
                  {level}
                </button>
              );
            })}
          </div>
        </div>

        {/* Confidence threshold */}
        <div style={{ marginBottom: 16 }}>
          <label
            style={{ fontWeight: 600, fontSize: 13, display: "block", marginBottom: 4 }}
          >
            Confidence Threshold: {(globalSettings.confidence_threshold * 100).toFixed(0)}%
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={globalSettings.confidence_threshold}
            onChange={(e) => {
              setGlobalSettings((prev) => ({
                ...prev,
                confidence_threshold: parseFloat(e.target.value),
              }));
              markDirty();
            }}
            style={{ width: "100%", maxWidth: 300 }}
          />
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              maxWidth: 300,
              fontSize: 11,
              color: "var(--muted-foreground)",
            }}
          >
            <span>0%</span>
            <span>100%</span>
          </div>
        </div>

        {/* Trading hours only */}
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 16,
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          <input
            type="checkbox"
            checked={globalSettings.trading_hours_only}
            onChange={(e) => {
              setGlobalSettings((prev) => ({
                ...prev,
                trading_hours_only: e.target.checked,
              }));
              markDirty();
            }}
          />
          Trading hours only
        </label>

        {/* Quiet hours */}
        <fieldset
          style={{
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            padding: "12px 16px",
            marginBottom: 16,
          }}
        >
          <legend style={{ fontWeight: 600, fontSize: 13, padding: "0 6px" }}>Quiet Hours</legend>
          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 10,
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            <input
              type="checkbox"
              checked={globalSettings.quiet_hours.enabled}
              onChange={(e) => {
                setGlobalSettings((prev) => ({
                  ...prev,
                  quiet_hours: { ...prev.quiet_hours, enabled: e.target.checked },
                }));
                markDirty();
              }}
            />
            Enabled
          </label>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <label style={{ fontSize: 13 }}>
              Start:{" "}
              <input
                type="time"
                value={globalSettings.quiet_hours.start}
                onChange={(e) => {
                  setGlobalSettings((prev) => ({
                    ...prev,
                    quiet_hours: { ...prev.quiet_hours, start: e.target.value },
                  }));
                  markDirty();
                }}
                style={{
                  padding: "4px 8px",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  fontSize: 13,
                  background: "var(--card-bg)",
                  color: "var(--foreground)",
                }}
              />
            </label>
            <label style={{ fontSize: 13 }}>
              End:{" "}
              <input
                type="time"
                value={globalSettings.quiet_hours.end}
                onChange={(e) => {
                  setGlobalSettings((prev) => ({
                    ...prev,
                    quiet_hours: { ...prev.quiet_hours, end: e.target.value },
                  }));
                  markDirty();
                }}
                style={{
                  padding: "4px 8px",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  fontSize: 13,
                  background: "var(--card-bg)",
                  color: "var(--foreground)",
                }}
              />
            </label>
          </div>
        </fieldset>

        {/* Save button */}
        <button
          onClick={() => {
            setFeedback(null);
            saveGlobalMut.mutate();
          }}
          disabled={!dirty || saveGlobalMut.isPending}
          style={{
            padding: "8px 20px",
            border: "none",
            borderRadius: "var(--radius)",
            background: dirty ? "var(--primary)" : "var(--muted)",
            color: dirty ? "var(--primary-foreground)" : "var(--muted-foreground)",
            fontSize: 14,
            fontWeight: 600,
            cursor: dirty && !saveGlobalMut.isPending ? "pointer" : "not-allowed",
          }}
        >
          {saveGlobalMut.isPending ? "Saving…" : "Save Global Settings"}
        </button>
      </div>

      {/* ================================================================ */}
      {/* Strategy Overrides                                                */}
      {/* ================================================================ */}

      <div className="card">
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>
          Per-Strategy Overrides
        </h2>

        {settings.strategy_overrides.length === 0 ? (
          <div className="text-muted" style={{ fontSize: 13 }}>
            No strategy-level overrides configured. Subscribe to strategies to manage per-strategy
            notification settings.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Enabled</th>
                <th>Conf. Threshold</th>
                <th>Entry Only</th>
              </tr>
            </thead>
            <tbody>
              {settings.strategy_overrides.map((s: StrategyOverride) => (
                <StrategyOverrideRow
                  key={s.strategy_id}
                  override={s}
                  onToggle={(body) => toggleStratMut.mutate({ code: s.strategy_id, body })}
                  pending={toggleStratMut.isPending}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strategy override row (local state for instant feedback)
// ---------------------------------------------------------------------------

function StrategyOverrideRow({
  override,
  onToggle,
  pending,
}: {
  override: StrategyOverride;
  onToggle: (body: {
    enabled?: boolean;
    confidence_threshold?: number;
    notify_entry_only?: boolean;
  }) => void;
  pending: boolean;
}) {
  const [enabled, setEnabled] = useState(override.push_enabled);
  const [entryOnly, setEntryOnly] = useState(override.notify_entry_only);
  const [threshold, setThreshold] = useState(override.confidence_threshold ?? 0.5);

  // Keep in sync if parent data changes
  const [synced, setSynced] = useState(false);
  if (!synced) {
    setEnabled(override.push_enabled);
    setEntryOnly(override.notify_entry_only);
    setThreshold(override.confidence_threshold ?? 0.5);
    setSynced(true);
  }

  const changed =
    enabled !== override.push_enabled ||
    entryOnly !== override.notify_entry_only ||
    threshold !== (override.confidence_threshold ?? 0.5);

  return (
    <tr>
      <td style={{ fontFamily: "monospace", fontSize: 12 }}>{override.strategy_id}</td>
      <td>
        <input
          type="checkbox"
          checked={enabled}
          disabled={pending}
          onChange={(e) => {
            setEnabled(e.target.checked);
            onToggle({ enabled: e.target.checked });
          }}
        />
      </td>
      <td>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={threshold}
            disabled={pending}
            onChange={(e) => setThreshold(parseFloat(e.target.value))}
            style={{ width: 80 }}
          />
          <span style={{ fontSize: 12 }}>{(threshold * 100).toFixed(0)}%</span>
          {changed && (
            <button
              type="button"
              disabled={pending}
              onClick={() => onToggle({ confidence_threshold: threshold })}
              style={{
                padding: "2px 8px",
                fontSize: 11,
                border: "1px solid var(--primary)",
                borderRadius: 4,
                background: "var(--primary)",
                color: "var(--primary-foreground)",
                cursor: "pointer",
              }}
            >
              Save
            </button>
          )}
        </div>
      </td>
      <td>
        <input
          type="checkbox"
          checked={entryOnly}
          disabled={pending}
          onChange={(e) => {
            setEntryOnly(e.target.checked);
            onToggle({ notify_entry_only: e.target.checked });
          }}
        />
      </td>
    </tr>
  );
}
