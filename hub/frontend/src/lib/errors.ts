// Error handling functionality

import type { AxiosError } from "axios"

/**
 * Whether a failure means a third-party account simply isn't connected.
 *
 * The API answers 401 with this when an action needs a provider the user
 * hasn't linked. It isn't a session problem and it isn't really an error
 * either: the fix is a connect button, not a message.
 */
export const isProviderNotConnected = (
  err: unknown,
  provider: "Zotero" | "GitHub" | "Google" | "Zenodo" | "Overleaf",
): boolean => {
  const detail = (err as AxiosError)?.response?.data as any
  return (
    typeof detail?.detail === "string" &&
    detail.detail === `User needs to authenticate with ${provider}`
  )
}

export const handleError = (err: AxiosError, showToast: any) => {
  const errDetail = (err.response?.data as any)?.detail
  let errorMessage = errDetail || "Something went wrong."
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    errorMessage = errDetail[0].msg
  }
  showToast("Error", errorMessage, "error")
}
