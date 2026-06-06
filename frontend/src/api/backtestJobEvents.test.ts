/**
 * Unit tests for the SSE client (`streamBacktestJobEvents`).
 *
 * We mock `_fetchWithAuth` indirectly by stubbing `fetch`. The client
 * iterates `res.body.getReader()`, so we build a `ReadableStream`
 * that yields the test's bytes. The decoder buffer logic must
 * correctly split frames that arrive in multiple `read()` calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { streamBacktestJobEvents } from "./backtestJobEvents";

function streamFromChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  let i = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(chunks[i]!);
        i += 1;
      } else {
        controller.close();
      }
    },
  });
}

function mockFetchWithStream(stream: ReadableStream<Uint8Array>, status = 200): Response {
  return new Response(stream, {
    status,
    headers: { "Content-Type": "text/event-stream" },
  });
}

describe("streamBacktestJobEvents", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("parses a single snapshot frame from one read()", async () => {
    const body = JSON.stringify({ job_id: "j-1", status: "running" });
    const bytes = new TextEncoder().encode(`event: snapshot\ndata: ${body}\n\n`);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchWithStream(streamFromChunks([bytes]))),
    );

    const events: unknown[] = [];
    const ctrl = streamBacktestJobEvents("j-1", {
      onEvent: (e) => events.push(e),
      onError: (e) => {
        throw e;
      },
    });

    // Wait for the async reader to drain the body.
    await new Promise((r) => setTimeout(r, 5));
    ctrl.abort();

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      type: "snapshot",
      data: { job_id: "j-1", status: "running" },
    });
  });

  it("parses two frames split across two read() calls", async () => {
    const data1 = JSON.stringify({ job_id: "j-1", status: "running" });
    const data2 = JSON.stringify({ job_id: "j-1", status: "completed" });
    const full = `event: snapshot\ndata: ${data1}\n\nevent: done\ndata: ${data2}\n\n`;
    const bytes = new TextEncoder().encode(full);
    // Split mid-event so the parser must buffer.
    const first = bytes.slice(0, 40);
    const second = bytes.slice(40);

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchWithStream(streamFromChunks([first, second]))),
    );

    const events: unknown[] = [];
    const ctrl = streamBacktestJobEvents("j-1", {
      onEvent: (e) => events.push(e),
      onError: (e) => {
        throw e;
      },
    });
    await new Promise((r) => setTimeout(r, 10));
    ctrl.abort();

    expect(events).toEqual([
      { type: "snapshot", data: { job_id: "j-1", status: "running" } },
      { type: "done", data: { job_id: "j-1", status: "completed" } },
    ]);
  });

  it("ignores :keepalive comment lines", async () => {
    const data = JSON.stringify({ job_id: "j-1" });
    const full = `:keepalive\n\nevent: snapshot\ndata: ${data}\n\n`;
    const bytes = new TextEncoder().encode(full);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchWithStream(streamFromChunks([bytes]))),
    );

    const events: unknown[] = [];
    const ctrl = streamBacktestJobEvents("j-1", {
      onEvent: (e) => events.push(e),
      onError: (e) => {
        throw e;
      },
    });
    await new Promise((r) => setTimeout(r, 5));
    ctrl.abort();

    // Only the snapshot is delivered, not the heartbeat.
    expect(events).toHaveLength(1);
  });

  it("aborting the controller does not call onError", async () => {
    // A stream that never ends: the controller's abort should cancel
    // the read loop without surfacing an onError.
    const infinite = new ReadableStream<Uint8Array>({
      start() {},
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(mockFetchWithStream(infinite)),
    );

    const errored: Error[] = [];
    const ctrl = streamBacktestJobEvents("j-1", {
      onEvent: () => {},
      onError: (e) => errored.push(e),
    });
    ctrl.abort();
    await new Promise((r) => setTimeout(r, 5));
    expect(errored).toHaveLength(0);
  });

  it("calls onError with 'session expired' on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("", {
          status: 401,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const errored: Error[] = [];
    streamBacktestJobEvents("j-1", {
      onEvent: () => {},
      onError: (e) => errored.push(e),
    });
    await new Promise((r) => setTimeout(r, 5));

    expect(errored).toHaveLength(1);
    expect(errored[0]?.message).toBe("session expired, please log in again");
  });

  it("calls onError with 'not found' on 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("", {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const errored: Error[] = [];
    streamBacktestJobEvents("j-1", {
      onEvent: () => {},
      onError: (e) => errored.push(e),
    });
    await new Promise((r) => setTimeout(r, 5));

    expect(errored[0]?.message).toBe("backtest job not found");
  });

  // ----- Round #1058: reconnect / Last-Event-ID -----------------------

  it("reconnects after a fetch network error and delivers the next snapshot", async () => {
    const body1 = JSON.stringify({ job_id: "j-1", status: "running" });
    const body2 = JSON.stringify({ job_id: "j-1", status: "running" });
    // The second stream includes a `done` event in a SEPARATE frame
    // (blank line between events) so the client stops reconnecting.
    const full = `event: snapshot\ndata: ${body1}\n\nevent: done\ndata: ${body2}\n\n`;
    const bytes = new TextEncoder().encode(full);
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network down"))
      .mockResolvedValueOnce(mockFetchWithStream(streamFromChunks([bytes])));

    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    const reconnects: Array<{ attempt: number; delay: number }> = [];
    const ctrl = streamBacktestJobEvents(
      "j-1",
      {
        onEvent: (e) => events.push(e),
        onError: () => {
          throw new Error("should not be called for a retryable network error");
        },
        onReconnect: (attempt, delay) => reconnects.push({ attempt, delay }),
      },
      { baseDelayMs: 10, maxDelayMs: 100, maxRetries: 3, jitter: 0 },
    );

    // Wait for first connect (rejected) + backoff (10ms) + second connect (ok).
    await new Promise((r) => setTimeout(r, 60));
    ctrl.abort();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({
      type: "snapshot",
      data: { job_id: "j-1", status: "running" },
    });
    expect(events[1]).toEqual({
      type: "done",
      data: { job_id: "j-1", status: "running" },
    });
    expect(reconnects).toEqual([{ attempt: 1, delay: 10 }]);
  });

  it("reconnects after a mid-stream reader error", async () => {
    // A stream that errors on the first read.
    const erroring = new ReadableStream<Uint8Array>({
      start() {},
      pull() {
        throw new Error("stream blew up");
      },
    });
    // Followed by a clean snapshot+done stream so the client
    // stops after the second fetch.
    const body1 = JSON.stringify({ job_id: "j-1", status: "running" });
    const body2 = JSON.stringify({ job_id: "j-1", status: "running" });
    const full = `event: snapshot\ndata: ${body1}\n\nevent: done\ndata: ${body2}\n\n`;
    const bytes = new TextEncoder().encode(full);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(mockFetchWithStream(erroring))
      .mockResolvedValueOnce(mockFetchWithStream(streamFromChunks([bytes])));

    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    const ctrl = streamBacktestJobEvents(
      "j-1",
      {
        onEvent: (e) => events.push(e),
        onError: () => {
          throw new Error("should not be called");
        },
      },
      { baseDelayMs: 10, maxDelayMs: 100, maxRetries: 3, jitter: 0 },
    );

    await new Promise((r) => setTimeout(r, 60));
    ctrl.abort();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(events).toHaveLength(2);
  });

  it("stops after maxRetries and surfaces a final onError", async () => {
    vi.useFakeTimers();
    try {
      const fetchMock = vi.fn().mockRejectedValue(new TypeError("down"));
      vi.stubGlobal("fetch", fetchMock);

      const errored: Error[] = [];
      streamBacktestJobEvents(
        "j-1",
        {
          onEvent: () => {
            throw new Error("should never fire");
          },
          onError: (e) => errored.push(e),
        },
        { baseDelayMs: 100, maxDelayMs: 1000, maxRetries: 2, jitter: 0 },
      );

      // Initial connect attempt.
      await vi.advanceTimersByTimeAsync(0);
      // Backoff #1: 100ms.
      await vi.advanceTimersByTimeAsync(100);
      // Backoff #2: 200ms.
      await vi.advanceTimersByTimeAsync(200);

      expect(errored).toHaveLength(1);
      expect(errored[0]?.message).toMatch(/max retries/i);
      // 1 initial + 2 reconnects = 3 fetch attempts.
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops reconnecting on a terminal done event", async () => {
    const data1 = JSON.stringify({ job_id: "j-1", status: "running" });
    const data2 = JSON.stringify({ job_id: "j-1", status: "completed" });
    // Two SEPARATE frames: snapshot then done.
    const full = `event: snapshot\ndata: ${data1}\n\nevent: done\ndata: ${data2}\n\n`;
    const bytes = new TextEncoder().encode(full);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(mockFetchWithStream(streamFromChunks([bytes])))
      .mockResolvedValueOnce(mockFetchWithStream(streamFromChunks([bytes]))); // would be the reconnect

    vi.stubGlobal("fetch", fetchMock);

    const events: unknown[] = [];
    const reconnects: number[] = [];
    const ctrl = streamBacktestJobEvents(
      "j-1",
      {
        onEvent: (e) => events.push(e),
        onError: () => {
          throw new Error("should not be called");
        },
        onReconnect: (attempt) => reconnects.push(attempt),
      },
      { baseDelayMs: 10, maxDelayMs: 100, maxRetries: 5, jitter: 0 },
    );

    await new Promise((r) => setTimeout(r, 30));
    ctrl.abort();

    // The `done` event marks the stream terminal — no reconnect.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(reconnects).toEqual([]);
    expect(events.map((e) => (e as { type: string }).type)).toEqual([
      "snapshot",
      "done",
    ]);
  });

  it("does not retry on 401 or 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response("", { status: 401, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response("", { status: 404, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const errored: string[] = [];
    const a = streamBacktestJobEvents("j-1", {
      onEvent: () => {},
      onError: (e) => errored.push(e.message),
    });
    const b = streamBacktestJobEvents("j-2", {
      onEvent: () => {},
      onError: (e) => errored.push(e.message),
    });

    await new Promise((r) => setTimeout(r, 5));
    a.abort();
    b.abort();

    // Each call attempted exactly once.
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(errored).toContain("session expired, please log in again");
    expect(errored).toContain("backtest job not found");
  });

  it("sends Last-Event-ID header on reconnect", async () => {
    const body1 = JSON.stringify({ job_id: "j-1", status: "running" });
    const body2 = JSON.stringify({ job_id: "j-1", status: "running" });
    const withId = new TextEncoder().encode(
      `event: snapshot\nid: 2026-06-05T10:00:01\ndata: ${body1}\n\n`,
    );
    // The first stream yields one snapshot, then errors on the next read.
    const errorAfterOne = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(withId);
      },
      pull() {
        // Throwing on the second pull simulates a network drop.
        throw new Error("network drop");
      },
    });
    // After the drop, the second fetch yields a snapshot + done so
    // the client stops after exactly 2 fetches.
    const full = `event: snapshot\ndata: ${body1}\n\nevent: done\ndata: ${body2}\n\n`;
    const clean = new TextEncoder().encode(full);

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(mockFetchWithStream(errorAfterOne))
      .mockResolvedValueOnce(mockFetchWithStream(streamFromChunks([clean])));

    vi.stubGlobal("fetch", fetchMock);

    const ctrl = streamBacktestJobEvents(
      "j-1",
      {
        onEvent: () => {},
        onError: () => {
          throw new Error("should not be called");
        },
      },
      { baseDelayMs: 10, maxDelayMs: 100, maxRetries: 2, jitter: 0 },
    );

    await new Promise((r) => setTimeout(r, 40));
    ctrl.abort();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    // The second call must carry the Last-Event-ID we just observed.
    const secondInit = fetchMock.mock.calls[1]?.[1] as RequestInit | undefined;
    const headers = secondInit?.headers as Record<string, string> | undefined;
    const lastEventId = headers?.["Last-Event-ID"] ?? headers?.["last-event-id"];
    expect(lastEventId).toBe("2026-06-05T10:00:01");
  });

  it("backoff doubles per attempt with jitter bounded", async () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const randomStub = vi.fn().mockReturnValue(0.5); // no jitter (1 + 0.2 * (2*0.5 - 1) = 1)
    try {
      const fetchMock = vi.fn().mockRejectedValue(new TypeError("down"));
      vi.stubGlobal("fetch", fetchMock);

      streamBacktestJobEvents(
        "j-1",
        {
          onEvent: () => {},
          onError: () => {},
        },
        { baseDelayMs: 100, maxDelayMs: 10000, maxRetries: 4, jitter: 0, randomFn: randomStub },
      );

      // Initial attempt.
      await vi.advanceTimersByTimeAsync(0);
      // Each backoff: 100, 200, 400, 800ms.
      await vi.advanceTimersByTimeAsync(100);
      await vi.advanceTimersByTimeAsync(200);
      await vi.advanceTimersByTimeAsync(400);
      await vi.advanceTimersByTimeAsync(800);

      // The 4 reconnect setTimeout calls should have delays 100/200/400/800.
      const reconnectDelays = setTimeoutSpy.mock.calls
        .map((c) => c[1] as number)
        .filter((d) => d === 100 || d === 200 || d === 400 || d === 800);
      expect(reconnectDelays).toEqual([100, 200, 400, 800]);
    } finally {
      setTimeoutSpy.mockRestore();
      vi.useRealTimers();
    }
  });
});
