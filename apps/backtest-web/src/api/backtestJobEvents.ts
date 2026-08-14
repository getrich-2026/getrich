/**
 * Server-Sent Events client for backtest lifecycle updates.
 *
 * Replaces the previous 5 s `refetchInterval` polling on the detail
 * pages with a 1 Hz push: each new progress / status write by the
 * runner is reflected in the UI within ~1 s.
 *
 * Why `fetch` + `ReadableStream` instead of `new EventSource(...)`:
 *   - We need to set the `Authorization` header. `EventSource` has no
 *     header API in the browser.
 *   - We want a single 401 / 404 response code to surface as a real
 *     error (EventSource fires a generic `error` event with no status).
 *   - The same `AbortController` pattern works for `useEffect`
 *     teardown without polyfills.
 *
 * The client is shared across three pages via thin wrappers:
 *   - ``streamBacktestJobEvents`` — /backtest-jobs/{id}/events
 *     (Round #986 — BacktestJobDetail)
 *   - ``streamBacktestSweepEvents`` — /backtest-sweeps/{id}/events
 *     (Round #1061 — dedicated sweep endpoint)
 *   - ``streamBacktestWalkForwardEvents`` —
 *     /backtest-walk-forwards/{id}/events (Round #1061)
 *
 * Reconnect (Round #1058)
 * ------------------------
 * On any error other than 401/404 (and other than a caller-initiated
 * abort), the client reconnects with exponential backoff + jitter.
 * 401/404 fall through to a single `onError` so the page can flip to
 * the 5 s polling fallback. The reconnect is best-effort — at most one
 * in-flight `update` event is lost between snapshots (same as the old
 * polling cadence).
 *
 * The server emits a `Last-Event-ID`-shaped token (the row's
 * `updated_at` ISO string) on every frame; we forward it as the
 * `Last-Event-ID` request header on each retry. The server currently
 * does not replay events from a log, but the header is plumbed
 * end-to-end so a future event-log feature is drop-in.
 */
import { _fetchWithAuth } from "./client";
import type { BacktestJobDetail } from "./backtests";

// The data shape is the union of the three endpoint payloads. We
// type as ``unknown`` at the core and let the typed wrappers narrow
// via a cast — the wire format is identical (just different row
// fields), and the core has no reason to know about the variants.
export type BacktestJobSseEvent =
  | { type: "snapshot"; data: BacktestJobDetail }
  | { type: "update"; data: BacktestJobDetail }
  | { type: "done"; data: BacktestJobDetail }
  | { type: "error"; data: { detail: string } };

export interface SseHandlers {
  onEvent: (event: BacktestJobSseEvent) => void;
  onError: (err: Error) => void;
  onOpen?: () => void;
  /**
   * Called before each reconnect attempt. Use this to show
   * a "Reconnecting..." UI affordance.
   */
  onReconnect?: (attempt: number, nextDelayMs: number) => void;
}

export interface SseOptions {
  /** Max reconnect attempts on retryable errors. Default 8. */
  maxRetries?: number;
  /** Initial backoff in ms. Default 1000. */
  baseDelayMs?: number;
  /** Max backoff in ms. Default 30000. */
  maxDelayMs?: number;
  /** Jitter as a fraction of base. Default 0.2 (±20%). */
  jitter?: number;
  /**
   * Test-only: clock source. Defaults to the global `setTimeout`.
   * Pass a fake to drive `vi.useFakeTimers()` deterministically.
   */
  setTimeoutFn?: typeof setTimeout;
  /**
   * Test-only: randomness source. Returns a number in [0, 1).
   * Defaults to `Math.random`. Pass a stub to make backoff
   * deterministic in tests.
   */
  randomFn?: () => number;
}

const DEFAULT_MAX_RETRIES = 8;
const DEFAULT_BASE_DELAY_MS = 1000;
const DEFAULT_MAX_DELAY_MS = 30000;
const DEFAULT_JITTER = 0.2;

/**
 * Error messages that should NOT trigger a reconnect.
 *
 * The job-specific and resource-specific 404 strings are matched by
 * prefix here — the core never knows which resource is being
 * streamed, so a cross-cutting 404 always terminates the stream.
 */
