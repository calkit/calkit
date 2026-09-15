// Functionality for working with Zotero OAuth

// Where the Zotero OAuth callback should send the user afterwards, so
// connecting from somewhere in a project comes back to that place rather
// than dropping them in account settings.
const ZOTERO_RETURN_KEY = "zoteroAuthReturnTo"

interface ZoteroReturn {
  /** Path (with search) to return to. */
  to: string
  /** Reopen the Zotero import modal on arrival. */
  reopenImport?: boolean
}

/**
 * Remember where to come back to before sending the user to Zotero.
 *
 * Defaults to wherever they are now, which is nearly always what's wanted:
 * the connect prompt appears at the point the account turned out to be
 * needed, and that's the point they were trying to get on with.
 */
export const stashZoteroReturn = (options?: {
  to?: string
  reopenImport?: boolean
}): void => {
  const value: ZoteroReturn = {
    to: options?.to ?? window.location.pathname + window.location.search,
    reopenImport: options?.reopenImport,
  }
  sessionStorage.setItem(ZOTERO_RETURN_KEY, JSON.stringify(value))
}

/** Read and clear the stashed return. Single-use. */
export const consumeZoteroReturn = (): ZoteroReturn | null => {
  const raw = sessionStorage.getItem(ZOTERO_RETURN_KEY)
  sessionStorage.removeItem(ZOTERO_RETURN_KEY)
  if (!raw) {
    return null
  }
  try {
    const parsed = JSON.parse(raw)
    return typeof parsed?.to === "string" ? parsed : null
  } catch {
    // Older sessions stored the bare path, so honour that rather than
    // sending someone to settings mid-flow after a deploy
    return { to: raw }
  }
}
