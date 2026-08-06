import { Container, Text } from "@chakra-ui/react"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"
import { useEffect, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { UsersService, type ApiError } from "../../client"
import { consumeGoogleOAuthState, getGoogleRedirectUri } from "../../lib/google"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

const authParamsSchema = z.object({
  code: z.string(),
  state: z.string(),
  scope: z.string().optional(),
  iss: z.string().optional(),
})

export const Route = createFileRoute("/auth/google")({
  component: GoogleAuth,
  validateSearch: (search) => authParamsSchema.parse(search),
})

function GoogleAuth() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const { loginGoogleMutation } = useAuth()
  // The same Google redirect serves two intents: a logged-out visitor is
  // signing in/up (issue our tokens), a logged-in user is connecting Google to
  // their existing account.
  const loggedIn = isLoggedIn()
  const googleAuthMutation = useMutation({
    mutationFn: (code: string) =>
      UsersService.postUserGoogleAuth({
        requestBody: {
          code,
          redirect_uri: getGoogleRedirectUri(),
        },
      }),
    onSuccess: () => {
      showToast("Success!", "Google account connected successfully.", "success")
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      navigate({ to: "/settings", search: { tab: "profile" } })
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
      // Still navigate back after showing error
      setTimeout(() => {
        navigate({ to: "/settings", search: { tab: "profile" } })
      }, 2000)
    },
  })
  const { code: googleAuthCode, state: googleAuthStateRecv } = Route.useSearch()
  const isMounted = useRef(false)

  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true
      // Confirm this response belongs to a flow this browser started: the
      // returned state must match the single-use value we stored (CSRF
      // protection). A missing/mismatched state is rejected.
      const expectedState = consumeGoogleOAuthState()
      if (
        googleAuthCode &&
        expectedState &&
        googleAuthStateRecv === expectedState
      ) {
        try {
          if (loggedIn) {
            googleAuthMutation.mutate(googleAuthCode)
          } else {
            loginGoogleMutation.mutate({
              code: googleAuthCode,
              redirectUri: getGoogleRedirectUri(),
            })
          }
        } catch {
          // Error should be handled in the mutation
        }
      } else if (googleAuthCode) {
        console.error("Google OAuth state mismatch — possible CSRF attempt")
        showToast(
          "Sign-in failed",
          "Could not verify the Google sign-in request. Please try again.",
          "error",
        )
        navigate({ to: "/login" })
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
          {googleAuthMutation.isPending || loginGoogleMutation.isPending
            ? "Authenticating with Google..."
            : "Done"}
        </Text>
      </Container>
    </>
  )
}
