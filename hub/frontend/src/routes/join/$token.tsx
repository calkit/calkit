import { Container, Spinner, Text, VStack } from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef } from "react"

import { ProjectsService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

export const Route = createFileRoute("/join/$token")({
  component: Join,
})

function Join() {
  const { token } = Route.useParams()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const ran = useRef(false)

  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectInvitationRedemption({ token }),
    onSuccess: (data) => {
      showToast(
        "You're in!",
        `You now have ${data.role_name} access to this project.`,
        "success",
      )
      navigate({
        to: "/$accountName/$projectName",
        params: {
          accountName: data.owner_name,
          projectName: data.project_name,
        },
      })
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  useEffect(() => {
    if (ran.current) {
      return
    }
    ran.current = true
    if (!isLoggedIn()) {
      // Send unauthenticated visitors to sign up, then return here to redeem.
      localStorage.setItem("post_login_redirect", `/join/${token}`)
      navigate({ to: "/signup" })
      return
    }
    mutation.mutate()
  }, [])

  return (
    <Container h="100vh" justifyContent="center" centerContent>
      <VStack gap={4}>
        <Spinner size="lg" />
        <Text>
          {mutation.isError
            ? "This invite link is invalid or has expired."
            : "Joining project…"}
        </Text>
      </VStack>
    </Container>
  )
}
