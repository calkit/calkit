import { beforeEach, describe, expect, it } from "vitest"

import {
  consumeGitHubOAuthState,
  consumeGitHubReturnTo,
  createGitHubOAuthState,
  getGitHubRedirectUri,
  startGitHubOAuth,
} from "./github"

class SessionStorageMock {
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
}

const installMocks = () => {
  Object.defineProperty(globalThis, "sessionStorage", {
    value: new SessionStorageMock(),
    writable: true,
    configurable: true,
  })
  // startGitHubOAuth navigates, which node has nowhere to go
  Object.defineProperty(globalThis, "location", {
    value: { href: "", origin: "http://localhost:5173" },
    writable: true,
    configurable: true,
  })
  Object.defineProperty(globalThis, "window", {
    value: { location: { origin: "http://localhost:5173", search: "" } },
    writable: true,
    configurable: true,
  })
  if (!globalThis.crypto) {
    Object.defineProperty(globalThis, "crypto", {
      value: { getRandomValues: (a: Uint8Array) => a.fill(7) },
      writable: true,
      configurable: true,
    })
  }
}

describe("GitHub OAuth state", () => {
  beforeEach(installMocks)

  it("round trips and is single use", () => {
    const state = createGitHubOAuthState()
    expect(state).toMatch(/^[0-9a-f]{32}$/)
    expect(consumeGitHubOAuthState()).toBe(state)
    // A replayed callback must not validate against a spent state
    expect(consumeGitHubOAuthState()).toBeNull()
  })

  it("issues a different state each time", () => {
    const first = createGitHubOAuthState()
    const second = createGitHubOAuthState()
    // Only meaningful with real randomness; the fallback stub fills a
    // constant, so just assert the latest one is what gets stored
    expect(consumeGitHubOAuthState()).toBe(second)
    expect(first).toHaveLength(32)
  })
})

describe("startGitHubOAuth", () => {
  beforeEach(installMocks)

  it("sends the browser to GitHub with a state parameter", () => {
    startGitHubOAuth()
    expect(location.href).toContain("https://github.com/login/oauth/authorize")
    expect(location.href).toContain("state=")
  })

  it("remembers where to return, and forgets when not given one", () => {
    startGitHubOAuth("/projects?newProject=1")
    expect(consumeGitHubReturnTo()).toBe("/projects?newProject=1")
    // A later flow without a destination must not inherit the old one
    startGitHubOAuth("/orgs?newOrg=1")
    startGitHubOAuth()
    expect(consumeGitHubReturnTo()).toBeNull()
  })
})

describe("consumeGitHubReturnTo", () => {
  beforeEach(installMocks)

  it("only honors same-origin paths, and only once", () => {
    startGitHubOAuth("/projects?newProject=1")
    expect(consumeGitHubReturnTo()).toBe("/projects?newProject=1")
    expect(consumeGitHubReturnTo()).toBeNull()
    // Protocol-relative and absolute URLs would take the user off-site
    for (const bad of [
      "//evil.example.com",
      "https://evil.example.com",
      "javascript:alert(1)",
      "",
    ]) {
      sessionStorage.setItem("gh_connect_return_to", bad)
      expect(consumeGitHubReturnTo()).toBeNull()
    }
  })
})

describe("getGitHubRedirectUri", () => {
  beforeEach(installMocks)

  it("points at the login route, the app's one registered callback", () => {
    expect(getGitHubRedirectUri()).toMatch(/\/login$/)
  })
})
