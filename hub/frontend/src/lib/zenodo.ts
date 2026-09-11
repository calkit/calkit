// Functionality for working with Zenodo

export const zenodoAuthStateParam = "4fdkjhsdrf84hfdkjhx" // TODO: Should be random

export const getZenodoAuthUrl = () => {
  const apiUrl = String(import.meta.env.VITE_API_URL)
  if (apiUrl.includes("localhost") || apiUrl.includes("staging")) {
    return "https://sandbox.zenodo.org/oauth/authorize"
  }
  return "https://zenodo.org/oauth/authorize"
}

export const getZenodoRedirectUri = () => {
  const apiUrl = String(import.meta.env.VITE_API_URL)
  if (apiUrl.includes("localhost")) {
    return "http://localhost:5173/auth/zenodo"
  }
  if (apiUrl.includes("staging")) {
    return "https://staging.calkit.io/auth/zenodo"
  }
  return "https://calkit.io/auth/zenodo"
}
