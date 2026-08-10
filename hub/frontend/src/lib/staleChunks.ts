// Recovery from chunks a deploy replaced under an open tab

/** How long to wait before a second reload, so a genuinely missing chunk
 *  produces one failed reload rather than a loop. Long enough to outlast the
 *  reload, short enough that a tab left open across a later deploy still
 *  recovers on its own. */
const COOLDOWN_MS = 30_000
const LAST_RELOAD_KEY = "calkit-stale-chunk-reload"

/** The pieces of `window` this needs, so tests can hand it a double. */
export interface ReloadTarget {
  addEventListener(
    type: "vite:preloadError",
    listener: (event: VitePreloadErrorEvent) => void,
  ): void
  sessionStorage: Pick<Storage, "getItem" | "setItem">
  location: { reload: () => void }
}

/**
 * Reload the page when a lazily imported chunk has gone missing.
 *
 * The bundle is split into content-hashed chunks fetched on demand, so the
 * files a tab was built against only exist while that build is deployed. A
 * tab that was open when a deploy landed gets "Failed to fetch dynamically
 * imported module" the first time it reaches for a chunk that changed, and
 * the app it wants is the one being served right now: reload and it's there.
 */
export function reloadOnStaleChunk(target: ReloadTarget): void {
  target.addEventListener("vite:preloadError", (event) => {
    const now = Date.now()
    try {
      const last = Number(target.sessionStorage.getItem(LAST_RELOAD_KEY)) || 0
      if (now - last < COOLDOWN_MS) {
        // Already reloaded and the chunk is still missing, so it isn't a
        // stale build; let the error surface instead of reloading again
        return
      }
      target.sessionStorage.setItem(LAST_RELOAD_KEY, String(now))
    } catch {
      // Without session storage there's no way to tell a first failure from
      // a reload loop, and a loop is worse than the error it papers over
      return
    }
    // Reloading is the handling, so Vite shouldn't also throw
    event.preventDefault()
    target.location.reload()
  })
}
