import type { AnyRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

export type AnalyticsConsent = "granted" | "denied"

const CONSENT_KEY = "analytics_consent"

// Self-hosted hubs without a Mixpanel token send nothing, so there is nothing
// to ask visitors about.
export const analyticsEnabled = Boolean(import.meta.env.VITE_MIXPANEL_TOKEN)

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

export function setAnalyticsConsent(consent: AnalyticsConsent): void {
  localStorage.setItem(CONSENT_KEY, consent)
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
