import { Container, Text } from "@chakra-ui/react"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"
import { useEffect, useRef } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { UsersService, type ApiError } from "../../client"
import { getZenodoRedirectUri, zenodoAuthStateParam } from "../../lib/zenodo"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

const authParamsSchema = z.object({
  code: z.string(),
  state: z.string(),
})

export const Route = createFileRoute("/auth/zenodo")({
  component: ZenodoAuth,
  validateSearch: (search) => authParamsSchema.parse(search),
})

function ZenodoAuth() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const zenodoAuthMutation = useMutation({
    mutationFn: (code: string) =>
      UsersService.postUserZenodoAuth({
        requestBody: {
          code,
          redirect_uri: getZenodoRedirectUri(),
        },
      }),
    onSuccess: () => {
      showToast("Success!", "Zenodo account connected successfully.", "success")
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
  const { code: zenodoAuthCode, state: zenodoAuthStateRecv } = Route.useSearch()
  const isMounted = useRef(false)

  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true
      if (zenodoAuthCode && zenodoAuthStateRecv === zenodoAuthStateParam) {
        try {
          zenodoAuthMutation.mutate(zenodoAuthCode)
        } catch {
          // Error should be handled in the mutation
        }
      } else if (
        zenodoAuthCode &&
        zenodoAuthStateRecv !== zenodoAuthStateParam
      ) {
        console.error(
          `Received state parameter does not match sent (${zenodoAuthStateParam})`,
        )
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
          {zenodoAuthMutation.isPending
            ? "Authenticating with Zenodo..."
            : "Done"}
        </Text>
      </Container>
    </>
  )
}
