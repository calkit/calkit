// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

const { mixpanelMock } = vi.hoisted(() => ({
  mixpanelMock: {
    track: vi.fn(),
    register: vi.fn(),
    opt_in_tracking: vi.fn(),
    opt_out_tracking: vi.fn(),
    has_opted_in_tracking: vi.fn(() => false),
    init: vi.fn(),
  },
}))

vi.mock("mixpanel-browser", () => ({ default: mixpanelMock }))

function setWebdriver(value: boolean): void {
  Object.defineProperty(navigator, "webdriver", {
    value,
    configurable: true,
  })
}

function makeRouter(
  templates: Record<string, string> = {},
  params: Record<string, string> = {},
) {
  let handler: ((event: { hrefChanged: boolean }) => void) | undefined
  let fullPath = "/"
  return {
    subscribe: (
      _event: string,
      fn: (event: { hrefChanged: boolean }) => void,
    ) => {
      handler = fn
      return () => {}
    },
    navigate: (href: string, hrefChanged = true, template?: string) => {
      window.history.pushState({}, "", href)
      fullPath =
        template ??
        templates[window.location.pathname] ??
        window.location.pathname
      handler?.({ hrefChanged })
    },
    getMatchedRoutes: () => ({
      matchedRoutes: [{ fullPath }],
      routeParams: params,
      foundRoute: undefined,
    }),
  }
}

async function load() {
  vi.resetModules()
  const analytics = await import("./analytics")
  return {
    mixpanel: mixpanelMock,
    ...analytics,
    initAnalytics: analytics.initAnalytics as any,
  }
}

function flush() {
  window.dispatchEvent(new Event("pagehide"))
}

function lastBeacon() {
  const call = sendBeacon.mock.calls.at(-1)
  return JSON.parse(call?.[1] as string)
}

const sendBeacon = vi.fn((_url: string, _body: string) => true)

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubEnv("VITE_MIXPANEL_TOKEN", "test-token")
  vi.stubEnv("VITE_API_URL", "http://api.test")
  Object.defineProperty(navigator, "sendBeacon", {
    value: sendBeacon,
    configurable: true,
    writable: true,
  })
  localStorage.clear()
  window.history.pushState({}, "", "/")
  setWebdriver(false)
})

describe("initAnalytics", () => {
  it("does not create a browser Mixpanel instance for anonymous views", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.init).not.toHaveBeenCalled()
  })

  it("buffers the landing page view without consent", async () => {
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    expect(mixpanel.track).not.toHaveBeenCalled()
    expect(sendBeacon).not.toHaveBeenCalled()
    flush()
    expect(sendBeacon).toHaveBeenCalledTimes(1)
    const payload = lastBeacon()
    expect(payload.views).toHaveLength(1)
    expect(payload.views[0].path).toBe("/")
    expect(payload.signals.webdriver).toBe(false)
    expect(payload.signals.interacted).toBe(false)
  })

  it("resolves the path but leaves a secret parameter as its placeholder", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter(
      { "/join/secret-token": "/join/$token" },
      { token: "secret-token" },
    )
    initAnalytics(router)
    router.navigate("/join/secret-token")
    flush()
    const payload = lastBeacon()
    expect(payload.views[1].path).toBe("/join/$token")
    expect(JSON.stringify(payload)).not.toContain("secret-token")
  })

  it("names the owner and project in a project page path", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter(
      { "/pete/proj": "/$accountName/$projectName" },
      { accountName: "pete", projectName: "proj" },
    )
    initAnalytics(router)
    router.navigate("/pete/proj")
    flush()
    const view = lastBeacon().views[1]
    expect(view.path).toBe("/pete/proj")
    expect(view.owner_name).toBe("pete")
    expect(view.project_name).toBe("proj")
  })

  it("drops the query string", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/reset-password?token=secret")
    flush()
    expect(lastBeacon().views[1].path).toBe("/reset-password")
    expect(JSON.stringify(lastBeacon())).not.toContain("secret")
  })

  it("batches navigations into one beacon", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    router.navigate("/datasets")
    flush()
    expect(sendBeacon).toHaveBeenCalledTimes(1)
    expect(lastBeacon().views).toHaveLength(3)
  })

  it("does not retrack a navigation to the same URL", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    router.navigate("/projects")
    router.navigate("/projects")
    flush()
    expect(lastBeacon().views).toHaveLength(2)
  })

  it("flushes once the batch fills", async () => {
    const { initAnalytics } = await load()
    const router = makeRouter()
    initAnalytics(router)
    for (let i = 0; i < 20; i++) router.navigate(`/page-${i}`)
    expect(sendBeacon).toHaveBeenCalled()
  })

  it("reports automated browsers as driven", async () => {
    setWebdriver(true)
    const { mixpanel, initAnalytics } = await load()
    initAnalytics(makeRouter())
    flush()
    expect(mixpanel.register).toHaveBeenCalledWith({ bot: true })
    expect(lastBeacon().signals.webdriver).toBe(true)
  })

  it("reports interaction, which is what tells a person from a bot", async () => {
    const { initAnalytics } = await load()
    initAnalytics(makeRouter())
    window.dispatchEvent(new Event("pointerdown"))
    flush()
    expect(lastBeacon().signals.interacted).toBe(true)
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

  it("tracks the page on the account once consent is granted", async () => {
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
    expect(mixpanel.track).toHaveBeenCalledTimes(1)
    expect(mixpanel.track.mock.calls[0][1].current_url_path).toBe("/")
  })

  it("routes later page views to the account after consent", async () => {
    const { mixpanel, initAnalytics, setAnalyticsConsent } = await load()
    const router = makeRouter()
    initAnalytics(router)
    setAnalyticsConsent("granted")
    router.navigate("/projects")
    expect(mixpanel.track).toHaveBeenCalledTimes(2)
  })

  it("keeps counting page views anonymously after a rejection", async () => {
    const { mixpanel, initAnalytics, setAnalyticsConsent } = await load()
    const router = makeRouter()
    initAnalytics(router)
    setAnalyticsConsent("denied")
    router.navigate("/projects")
    flush()
    expect(mixpanel.track).not.toHaveBeenCalled()
    expect(lastBeacon().views).toHaveLength(2)
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
