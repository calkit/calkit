// Functionality for connecting Hugging Face with OAuth

import { UsersService } from "../client"

const HF_OAUTH_STATE_KEY = "huggingface_oauth_state"
const HF_OAUTH_REDIRECT_KEY = "huggingface_oauth_redirect_uri"
const HF_OAUTH_RETURN_KEY = "huggingface_oauth_return_to"

// Generate a single-use OAuth `state` for CSRF protection
const createHuggingFaceOAuthState = (): string => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  )
  sessionStorage.setItem(HF_OAUTH_STATE_KEY, state)
  return state
}

// Send the browser to Hugging Face to connect, coming back to `returnTo`, a
// path in this app, once connected. The backend holds the client ID, so it
// builds the authorization URL.
export const startHuggingFaceAuth = async (returnTo: string) => {
  const response = await UsersService.postUserHuggingfaceAuthStart({
    huggingFaceAuthStartRequest: { state: createHuggingFaceOAuthState() },
  })
  // The code exchange must repeat the redirect URI the backend chose
  sessionStorage.setItem(HF_OAUTH_REDIRECT_KEY, response.data.redirect_uri)
  sessionStorage.setItem(HF_OAUTH_RETURN_KEY, returnTo)
  location.href = response.data.authorize_url
}

// Read and clear what was stored when the flow started. Single-use.
export const consumeHuggingFaceOAuthState = (): {
  state: string | null
  redirectUri: string | null
  returnTo: string | null
} => {
  const state = sessionStorage.getItem(HF_OAUTH_STATE_KEY)
  const redirectUri = sessionStorage.getItem(HF_OAUTH_REDIRECT_KEY)
  const stored = sessionStorage.getItem(HF_OAUTH_RETURN_KEY)
  sessionStorage.removeItem(HF_OAUTH_STATE_KEY)
  sessionStorage.removeItem(HF_OAUTH_REDIRECT_KEY)
  sessionStorage.removeItem(HF_OAUTH_RETURN_KEY)
  // Only paths in this app, so it can't send anyone elsewhere
  const returnTo =
    stored?.startsWith("/") && !stored.startsWith("//") ? stored : null
  return { state, redirectUri, returnTo }
}
