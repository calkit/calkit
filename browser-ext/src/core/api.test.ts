import { beforeEach, describe, expect, test, vi } from "vitest";

import type { Credentials } from "./storage";

const store = new Map<string, Credentials>();

vi.mock("./storage", () => ({
  getCredentials: async (apiUrl: string) => store.get(apiUrl) ?? null,
  setCredentials: async (apiUrl: string, creds: Credentials | null) => {
    if (creds === null) {
      store.delete(apiUrl);
    } else {
      store.set(apiUrl, creds);
    }
  },
  getCurrentHub: async () => ({ apiUrl: API }),
}));

const { ApiError, NotSignedInError, refreshCredentials } = await import(
  "./api"
);

const API = "http://api.localhost";

function respond(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status })),
  );
}

describe("refreshCredentials", () => {
  beforeEach(() => {
    store.clear();
    store.set(API, { accessToken: "a", refreshToken: "r", expiresAt: 0 });
  });

  test("only signs out when the hub rejects the refresh token", async () => {
    // A proxy erroring while the hub restarts keeps the user signed in
    for (const status of [500, 502, 503, 404]) {
      respond(status, { detail: "Bad Gateway" });
      await expect(refreshCredentials(API)).rejects.toBeInstanceOf(ApiError);
      expect(store.get(API)?.refreshToken).toBe("r");
    }
    // A fresh pair replaces the old one
    respond(200, { access_token: "a2", refresh_token: "r2", expires_in: 60 });
    expect(await refreshCredentials(API)).toBe("a2");
    expect(store.get(API)?.refreshToken).toBe("r2");
    // A rejected token is dropped, so it isn't retried on every request
    respond(401, { detail: "Invalid refresh token" });
    await expect(refreshCredentials(API)).rejects.toBeInstanceOf(
      NotSignedInError,
    );
    expect(store.has(API)).toBe(false);
  });
});