const NON_RETRYABLE_MESSAGES: ReadonlySet<string> = new Set([
  "session expired, please log in again",
  "backtest job not found",
  "backtest sweep not found",
  "walk-forward not found",
]);

type ConnectOutcome = "ok" | "retryable" | "terminal" | "aborted";

/**
 * Open an SSE stream for the given path. Returns an `AbortController`
 * the caller can use to cancel the stream (e.g. on unmount).
 *
 * The fetch + ReadableStream pattern:
 *   1. Open the GET with `Accept: text/event-stream` and the auth
 *      header (overriding the default `Accept: application/json` from
 *      `_fetchWithAuth`).
 *   2. Iterate `res.body.getReader()` chunks; decode UTF-8.
 *   3. Buffer the partial text; split on `\n\n` (SSE frame terminator).
 *   4. Within a frame, lines beginning with `event:` set the event name;
 *      lines beginning with `id:` set the last-event-id; lines
 *      beginning with `data:` append to the data buffer; lines
 *      beginning with `:` are comments (heartbeats) and are ignored.
 *   5. On `\n\n` boundary, parse the data buffer as JSON and invoke
 *      `onEvent`.
 *
 * The handler is typed against :class:`BacktestJobDetail` for
 * backwards compatibility; the underlying JSON is dispatched
 * opaquely, so callers streaming a different payload can cast at the
 * call site (the wire format is identical).
 */
function streamSseEvents(
  path: string,
  handlers: SseHandlers,
  options?: SseOptions,
): AbortController {
  const maxRetries = options?.maxRetries ?? DEFAULT_MAX_RETRIES;
  const baseDelayMs = options?.baseDelayMs ?? DEFAULT_BASE_DELAY_MS;
  const maxDelayMs = options?.maxDelayMs ?? DEFAULT_MAX_DELAY_MS;
  const jitter = options?.jitter ?? DEFAULT_JITTER;
  const setTimeoutFn = options?.setTimeoutFn ?? setTimeout;
  const randomFn = options?.randomFn ?? Math.random;

  const controller = new AbortController();
  let attempts = 0;
  let sawTerminal = false;
  let lastEventId: string | null = null;

  const fireError = (err: Error): void => {
    handlers.onError(err);
  };

  const isRetryable = (err: Error): boolean => {
    if (NON_RETRYABLE_MESSAGES.has(err.message)) return false;
    // AbortError is the caller's choice; never retry on abort.
    if (err.name === "AbortError") return false;
    return true;
  };

  const computeBackoff = (n: number): number => {
    const base = Math.min(maxDelayMs, baseDelayMs * 2 ** (n - 1));
    const jitterFactor = 1 + jitter * (2 * randomFn() - 1);
    return Math.max(0, base * jitterFactor);
  };

  const connectOnce = async (): Promise<ConnectOutcome> => {
    let res: Response;
    try {
      res = await _fetchWithAuth(path, {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          ...(lastEventId ? { "Last-Event-ID": lastEventId } : {}),
        },
        signal: controller.signal,
      });
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        return "aborted";
      }
      // Network / fetch error — retryable.
      return "retryable";
    }

    if (!res.ok || !res.body) {
      const detail =
        res.status === 401
          ? "session expired, please log in again"
          : res.status === 404
            ? "backtest job not found"
            : `stream failed (${res.status})`;
      const err = new Error(detail);
      if (isRetryable(err)) {
        return "retryable";
      }
      // Non-retryable (401/404): fire the error ONCE, no retry.
      fireError(err);
      return "terminal";
    }

    handlers.onOpen?.();

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let currentEvent: string | null = null;
    let currentId: string | null = null;
    let dataBuf = "";

    const flushFrame = (): void => {
      if (dataBuf === "") {
        currentEvent = null;
        currentId = null;
        return;
      }
      try {
        const parsed: unknown = JSON.parse(dataBuf);
        const type = currentEvent ?? "message";
        if (type === "snapshot" || type === "update" || type === "done") {
          if (type === "done") {
            sawTerminal = true;
          }
          handlers.onEvent({
            type,
            data: parsed as BacktestJobDetail,
          });
        } else if (type === "error") {
          handlers.onEvent({
            type: "error",
            data: parsed as { detail: string },
          });
        }
        // Unknown event types are silently dropped (forward-compat).
        if (currentId) {
          lastEventId = currentId;
        }
      } catch (err) {
        fireError(err as Error);
      }
      currentEvent = null;
      currentId = null;
      dataBuf = "";
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          flushFrame();
          return sawTerminal ? "ok" : "retryable";
        }
        buffer += decoder.decode(value, { stream: true });
        let idx = buffer.indexOf("\n\n");
        while (idx !== -1) {
          const frame = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const rawLine of frame.split("\n")) {
            if (rawLine.startsWith(":")) continue; // comment / heartbeat
            if (rawLine.startsWith("event:")) {
              currentEvent = rawLine.slice(6).trim();
            } else if (rawLine.startsWith("id:")) {
              currentId = rawLine.slice(3).trim();
            } else if (rawLine.startsWith("data:")) {
              dataBuf += rawLine.slice(5).trim();
            }
            // `retry:` is ignored for now.
          }
          flushFrame();
          idx = buffer.indexOf("\n\n");
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        return "aborted";
      }
      // Reader error — retryable.
      return "retryable";
    }
  };

  const scheduleReconnect = (): void => {
    if (controller.signal.aborted) return;
    if (sawTerminal) return;
    if (attempts >= maxRetries) {
      fireError(new Error("SSE max retries exceeded"));
      return;
    }
    attempts += 1;
    const delay = computeBackoff(attempts);
    handlers.onReconnect?.(attempts, delay);
    setTimeoutFn(() => {
      void runOnce();
    }, delay);
  };

  const runOnce = async (): Promise<void> => {
    const outcome = await connectOnce();
    if (controller.signal.aborted || outcome === "aborted") {
      return;
    }
    if (outcome === "ok" || outcome === "terminal") {
      // "ok" — stream completed cleanly via the `done` event.
      // "terminal" — connectOnce has already fired the single
      //   onError; no further work to do.
      return;
    }
    // outcome === "retryable"
    scheduleReconnect();
  };

  void runOnce();
  return controller;
}

