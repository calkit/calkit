import { Container, Text } from "@chakra-ui/react"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"
import { useEffect, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { UsersService, type ApiError } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

// Zotero uses OAuth 1.0a, so it sends back a verifier rather than a code, and
// the request token it was issued against stands in for a state parameter.
// Zotero omits the verifier when the user declines.
// Kept in sync with the references page, which stashes where to return.
const ZOTERO_RETURN_KEY = "zoteroAuthReturnTo"

const authParamsSchema = z.object({
  oauth_token: z.string(),
  oauth_verifier: z.string().optional(),
})

export const Route = createFileRoute("/auth/zotero")({
  component: ZoteroAuth,
  validateSearch: (search) => authParamsSchema.parse(search),
})

function ZoteroAuth() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const zoteroAuthMutation = useMutation({
    mutationFn: ({
      oauthToken,
      oauthVerifier,
    }: {
      oauthToken: string
      oauthVerifier: string
    }) =>
      UsersService.postUserZoteroAuth({
        requestBody: {
          oauth_token: oauthToken,
          oauth_verifier: oauthVerifier,
        },
      }),
    onSuccess: () => {
      showToast("Success!", "Zotero account connected successfully.", "success")
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      returnToOrigin(true)
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
      // Still navigate back after showing error
      setTimeout(() => returnToOrigin(false), 2000)
    },
  })
  const { oauth_token: oauthToken, oauth_verifier: oauthVerifier } =
    Route.useSearch()
  const isMounted = useRef(false)
  // Return to wherever the connect flow was started (e.g. the references import
  // modal), reopening the import modal on success. Falls back to settings.
  const returnToOrigin = (success: boolean) => {
    const origin = sessionStorage.getItem(ZOTERO_RETURN_KEY)
    sessionStorage.removeItem(ZOTERO_RETURN_KEY)
    if (origin) {
      const url = new URL(origin, window.location.origin)
      if (success) url.searchParams.set("import_zotero_open", "true")
      window.location.assign(url.pathname + url.search)
    } else {
      navigate({ to: "/settings", search: { tab: "connected-accounts" } })
    }
  }

  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true
      if (oauthToken && oauthVerifier) {
        try {
          zoteroAuthMutation.mutate({ oauthToken, oauthVerifier })
        } catch {
          // Error should be handled in the mutation
        }
      } else {
        showToast(
          "Not connected",
          "Zotero access was not granted. Please try again.",
          "error",
        )
        returnToOrigin(false)
      }
    }
  }, [])

  return (
    <>
      <Container
        h="100vh"
        maxW="xs"
        alignItems="stretch"
        justifyContent="center"
        gap={4}
        centerContent
      >
        <Text>
          {zoteroAuthMutation.isPending
            ? "Authenticating with Zotero..."
            : "Done"}
        </Text>
      </Container>
    </>
  )
}
