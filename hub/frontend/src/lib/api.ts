// Helpers for working with the generated API client

import type { AxiosResponse } from "axios"

/**
 * Extract the body from a response whose endpoint declares a nullable
 * response model. The generated client coerces null JSON bodies to an empty
 * object (its `data ?? {}` fallback), which breaks truthiness guards, so
 * restore the null those endpoints actually returned.
 */
export const dataOrNull = <T>(response: AxiosResponse<T>): T | null => {
  const data = response.data
  if (
    data &&
    typeof data === "object" &&
    !Array.isArray(data) &&
    Object.keys(data).length === 0
  ) {
    return null
  }
  return data ?? null
}
