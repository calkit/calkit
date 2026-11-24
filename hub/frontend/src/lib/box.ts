// Functionality for connecting Box with OAuth

import { UsersService } from "../client"

const BOX_OAUTH_STATE_KEY = "box_oauth_state"
const BOX_OAUTH_REDIRECT_KEY = "box_oauth_redirect_uri"
const BOX_OAUTH_RETURN_KEY = "box_oauth_return_to"

// Generate a single-use OAuth `state` for CSRF protection
const createBoxOAuthState = (): string => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  )
  sessionStorage.setItem(BOX_OAUTH_STATE_KEY, state)
  return state
}

// Send the browser to Box to connect, coming back to `returnTo`, a
// path in this app; the backend builds the URL, since it holds the client ID
export const startBoxAuth = async (returnTo: string) => {
  const response = await UsersService.postUserBoxAuthStart({
    boxAuthStartRequest: { state: createBoxOAuthState() },
  })
  // The code exchange must repeat the redirect URI the backend chose
  sessionStorage.setItem(BOX_OAUTH_REDIRECT_KEY, response.data.redirect_uri)
  sessionStorage.setItem(BOX_OAUTH_RETURN_KEY, returnTo)
  location.href = response.data.authorize_url
}

// Read and clear what was stored when the flow started. Single-use.
export const consumeBoxOAuthState = (): {
  state: string | null
  redirectUri: string | null
  returnTo: string | null
} => {
  const state = sessionStorage.getItem(BOX_OAUTH_STATE_KEY)
  const redirectUri = sessionStorage.getItem(BOX_OAUTH_REDIRECT_KEY)
  const stored = sessionStorage.getItem(BOX_OAUTH_RETURN_KEY)
  sessionStorage.removeItem(BOX_OAUTH_STATE_KEY)
  sessionStorage.removeItem(BOX_OAUTH_REDIRECT_KEY)
  sessionStorage.removeItem(BOX_OAUTH_RETURN_KEY)
  // Only paths in this app, so it can't send anyone elsewhere
  const returnTo =
    stored?.startsWith("/") && !stored.startsWith("//") ? stored : null
  return { state, redirectUri, returnTo }
}
