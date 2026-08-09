// Functionality for working with Google OAuth

const GOOGLE_OAUTH_STATE_KEY = "google_oauth_state"

// Generate a fresh, unguessable OAuth `state`, persisting it in sessionStorage
// so the /auth/google callback can confirm the response belongs to a flow this
// browser started (CSRF protection). Returns the value to send to Google.
export const createGoogleOAuthState = (): string => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  )
  sessionStorage.setItem(GOOGLE_OAUTH_STATE_KEY, state)
  return state
}

// Read and clear the state stored by createGoogleOAuthState. Single-use.
export const consumeGoogleOAuthState = (): string | null => {
  const state = sessionStorage.getItem(GOOGLE_OAUTH_STATE_KEY)
  sessionStorage.removeItem(GOOGLE_OAUTH_STATE_KEY)
  return state
}

// Google OAuth authorization endpoint
export const getGoogleAuthUrl = () => {
  return "https://accounts.google.com/o/oauth2/v2/auth"
}

export const getGoogleRedirectUri = () => {
  const apiUrl = String(import.meta.env.VITE_API_URL)
  if (apiUrl.includes("localhost")) {
    return "http://localhost:5173/auth/google"
  }
  if (apiUrl.includes("staging")) {
    return "https://staging.calkit.io/auth/google"
  }
  return "https://calkit.io/auth/google"
}
