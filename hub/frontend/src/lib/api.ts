// Helpers for working with the generated API client

import type { QueryClient } from "@tanstack/react-query"
import type { AxiosResponse } from "axios"

import { ProjectsService } from "../client"

/**
 * HTTP status carried by a thrown request error, or null if it has none.
 *
 * The client is configured with `throwOnError`, so failures arrive as thrown
 * errors rather than a status field, and different layers surface the code in
 * different places (axios nests it under `response`, some wrappers hoist it).
 * Checking one spot silently misses the others.
 */
export const httpStatus = (error: unknown): number | null => {
  const e = error as
    | {
        status?: number
        statusCode?: number
        response?: { status?: number }
      }
    | null
    | undefined
  return e?.status ?? e?.response?.status ?? e?.statusCode ?? null
}

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

/**
 * Make the app show a project's just-committed content.
 *
 * The contents endpoints read a server-side clone that's only re-pulled
 * once its TTL lapses, so invalidating the client cache alone would just
 * refetch the same stale bytes. One `ttl=0` read forces the server to
 * re-pull first; that also warms the clone, so the refetches triggered by
 * the invalidation below see the new commit without each re-pulling.
 *
 * Never rejects. Callers fire this off after a save has already succeeded,
 * so a failure here means the UI is briefly stale, not that anything went
 * wrong with the save -- and an unhandled rejection would be worse than the
 * staleness.
 */
export const refreshProjectContents = async (
  ownerName: string,
  projectName: string,
  queryClient: QueryClient,
): Promise<void> => {
  try {
    await ProjectsService.getProjectContents({
      owner_name: ownerName,
      project_name: projectName,
      ttl: 0,
    })
  } catch {
    // Best effort: still invalidate, so a failed refresh doesn't leave the
    // UI showing pre-save content.
  }
  try {
    await queryClient.invalidateQueries({
      queryKey: ["projects", ownerName, projectName],
    })
  } catch {
    // A refetch that fails leaves its own query in an error state, which the
    // pages already render; there's nothing useful to do with it here.
  }
}
