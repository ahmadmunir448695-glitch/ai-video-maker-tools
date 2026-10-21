/**
 * The access-token lifecycle, which is the part of the client most likely to
 * break in a way the user feels (being signed out at random).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, getAccessToken, onUnauthenticated, refreshAccessToken, setAccessToken } from "./api";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => body,
  };
}

describe("access token storage", () => {
  afterEach(() => setAccessToken(null));

  it("keeps the token in memory, not in localStorage", () => {
    setAccessToken("abc123");

    expect(getAccessToken()).toBe("abc123");
    // An XSS payload reading storage must find nothing useful.
    expect(Object.values({ ...globalThis.localStorage }).join("")).not.toContain("abc123");
  });

  it("clears the token when asked", () => {
    setAccessToken("abc123");
    setAccessToken(null);

    expect(getAccessToken()).toBeNull();
  });
});

describe("refreshAccessToken", () => {
  beforeEach(() => setAccessToken(null));
  afterEach(() => vi.unstubAllGlobals());

  it("stores the new token from the refresh response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ access: "fresh", user: { id: "1" } })));

    await refreshAccessToken();

    expect(getAccessToken()).toBe("fresh");
  });

  it("shares one in-flight request between concurrent callers", async () => {
    // Token rotation invalidates the cookie on first use, so a burst of 401s
    // must not fire a burst of refreshes.
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ access: "fresh", user: { id: "1" } }));
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([refreshAccessToken(), refreshAccessToken(), refreshAccessToken()]);

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("throws and clears the token when the cookie is rejected", async () => {
    setAccessToken("stale");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "expired" }, 401)));

    await expect(refreshAccessToken()).rejects.toThrow(ApiError);
    expect(getAccessToken()).toBeNull();
  });
});

describe("request retry on 401", () => {
  beforeEach(() => setAccessToken("expired-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("refreshes once and replays the request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401)) // original call
      .mockResolvedValueOnce(jsonResponse({ access: "fresh", user: { id: "1" } })) // refresh
      .mockResolvedValueOnce(jsonResponse({ results: [] })); // replay
    vi.stubGlobal("fetch", fetchMock);

    const body = await api.get("/videos/");

    expect(body).toEqual({ results: [] });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(getAccessToken()).toBe("fresh");
  });

  it("gives up and reports the session lost when the refresh also fails", async () => {
    const onLost = vi.fn();
    onUnauthenticated(onLost);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "expired" }, 401)));

    await expect(api.get("/videos/")).rejects.toThrow(ApiError);
    expect(onLost).toHaveBeenCalled();
    onUnauthenticated(null);
  });

  it("does not try to refresh on an auth endpoint, which would loop", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ detail: "bad credentials" }, 401));
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.post("/auth/login", {})).rejects.toThrow(ApiError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("ApiError", () => {
  it("exposes a server field error by path", () => {
    const error = new ApiError("invalid", {
      status: 400,
      fields: { spec: { trim: "The end point must come after the start point." } },
    });

    expect(error.fieldError("spec.trim")).toBe("The end point must come after the start point.");
    expect(error.fieldError("spec.speed")).toBeNull();
  });

  it("joins a list of messages for one field", () => {
    const error = new ApiError("invalid", { status: 400, fields: { password: ["Too short.", "Too common."] } });

    expect(error.fieldError("password")).toBe("Too short. Too common.");
  });
});
