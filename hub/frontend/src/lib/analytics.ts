import type { AnyRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

let lastTrackedHref: string | null = null

function trackPageView(): void {
  const href = window.location.href
  if (href === lastTrackedHref) return
  lastTrackedHref = href
  mixpanel.track_pageview()
}

// Automated browsers (Selenium, Puppeteer, Playwright) set navigator.webdriver
// even when they spoof their user agent. We tag their events with a bot super
// property, which sticks to every event for the session, so this traffic can be
// filtered out in Mixpanel rather than dropped before it gets there.
export function initAnalytics(router: AnyRouter): void {
  if (navigator.webdriver) {
    mixpanel.register({ bot: true })
  }
  trackPageView()
  router.subscribe("onResolved", ({ hrefChanged }) => {
    if (hrefChanged) trackPageView()
  })
}
