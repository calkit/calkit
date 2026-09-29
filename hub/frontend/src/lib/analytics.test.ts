// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

const { mixpanelMock, anonymousMock } = vi.hoisted(() => {
  const anonymousMock = {
    track_pageview: vi.fn(),
    register: vi.fn(),
  }
  const mixpanelMock = {
    track_pageview: vi.fn(),
    register: vi.fn(),
    opt_in_tracking: vi.fn(),
    opt_out_tracking: vi.fn(),
    has_opted_in_tracking: vi.fn(() => false),
    init: vi.fn(() => anonymousMock),
  }
  return { mixpanelMock, anonymousMock }
})

vi.mock("mixpanel-browser", () => ({ default: mixpanelMock }))

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
    anonymous: anonymousMock,
    ...analytics,
    initAnalytics: analytics.initAnalytics as any,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubEnv("VITE_MIXPANEL_TOKEN", "test-token")
  localStorage.clear()
  window.history.pushState({}, "", "/")
  setWebdriver(false)
})

describe("initAnalytics", () => {
  it("initializes the anonymous instance with no device storage or IP", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.init).toHaveBeenCalledWith(
      "test-token",
      { track_pageview: false, disable_persistence: true, ip: false },
      "anonymous",
    )
  })

  it("tracks the landing page view anonymously", async () => {
    const { mixpanel, anonymous, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(1)
    expect(mixpanel.track_pageview).not.toHaveBeenCalled()
  })

  it("marks anonymous events so they can be told apart", async () => {
    const { anonymous, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(anonymous.register).toHaveBeenCalledWith({ anonymous: true })
  })

  it("tracks navigations to new URLs", async () => {
    const { anonymous, initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(2)
  })

  it("does not retrack a navigation to the same URL", async () => {
    const { anonymous, initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    router.navigate("/projects")
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(2)
  })

  it("tags automated browsers as bots but still tracks them", async () => {
    setWebdriver(true)
    const { anonymous, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(anonymous.register).toHaveBeenCalledWith({ bot: true })
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(1)
  })

  it("does not tag normal browsers as bots", async () => {
    const { mixpanel, anonymous, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(anonymous.register).not.toHaveBeenCalledWith({ bot: true })
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

  it("is sent with signups and logins only once answered", async () => {
    const { getAnalyticsConsentToSave, setAnalyticsConsent } = await load()
    expect(getAnalyticsConsentToSave()).toBeUndefined()
    setAnalyticsConsent("denied")
    expect(getAnalyticsConsentToSave()).toBe(false)
    setAnalyticsConsent("granted")
    expect(getAnalyticsConsentToSave()).toBe(true)
  })

  it("ignores unrecognized stored values", async () => {
    localStorage.setItem("analytics_consent", "maybe")
    const { getAnalyticsConsent } = await load()
    expect(getAnalyticsConsent()).toBeNull()
  })

  it("opts in and tracks the page the visitor accepted on", async () => {
    const {
      mixpanel,
      anonymous,
      initAnalytics,
      setAnalyticsConsent,
      getAnalyticsConsent,
    } = await load()
    initAnalytics(makeRouter())
    setAnalyticsConsent("granted")
    expect(getAnalyticsConsent()).toBe("granted")
    expect(mixpanel.opt_in_tracking).toHaveBeenCalledTimes(1)
    // The anonymous view on load, then the accepted page on the account
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(1)
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(1)
  })

  it("routes page views to the identified instance once consent is granted", async () => {
    const { mixpanel, anonymous, initAnalytics, setAnalyticsConsent } =
      await load()
    const router = makeRouter()
    initAnalytics(router)
    setAnalyticsConsent("granted")
    router.navigate("/projects")
    expect(mixpanel.track_pageview).toHaveBeenCalledTimes(2)
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(1)
  })

  it("keeps tracking page views anonymously after a rejection", async () => {
    const { mixpanel, anonymous, initAnalytics, setAnalyticsConsent } =
      await load()
    const router = makeRouter()
    initAnalytics(router)
    setAnalyticsConsent("denied")
    router.navigate("/projects")
    expect(anonymous.track_pageview).toHaveBeenCalledTimes(2)
    expect(mixpanel.track_pageview).not.toHaveBeenCalled()
  })

  it("notifies subscribers when the answer changes", async () => {
    const { subscribeAnalyticsConsent, setAnalyticsConsent } = await load()
    const listener = vi.fn()
    const unsubscribe = subscribeAnalyticsConsent(listener)
    setAnalyticsConsent("denied")
    expect(listener).toHaveBeenCalledTimes(1)
    unsubscribe()
    setAnalyticsConsent("granted")
    expect(listener).toHaveBeenCalledTimes(1)
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

describe("reconcileAnalyticsConsent", () => {
  it("applies the account's answer when a user is first seen", async () => {
    const { reconcileAnalyticsConsent } = await load()
    expect(reconcileAnalyticsConsent(true, null, true)).toEqual({
      apply: "granted",
    })
    expect(reconcileAnalyticsConsent(false, "granted", true)).toEqual({
      apply: "denied",
    })
  })

  it("does nothing when the account and browser already agree", async () => {
    const { reconcileAnalyticsConsent } = await load()
    expect(reconcileAnalyticsConsent(true, "granted", true)).toBeNull()
    expect(reconcileAnalyticsConsent(false, "denied", false)).toBeNull()
  })

  it("saves an answer given before signing in to an account without one", async () => {
    const { reconcileAnalyticsConsent } = await load()
    expect(reconcileAnalyticsConsent(null, "denied", true)).toEqual({
      save: false,
    })
  })

  it("saves a changed answer to the account after the first look", async () => {
    const { reconcileAnalyticsConsent } = await load()
    expect(reconcileAnalyticsConsent(false, "granted", false)).toEqual({
      save: true,
    })
  })

  it("does nothing when neither has an answer", async () => {
    const { reconcileAnalyticsConsent } = await load()
    expect(reconcileAnalyticsConsent(null, null, true)).toBeNull()
    expect(reconcileAnalyticsConsent(undefined, null, false)).toBeNull()
  })
})
