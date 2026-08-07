// Functionality for working with GitHub OAuth

const GITHUB_OAUTH_STATE_KEY = "gh_oauth_state"

// Generate a fresh, unguessable OAuth `state`, persisting it in sessionStorage
// so the callback can confirm the response belongs to a flow this browser
// started (CSRF protection). Returns the value to send to GitHub.
export const createGitHubOAuthState = (): string => {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const state = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  )
  sessionStorage.setItem(GITHUB_OAUTH_STATE_KEY, state)
  return state
}

// Read and clear the state stored by createGitHubOAuthState. Single-use.
export const consumeGitHubOAuthState = (): string | null => {
  const state = sessionStorage.getItem(GITHUB_OAUTH_STATE_KEY)
  sessionStorage.removeItem(GITHUB_OAUTH_STATE_KEY)
  return state
}

// GitHub OAuth apps have one registered callback URL, so both signing in and
// connecting GitHub to an existing account come back through /login.
export const getGitHubRedirectUri = (): string => {
  const baseUrl =
    import.meta.env.VITE_API_URL?.replace("/api", "") || window.location.origin
  return `${baseUrl}/login`
}

const GITHUB_RETURN_TO_KEY = "gh_connect_return_to"

// Send the browser to GitHub to authorize, for either intent. Pass returnTo
// to come back to whatever the user was doing (the callback lands on /login,
// which would otherwise drop them at settings).
export const startGitHubOAuth = (returnTo?: string): void => {
  const clientId = import.meta.env.VITE_GH_CLIENT_ID
  const state = createGitHubOAuthState()
  if (returnTo) {
    sessionStorage.setItem(GITHUB_RETURN_TO_KEY, returnTo)
  } else {
    sessionStorage.removeItem(GITHUB_RETURN_TO_KEY)
  }
  location.href = `https://github.com/login/oauth/authorize?client_id=${clientId}&state=${state}`
}

// Read and clear where to return after connecting. Only same-origin paths are
// honored, so a stale or tampered value can't bounce the user off-site.
export const consumeGitHubReturnTo = (): string | null => {
  const value = sessionStorage.getItem(GITHUB_RETURN_TO_KEY)
  sessionStorage.removeItem(GITHUB_RETURN_TO_KEY)
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return null
  }
  return value
}