/**
 * Open an SSE stream for one backtest job.
 *
 * Wrapper over :func:`streamSseEvents` for the original
 * /backtest-jobs/{id}/events endpoint. Kept for backwards
 * compatibility — new code should call the page-specific wrapper
 * when streaming a sweep or walk-forward study.
 */
export function streamBacktestJobEvents(
  jobId: string,
  handlers: SseHandlers,
  options?: SseOptions,
): AbortController {
  return streamSseEvents(
    `/backtest-jobs/${encodeURIComponent(jobId)}/events`,
    handlers,
    options,
  );
}

/**
 * Open an SSE stream for one parameter sweep.
 *
 * Companion to :func:`streamBacktestJobEvents` but keyed on the
 * sweep row instead of the parent job. Lets the result page open
 * the stream as soon as it has a ``sweepId`` — no need to wait for
 * the runner to claim the job and surface a ``job_id`` (which can
 * be ``None`` in the brief window between job create and runner
 * claim).
 */
export function streamBacktestSweepEvents(
  sweepId: string,
  handlers: SseHandlers,
  options?: SseOptions,
): AbortController {
  return streamSseEvents(
    `/backtest-sweeps/${encodeURIComponent(sweepId)}/events`,
    handlers,
    options,
  );
}

/**
 * Open an SSE stream for one walk-forward study.
 *
 * Companion to :func:`streamBacktestJobEvents` but keyed on the
 * walk-forward row instead of the parent job.
 */
export function streamBacktestWalkForwardEvents(
  walkForwardId: string,
  handlers: SseHandlers,
  options?: SseOptions,
): AbortController {
  return streamSseEvents(
    `/backtest-walk-forwards/${encodeURIComponent(walkForwardId)}/events`,
    handlers,
    options,
  );
}
