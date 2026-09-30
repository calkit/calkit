import type { AnyRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

export type AnalyticsConsent = "granted" | "denied"

const CONSENT_KEY = "analytics_consent"

// Self-hosted hubs without a Mixpanel token send nothing, so there is nothing
// to ask visitors about.
export const analyticsEnabled = Boolean(import.meta.env.VITE_MIXPANEL_TOKEN)

export const privacyPolicyUrl = "https://docs.calkit.org/privacy/"

const PAGE_VIEW_EVENT = "$mp_web_page_view"

// Mixpanel attaches the full current URL and the referrer to every event by
// default. Our URLs carry secrets, e.g., password reset and invitation tokens,
// and the names of accounts and projects, so those properties are dropped and
// page views send only a route template with its parameter values left out.
export const sensitivePropertyBlacklist = [
  "$current_url",
  "$referrer",
  "$referring_domain",
  "$initial_referrer",
  "$initial_referring_domain",
]

// Anonymous page views are counted by the hub rather than sent to Mixpanel
// from the browser, so nothing is stored on the visitor's device and they can
// be collected without consent. The whole session's views go in one beacon
// where possible, since a beacon has nobody waiting on it.
const MAX_VIEWS_PER_BEACON = 20
const BEACON_INTERVAL_MS = 15_000

let router: AnyRouter | null = null

let lastTrackedHref: string | null = null

let interacted = false

type PageContext = {
  path: string
  owner_name?: string
  project_name?: string
}

let pendingViews: (PageContext & { ts: number })[] = []

let flushTimer: ReturnType<typeof setTimeout> | null = null

// Route parameters that are secrets, e.g., an invitation token. These keep
// their placeholder in the path so they never reach analytics; every other
// value, including the owner and project, is filled in so the path names the
// actual page rather than a template.
const SECRET_PARAM_NAMES = new Set([
  "token",
  "code",
  "user_code",
  "secret",
  "key",
  "access_token",
  "refresh_token",
])

function resolvePath(template: string, params: Record<string, string>): string {
  return template.replace(/\$(\w+)/g, (placeholder, name: string) =>
    SECRET_PARAM_NAMES.has(name) ? placeholder : params[name] ?? placeholder,
  )
}

// The page's resolved path, e.g., "/pete/proj/datasets" or "/join/$token",
// plus the owner and project for project pages. The owner and project name the
// page rather than the visitor, and are what makes project views useful to
// group.
function pageContext(): PageContext {
  if (!router) return { path: "/" }
  const { matchedRoutes, routeParams } = router.getMatchedRoutes(
    window.location.pathname,
    undefined,
  )
  return {
    path: resolvePath(
      matchedRoutes[matchedRoutes.length - 1]?.fullPath || "/",
      routeParams,
    ),
    owner_name: routeParams.accountName,
    project_name: routeParams.projectName,
  }
}

function pageViewProperties(context: PageContext) {
  return {
    current_url_path: context.path,
    current_domain: window.location.hostname,
    current_url_protocol: window.location.protocol,
    owner_name: context.owner_name,
    project_name: context.project_name,
  }
}

function sendBeacon(body: string): void {
  const url = `${import.meta.env.VITE_API_URL ?? ""}/pageviews`
  // A string body is sent as text/plain, which stays a simple cross-origin
  // request, so no preflight stands between the visitor leaving and this
  // arriving
  if (navigator.sendBeacon?.(url, body)) return
  fetch(url, {
    method: "POST",
    body,
    keepalive: true,
    headers: { "Content-Type": "text/plain" },
  }).catch(() => {
    // Analytics is best-effort; a visitor shouldn't see anything from it
  })
}

function flushPageViews(): void {
  if (!pendingViews.length) return
  const views = pendingViews
  pendingViews = []
  if (flushTimer !== null) {
    clearTimeout(flushTimer)
    flushTimer = null
  }
  const now = Date.now()
  sendBeacon(
    JSON.stringify({
      views: views.map((view) => ({
        path: view.path,
        owner_name: view.owner_name,
        project_name: view.project_name,
        dwell_ms: Math.max(0, now - view.ts),
      })),
      // Whether the browser was driven, and whether any real input happened;
      // the hub uses the pair to tell a person from a bot driving a browser
      signals: { webdriver: Boolean(navigator.webdriver), interacted },
    }),
  )
}

function queuePageView(context: PageContext): void {
  pendingViews.push({ ...context, ts: Date.now() })
  if (pendingViews.length >= MAX_VIEWS_PER_BEACON) {
    flushPageViews()
    return
  }
  if (flushTimer === null) {
    flushTimer = setTimeout(flushPageViews, BEACON_INTERVAL_MS)
  }
}

function trackPageView(): void {
  if (!analyticsEnabled) return
  const href = window.location.href
  if (href === lastTrackedHref) return
  lastTrackedHref = href
  const context = pageContext()
  // A visitor who allowed analytics gets page views on their account; everyone
  // else gets anonymous ones the hub counts
  if (getAnalyticsConsent() === "granted") {
    mixpanel.track(PAGE_VIEW_EVENT, {
      ...pageViewProperties(context),
      webdriver: Boolean(navigator.webdriver),
      interacted,
    })
  } else {
    queuePageView(context)
  }
}

// Mixpanel is initialized opted out, and it records opt-outs the same way
// whether they came from that default or from the visitor, so whether the
// visitor has actually answered is kept under a key of our own.
export function getAnalyticsConsent(): AnalyticsConsent | null {
  const value = localStorage.getItem(CONSENT_KEY)
  return value === "granted" || value === "denied" ? value : null
}

// Sent with signup and login requests; unanswered is left out, not sent as no
export function getAnalyticsConsentToSave(): boolean | undefined {
  const consent = getAnalyticsConsent()
  return consent === null ? undefined : consent === "granted"
}

const consentListeners = new Set<() => void>()

// For useSyncExternalStore, so the banner, the settings tab, and the account
// sync all see an answer given in any one of them
export function subscribeAnalyticsConsent(listener: () => void): () => void {
  consentListeners.add(listener)
  return () => consentListeners.delete(listener)
}

// Once signed in, the account's saved answer wins the first time it's seen,
// so a choice follows the user between browsers. After that, answers given in
// this browser (including one given before signing in) are saved to the
// account, which is what server-side events check.
export function reconcileAnalyticsConsent(
  account: boolean | null | undefined,
  local: AnalyticsConsent | null,
  firstSeen: boolean,
): { apply: AnalyticsConsent } | { save: boolean } | null {
  if (firstSeen && account != null) {
    const fromAccount = account ? "granted" : "denied"
    return fromAccount === local ? null : { apply: fromAccount }
  }
  if (local === null) return null
  const granted = local === "granted"
  return account === granted ? null : { save: granted }
}

export function setAnalyticsConsent(consent: AnalyticsConsent): void {
  localStorage.setItem(CONSENT_KEY, consent)
  for (const listener of consentListeners) listener()
  if (consent === "granted") {
    mixpanel.opt_in_tracking()
    // The page the visitor accepted on was counted anonymously, so it is
    // tracked again now that it can be tied to their account
    lastTrackedHref = null
    trackPageView()
  } else {
    mixpanel.opt_out_tracking({ delete_user: false })
  }
}

// Automated browsers (Selenium, Puppeteer, Playwright) set navigator.webdriver
// even when they spoof their user agent, so it's one signal among several.
// The stronger one for a bot driving a real browser is that it never produces
// real input, which is what `interacted` records.
function watchForInteraction(): () => void {
  const markInteracted = () => {
    interacted = true
  }
  const events = ["pointerdown", "keydown", "touchstart", "scroll"]
  for (const event of events) {
    window.addEventListener(event, markInteracted, {
      passive: true,
      once: true,
    })
  }
  return () => {
    for (const event of events) {
      window.removeEventListener(event, markInteracted)
    }
  }
}

// Set when this has already run, so a hot reload can drop the previous
// listeners instead of counting every later view twice
const INIT_KEY = "__calkitAnalyticsCleanup"

export function initAnalytics(appRouter: AnyRouter): void {
  router = appRouter
  const previous = (window as unknown as Record<string, unknown>)[INIT_KEY]
  if (typeof previous === "function") previous()
  // Our key is the record of what the visitor chose, so bring Mixpanel's own
  // opt-in state back in line if its storage was cleared separately
  const granted = getAnalyticsConsent() === "granted"
  if (granted !== mixpanel.has_opted_in_tracking()) {
    if (granted) mixpanel.opt_in_tracking()
    else mixpanel.opt_out_tracking({ delete_user: false })
  }
  if (navigator.webdriver) {
    mixpanel.register({ bot: true })
  }
  const stopWatching = watchForInteraction()
  const onHidden = () => {
    if (document.visibilityState === "hidden") flushPageViews()
  }
  document.addEventListener("visibilitychange", onHidden)
  window.addEventListener("pagehide", flushPageViews)
  ;(window as unknown as Record<string, unknown>)[INIT_KEY] = () => {
    stopWatching()
    document.removeEventListener("visibilitychange", onHidden)
    window.removeEventListener("pagehide", flushPageViews)
  }
  trackPageView()
  appRouter.subscribe("onResolved", ({ hrefChanged }) => {
    if (hrefChanged) trackPageView()
  })
}
