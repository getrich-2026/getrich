import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, setAccessToken } from "./client";
import { downloadBacktestRunArtifact } from "./backtestRuns";
import { lastFetchCall, mockJsonResponse } from "../test/fetch";

function mockBlobResponse(body: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

describe("downloadBacktestRunArtifact", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
    vi.restoreAllMocks();
    // jsdom does not implement createObjectURL/revokeObjectURL by default.
    if (!("createObjectURL" in URL)) {
      Object.defineProperty(URL, "createObjectURL", {
        value: vi.fn(() => "blob:mock-url"),
        configurable: true,
      });
    } else {
      vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:mock-url");
    }
    if (!("revokeObjectURL" in URL)) {
      Object.defineProperty(URL, "revokeObjectURL", {
        value: vi.fn(),
        configurable: true,
      });
    } else {
      vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    }
  });

  it("fetches with bearer auth and triggers a save dialog for the blob", async () => {
    setAccessToken("test-token");
    const fetchMock = vi.fn().mockResolvedValue(mockBlobResponse("hello world"));
    vi.stubGlobal("fetch", fetchMock);

    const clickSpy = vi.fn();
    const removeSpy = vi.fn();
    const appendSpy = vi.spyOn(document.body, "appendChild");
    const createElementSpy = vi.spyOn(document, "createElement");
    createElementSpy.mockImplementation(((tag: string) => {
      const el = {
        tag,
        href: "",
        download: "",
        style: { display: "" },
        click: clickSpy,
        remove: removeSpy,
      } as unknown as HTMLElement;
      return el;
    }) as typeof document.createElement);
    appendSpy.mockImplementation((node) => node);

    await downloadBacktestRunArtifact("run-1", "artifact-1", "manifest.json");

    const [url, init] = lastFetchCall();
    expect(url).toBe("/v1/backtest-runs/run-1/artifacts/artifact-1/content");
    expect(init?.method).toBeUndefined(); // GET default
    expect((init?.headers as Record<string, string> | undefined)).toMatchObject({
      Authorization: "Bearer test-token",
      Accept: "application/octet-stream",
    });

    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

    createElementSpy.mockRestore();
    appendSpy.mockRestore();
  });

  it("url-encodes run and artifact ids", async () => {
    setAccessToken("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockBlobResponse("x")));

    const createElementSpy = vi
      .spyOn(document, "createElement")
      .mockImplementation(((tag: string) => {
        return {
          tag,
          href: "",
          download: "",
          style: { display: "" },
          click: () => undefined,
          remove: () => undefined,
        } as unknown as HTMLElement;
      }) as typeof document.createElement);
    vi.spyOn(document.body, "appendChild").mockImplementation((n) => n);

    await downloadBacktestRunArtifact("run/with/slash", "id with space", "x.json");

    const [url] = lastFetchCall();
    expect(url).toBe(
      "/v1/backtest-runs/run%2Fwith%2Fslash/artifacts/id%20with%20space/content",
    );

    createElementSpy.mockRestore();
  });

  it("raises ApiClientError(401) when the server rejects the request", async () => {
    setAccessToken("tok");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse(
          { code: 4010, message: "auth required: please log in" },
          401,
        ),
      ),
    );

    await expect(
      downloadBacktestRunArtifact("run-1", "artifact-1", "x.json"),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      status: 401,
    });
  });

  it("raises ApiClientError with parsed message on 400", async () => {
    setAccessToken("tok");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        mockJsonResponse(
          { code: 4000, message: "artifact uri is not a local file: scheme='https'" },
          400,
        ),
      ),
    );

    await expect(
      downloadBacktestRunArtifact("run-1", "artifact-1", "x.json"),
    ).rejects.toBeInstanceOf(ApiClientError);
  });

  it("falls back to statusText when the body is not parseable JSON", async () => {
    setAccessToken("tok");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("not-json", {
          status: 502,
          statusText: "Bad Gateway",
        }),
      ),
    );

    await expect(
      downloadBacktestRunArtifact("run-1", "artifact-1", "x.json"),
    ).rejects.toMatchObject({
      name: "ApiClientError",
      status: 502,
    });
  });
});
