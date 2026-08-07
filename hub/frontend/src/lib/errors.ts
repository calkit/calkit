// Error handling functionality

import type { AxiosError } from "axios"

export const handleError = (err: AxiosError, showToast: any) => {
  const errDetail = (err.response?.data as any)?.detail
  let errorMessage = errDetail || "Something went wrong."
  if (Array.isArray(errDetail) && errDetail.length > 0) {
    errorMessage = errDetail[0].msg
  }
  showToast("Error", errorMessage, "error")
}
