export const appNameBase = "calkit"
export const apiUrl = String(import.meta.env.VITE_API_URL)

const getAppName = () => {
  if (apiUrl.includes("localhost")) {
    return appNameBase + "-dev"
  }
  if (apiUrl.includes("staging")) {
    return appNameBase + "-staging"
  }
  return appNameBase
}

export const appName = getAppName()
