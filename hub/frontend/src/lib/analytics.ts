import type { AnyRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

export type AnalyticsConsent = "granted" | "denied"

const CONSENT_KEY = "analytics_consent"

// Self-hosted hubs without a Mixpanel token send nothing, so there is nothing
// to ask visitors about.
export const analyticsEnabled = Boolean(import.meta.env.VITE_MIXPANEL_TOKEN)

export const privacyPolicyUrl = "https://docs.calkit.org/privacy/"

let lastTrackedHref: string | null = null

function trackPageView(): void {
  const href = window.location.href
  if (href === lastTrackedHref) return
  lastTrackedHref = href
  mixpanel.track_pageview()
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
    // The page the visitor accepted on was dropped while opted out
    lastTrackedHref = null
    trackPageView()
  } else {
    mixpanel.opt_out_tracking({ delete_user: false })
  }
}

// Automated browsers (Selenium, Puppeteer, Playwright) set navigator.webdriver
// even when they spoof their user agent. We tag their events with a bot super
// property, which sticks to every event for the session, so this traffic can be
// filtered out in Mixpanel rather than dropped before it gets there.
export function initAnalytics(router: AnyRouter): void {
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
  trackPageView()
  router.subscribe("onResolved", ({ hrefChanged }) => {
    if (hrefChanged) trackPageView()
  })
}
