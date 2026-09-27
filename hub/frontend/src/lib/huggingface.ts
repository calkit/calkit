// Functionality for connecting Hugging Face with OAuth

const HF_OAUTH_STATE_KEY = "huggingface_oauth_state"
const HF_OAUTH_REDIRECT_KEY = "huggingface_oauth_redirect_uri"

// Generate a single-use OAuth `state` for CSRF protection, and remember the
// redirect URI the backend chose, since the code exchange must repeat it.
export const createHuggingFaceOAuthState = (): string => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  )
  sessionStorage.setItem(HF_OAUTH_STATE_KEY, state)
  return state
}

export const saveHuggingFaceRedirectUri = (redirectUri: string) => {
  sessionStorage.setItem(HF_OAUTH_REDIRECT_KEY, redirectUri)
}

// Read and clear what was stored when the flow started. Single-use.
export const consumeHuggingFaceOAuthState = (): {
  state: string | null
  redirectUri: string | null
} => {
  const state = sessionStorage.getItem(HF_OAUTH_STATE_KEY)
  const redirectUri = sessionStorage.getItem(HF_OAUTH_REDIRECT_KEY)
  sessionStorage.removeItem(HF_OAUTH_STATE_KEY)
  sessionStorage.removeItem(HF_OAUTH_REDIRECT_KEY)
  return { state, redirectUri }
}
