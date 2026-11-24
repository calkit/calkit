// Where Box sends the browser back after someone connects their account

import { Container, Text } from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import mixpanel from "mixpanel-browser"
import { z } from "zod"

import type { AxiosError } from "axios"
import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { consumeBoxOAuthState } from "../../lib/box"

// Without a code if the person denied access, or their institution blocks
// the app
const authParamsSchema = z.object({
  code: z.string().optional(),
  state: z.string().optional(),
  error: z.string().optional(),
  error_description: z.string().optional(),
})

export const Route = createFileRoute("/auth/box")({
  component: BoxAuth,
  validateSearch: (search) => authParamsSchema.parse(search),
})

function BoxAuth() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const goToSettings = () =>
    navigate({ to: "/settings", search: { tab: "connected-accounts" } })
  const mutation = useMutation({
    mutationFn: ({
      code,
      redirectUri,
    }: { code: string; redirectUri: string; returnTo: string | null }) =>
      UsersService.postUserBoxAuth({
        appApiRoutesUsersOAuthCodeExchange: {
          code,
          redirect_uri: redirectUri,
        },
      }).then((response) => response.data),
    onSuccess: (_data, { returnTo }) => {
      showToast("Success!", "Box account connected.", "success")
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      if (returnTo) {
        navigate({ href: returnTo })
      } else {
        goToSettings()
      }
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
      setTimeout(goToSettings, 2000)
    },
  })
  const { code, state, error, error_description } = Route.useSearch()
  const isMounted = useRef(false)

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs once on arrival from Box
  useEffect(() => {
    if (isMounted.current) {
      return
    }
    isMounted.current = true
    // The returned state must match the one this browser stored
    if (error || !code) {
      // E.g., access_denied, which may mean an institution blocks the app
      mixpanel.track("Canceled connecting account", {
        provider: "box",
        error,
      })
      consumeBoxOAuthState()
      showToast(
        "Connection canceled",
        error_description ?? error ?? "No authorization code",
        "error",
      )
      goToSettings()
      return
    }
    const expected = consumeBoxOAuthState()
    if (expected.state && expected.redirectUri && state === expected.state) {
      mutation.mutate({
        code,
        redirectUri: expected.redirectUri,
        returnTo: expected.returnTo,
      })
    } else {
      showToast(
        "Connection failed",
        "Couldn't verify Box request; try again",
        "error",
      )
      goToSettings()
    }
  }, [])

  return (
    <Container
      h="100vh"
      maxW="xs"
      alignItems="stretch"
      justifyContent="center"
      gap={4}
      centerContent
    >
      <Text>{mutation.isPending ? "Connecting Box..." : "Done"}</Text>
    </Container>
  )
}
