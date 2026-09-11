// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("mixpanel-browser", () => ({
  default: { track_pageview: vi.fn(), register: vi.fn() },
}))

function setWebdriver(value: boolean): void {
  Object.defineProperty(navigator, "webdriver", {
    value,
    configurable: true,
  })
}

function makeRouter() {
  let handler: ((event: { hrefChanged: boolean }) => void) | undefined
  return {
    subscribe: (
      _event: string,
      fn: (event: { hrefChanged: boolean }) => void,
    ) => {
      handler = fn
      return () => {}
    },
    navigate: (href: string, hrefChanged = true) => {
      window.history.pushState({}, "", href)
      handler?.({ hrefChanged })
    },
  }
}

async function load() {
  vi.resetModules()
  const mixpanel = (await import("mixpanel-browser")).default
  const { initAnalytics } = await import("./analytics")
  // biome-ignore lint/suspicious/noExplicitAny: test router stub
  return { mixpanel, initAnalytics: initAnalytics as any }
}

describe("initAnalytics", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.pushState({}, "", "/")
    setWebdriver(false)
  })

  it("tracks the landing page view", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(1)
  })

  it("tracks navigations to new URLs", async () => {
    const { mixpanel, initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(2)
  })

  it("does not retrack a navigation to the same URL", async () => {
    const { mixpanel, initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    router.navigate("/projects")
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(2)
  })

  it("tags automated browsers with a bot super property but still tracks them", async () => {
    setWebdriver(true)
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.register).toHaveBeenCalledWith({ bot: true })
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(1)
  })

  it("does not tag normal browsers", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.register).not.toHaveBeenCalled()
  })
})
