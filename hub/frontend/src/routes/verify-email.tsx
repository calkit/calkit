import { CheckCircleIcon, WarningTwoIcon } from "@chakra-ui/icons"
import {
  Button,
  Container,
  Heading,
  Icon,
  Spinner,
  Text,
} from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Link as RouterLink, createFileRoute } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useEffect } from "react"
import { z } from "zod"

import { UsersService } from "../client"
import { isLoggedIn } from "../hooks/useAuth"

const verifySearchSchema = z.object({ token: z.string().catch("") })

/**
 * Where the link in the verification email lands.
 *
 * Open to anyone, since the link may be clicked in a browser that isn't
 * signed in; the token is what proves the address.
 */
export const Route = createFileRoute("/verify-email")({
  component: VerifyEmail,
  validateSearch: (search) => verifySearchSchema.parse(search),
})

function VerifyEmail() {
  const { token } = Route.useSearch()
  const queryClient = useQueryClient()
  const loggedIn = isLoggedIn()
  const verifyQuery = useQuery({
    queryKey: ["verify-email", token],
    queryFn: () =>
      UsersService.postVerifyEmail({
        emailVerificationToken: { token },
      }).then((response) => response.data),
    enabled: !!token,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: Number.POSITIVE_INFINITY,
  })
  // The signed-in user's badge in settings reads from the cached user
  useEffect(() => {
    if (verifyQuery.isSuccess && loggedIn) {
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
    }
  }, [verifyQuery.isSuccess, loggedIn, queryClient])
  const errorDetail = (
    (verifyQuery.error as AxiosError | null)?.response?.data as
      | { detail?: unknown }
      | undefined
  )?.detail
  const failed = !token || verifyQuery.isError
  return (
    <Container
      h="100vh"
      maxW="sm"
      alignItems="center"
      justifyContent="center"
      gap={4}
      centerContent
    >
      {token && verifyQuery.isPending ? (
        <>
          <Spinner size="lg" color="ui.main" />
          <Text textAlign="center">Verifying your email...</Text>
        </>
      ) : failed ? (
        <>
          <Icon as={WarningTwoIcon} boxSize={10} color="orange.400" />
          <Heading size="lg" textAlign="center">
            This link didn't work
          </Heading>
          <Text textAlign="center" color="ui.dim">
            {typeof errorDetail === "string"
              ? errorDetail
              : "The link is missing its token, has expired, or was already used."}
          </Text>
          <Text textAlign="center" fontSize="sm">
            You can request a fresh code or link from your settings.
          </Text>
          <Button
            as={RouterLink}
            to={loggedIn ? "/settings" : "/login"}
            search={loggedIn ? ({ tab: "profile" } as any) : undefined}
            variant="primary"
          >
            {loggedIn ? "Go to settings" : "Log in"}
          </Button>
        </>
      ) : (
        <>
          <Icon as={CheckCircleIcon} boxSize={10} color="ui.success" />
          <Heading size="lg" textAlign="center">
            Email verified
          </Heading>
          <Text textAlign="center" color="ui.dim">
            Thanks. Your address is confirmed.
          </Text>
          <Button
            as={RouterLink}
            to={loggedIn ? "/" : "/login"}
            variant="primary"
          >
            {loggedIn ? "Continue" : "Log in"}
          </Button>
        </>
      )}
    </Container>
  )
}
