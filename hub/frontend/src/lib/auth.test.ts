import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("../client", () => ({
  LoginService: {
    refreshAccessToken: vi.fn(),
  },
}))

import { LoginService } from "../client"
import {
  clearTokens,
  getAccessToken,
  getValidAccessToken,
  isAuthenticationError,
  storeTokens,
} from "./auth"

class LocalStorageMock {
  private store = new Map<string, string>()

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}

const createJwt = (exp: number): string => {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url")

  return `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ exp })}.sig`
}

describe("getValidAccessToken", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      value: new LocalStorageMock(),
      writable: true,
      configurable: true,
    })

    if (!globalThis.atob) {
      Object.defineProperty(globalThis, "atob", {
        value: (input: string) => Buffer.from(input, "base64").toString("utf8"),
        writable: true,
        configurable: true,
      })
    }

    clearTokens()
    vi.clearAllMocks()
  })

  it("does not refresh while requesting /login/refresh", async () => {
    const expiredAccessToken = createJwt(Math.floor(Date.now() / 1000) - 3600)
    storeTokens(expiredAccessToken, "refresh-token")

    const refreshAccessTokenMock = vi.mocked(LoginService.refreshAccessToken)
    refreshAccessTokenMock.mockResolvedValue({
      access_token: "new-access",
      refresh_token: "new-refresh",
      token_type: "bearer",
    })

    const token = await getValidAccessToken("/login/refresh")

    expect(token).toBe(expiredAccessToken)
    expect(refreshAccessTokenMock).not.toHaveBeenCalled()
  })

  it("refreshes expired token for normal API requests", async () => {
    const expiredAccessToken = createJwt(Math.floor(Date.now() / 1000) - 3600)
    storeTokens(expiredAccessToken, "refresh-token")

    const refreshAccessTokenMock = vi.mocked(LoginService.refreshAccessToken)
    refreshAccessTokenMock.mockResolvedValue({
      access_token: "new-access",
      refresh_token: "new-refresh",
      token_type: "bearer",
    })

    const token = await getValidAccessToken("/projects")

    expect(token).toBe("new-access")
    expect(refreshAccessTokenMock).toHaveBeenCalledTimes(1)
    expect(getAccessToken()).toBe("new-access")
  })
})

describe("isAuthenticationError", () => {
  it("does NOT log out on a bare 401 (not how sessions fail here)", () => {
    expect(isAuthenticationError({ status: 401 })).toBe(false)
  })

  it("does NOT log out on a missing-third-party-token 401", () => {
    // e.g. a GitHub-less user viewing the profile page hits
    // /user/github-app-installations, which 401s with this detail. Logging out
    // on it caused spurious logouts.
    expect(
      isAuthenticationError({
        status: 401,
        body: { detail: "User needs to authenticate with GitHub" },
      }),
    ).toBe(false)
    expect(
      isAuthenticationError({
        status: 401,
        body: { detail: "User needs to authenticate with Google" },
      }),
    ).toBe(false)
  })

  it("treats a 403 with a token-auth detail as an authentication failure", () => {
    for (const detail of [
      "Could not validate credentials",
      "Invalid token",
      "Invalid token scope",
      "Token has been deactivated",
      "Token has expired",
      "Token invalid",
    ]) {
      expect(isAuthenticationError({ status: 403, body: { detail } })).toBe(
        true,
      )
    }
  })

  it("does NOT log out on a plain 403 permission denial", () => {
    // The key fix: GitHub-less users hit ordinary 403s (forbidden) that must
    // not end the session.
    expect(
      isAuthenticationError({ status: 403, body: { detail: "Forbidden" } }),
    ).toBe(false)
    expect(
      isAuthenticationError({
        status: 403,
        body: { detail: "User is not authenticated" },
      }),
    ).toBe(false)
    expect(isAuthenticationError({ status: 403 })).toBe(false)
  })

  it("reads detail from an axios-shaped error too", () => {
    expect(
      isAuthenticationError({
        response: { status: 403, data: { detail: "Token has expired" } },
      }),
    ).toBe(true)
    expect(
      isAuthenticationError({
        response: { status: 403, data: { detail: "Forbidden" } },
      }),
    ).toBe(false)
  })

  it("ignores non-auth statuses", () => {
    expect(isAuthenticationError({ status: 404 })).toBe(false)
    expect(isAuthenticationError({ status: 502 })).toBe(false)
  })
})
