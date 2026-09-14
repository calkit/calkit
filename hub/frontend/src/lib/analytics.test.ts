// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

vi.mock("mixpanel-browser", () => ({
  default: {
    track_pageview: vi.fn(),
    register: vi.fn(),
    opt_in_tracking: vi.fn(),
    opt_out_tracking: vi.fn(),
    has_opted_in_tracking: vi.fn(() => false),
  },
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
  const analytics = await import("./analytics")
  return {
    mixpanel,
    ...analytics,
    initAnalytics: analytics.initAnalytics as any,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  window.history.pushState({}, "", "/")
  setWebdriver(false)
})

describe("initAnalytics", () => {
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

  it("opts back in when consent was granted but Mixpanel lost its record", async () => {
    localStorage.setItem("analytics_consent", "granted")
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.opt_in_tracking).toHaveBeenCalledTimes(1)
  })

  it("opts out when Mixpanel is opted in without recorded consent", async () => {
    const { mixpanel, initAnalytics } = await load()
    vi.mocked(mixpanel.has_opted_in_tracking).mockReturnValueOnce(true)
    initAnalytics(makeRouter())
    expect(mixpanel.opt_out_tracking).toHaveBeenCalledTimes(1)
  })

  it("leaves Mixpanel alone when it already matches the recorded consent", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.opt_in_tracking).not.toHaveBeenCalled()
    expect(mixpanel.opt_out_tracking).not.toHaveBeenCalled()
  })
})

describe("analytics consent", () => {
  it("is unanswered until the visitor chooses", async () => {
    const { getAnalyticsConsent } = await load()
    expect(getAnalyticsConsent()).toBeNull()
  })

  it("ignores unrecognized stored values", async () => {
    localStorage.setItem("analytics_consent", "maybe")
    const { getAnalyticsConsent } = await load()
    expect(getAnalyticsConsent()).toBeNull()
  })

  it("opts in and tracks the page the visitor accepted on", async () => {
    const {
      mixpanel,
      initAnalytics,
      setAnalyticsConsent,
      getAnalyticsConsent,
    } = await load()
    initAnalytics(makeRouter())
    setAnalyticsConsent("granted")
    expect(getAnalyticsConsent()).toBe("granted")
    expect(mixpanel.opt_in_tracking).toHaveBeenCalledTimes(1)
    // Once on load (dropped while opted out), then again after accepting
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(2)
  })

  it("opts out without deleting the Mixpanel profile", async () => {
    const { mixpanel, setAnalyticsConsent, getAnalyticsConsent } = await load()
    setAnalyticsConsent("denied")
    expect(getAnalyticsConsent()).toBe("denied")
    expect(mixpanel.opt_out_tracking).toHaveBeenCalledWith({
      delete_user: false,
    })
  })
})
