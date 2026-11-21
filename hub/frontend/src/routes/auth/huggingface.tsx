import { Container, Text } from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef } from "react"
import { z } from "zod"

import type { AxiosError } from "axios"
import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { consumeHuggingFaceOAuthState } from "../../lib/huggingface"

const authParamsSchema = z.object({
  code: z.string(),
  state: z.string(),
})

export const Route = createFileRoute("/auth/huggingface")({
  component: HuggingFaceAuth,
  validateSearch: (search) => authParamsSchema.parse(search),
})

function HuggingFaceAuth() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const goToSettings = () =>
    navigate({ to: "/settings", search: { tab: "connected-accounts" } })
  const mutation = useMutation({
    mutationFn: ({
      code,
      redirectUri,
    }: { code: string; redirectUri: string }) =>
      UsersService.postUserHuggingfaceAuth({
        appApiRoutesUsersOAuthCodeExchange: {
          code,
          redirect_uri: redirectUri,
        },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Hugging Face account connected.", "success")
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      goToSettings()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
      setTimeout(goToSettings, 2000)
    },
  })
  const { code, state } = Route.useSearch()
  const isMounted = useRef(false)

  // biome-ignore lint/correctness/useExhaustiveDependencies: runs once on arrival from Hugging Face
  useEffect(() => {
    if (isMounted.current) {
      return
    }
    isMounted.current = true
    // The returned state must match the one this browser stored
    const expected = consumeHuggingFaceOAuthState()
    if (expected.state && expected.redirectUri && state === expected.state) {
      mutation.mutate({ code, redirectUri: expected.redirectUri })
    } else {
      showToast(
        "Connection failed",
        "Could not verify the Hugging Face request. Please try again.",
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
      <Text>{mutation.isPending ? "Connecting Hugging Face..." : "Done"}</Text>
    </Container>
  )
}
