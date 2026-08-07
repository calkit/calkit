import {
  Alert,
  AlertDescription,
  Button,
  Container,
  Heading,
  Text,
  VStack,
  AlertIcon,
  Code,
  Box,
  Spinner,
} from "@chakra-ui/react"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { z } from "zod"
import { useMutation } from "@tanstack/react-query"
import { useState } from "react"

import { LoginService, type ApiError } from "../../client"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

const cliAuthParamsSchema = z.object({
  device_code: z.string().optional(),
})

export const Route = createFileRoute("/login/device")({
  component: CliAuth,
  validateSearch: (search) => cliAuthParamsSchema.parse(search),
})

function CliAuth() {
  const { device_code: deviceCode } = Route.useSearch()
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const [authorized, setAuthorized] = useState(false)

  const authorizeMutation = useMutation({
    mutationFn: () =>
      LoginService.postLoginDeviceAuthorize({
        requestBody: { device_code: deviceCode! },
      }),
    onSuccess: () => {
      setAuthorized(true)
      showToast(
        "Authorized!",
        "Your CLI has been authorized. You can close this window.",
        "success",
      )
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  const handleLoginRedirect = () => {
    if (!deviceCode) {
      navigate({ to: "/login" })
      return
    }
    localStorage.setItem(
      "post_login_redirect",
      `/login/device?device_code=${deviceCode}`,
    )
    navigate({ to: "/login" })
  }

  if (!deviceCode) {
    return (
      <Container
        minH="100vh"
        maxW="sm"
        justifyContent="center"
        centerContent
        py={10}
      >
        <Box w="full" borderWidth="1px" borderRadius="lg" p={6}>
          <VStack spacing={4} align="stretch">
            <Heading size="md" textAlign="center">
              Invalid Authorization Link
            </Heading>
            <Alert status="warning" borderRadius="md">
              <AlertIcon />
              <AlertDescription>
                This page requires a <Code>device_code</Code> query parameter.
                Start from the CLI login command to open a valid link.
              </AlertDescription>
            </Alert>
            <Button variant="ghost" onClick={() => navigate({ to: "/" })}>
              Go to Home
            </Button>
          </VStack>
        </Box>
      </Container>
    )
  }

  if (isLoggedIn() && isLoading) {
    return (
      <Container minH="100vh" maxW="sm" justifyContent="center" centerContent>
        <VStack spacing={3}>
          <Spinner size="lg" />
          <Text color="gray.600">Loading your account...</Text>
        </VStack>
      </Container>
    )
  }

  if (!isLoggedIn() || !user) {
    return (
      <Container
        minH="100vh"
        maxW="sm"
        justifyContent="center"
        centerContent
        py={10}
      >
        <Box w="full" borderWidth="1px" borderRadius="lg" p={6}>
          <VStack spacing={4} align="stretch">
            <Heading size="md" textAlign="center">
              Authorize CLI Access
            </Heading>
            <Text textAlign="center" color="gray.600">
              You need to sign in before authorizing this CLI request.
            </Text>
            <Button variant="primary" onClick={handleLoginRedirect}>
              Log in to authorize
            </Button>
          </VStack>
        </Box>
      </Container>
    )
  }

  if (authorized) {
    return (
      <Container
        minH="100vh"
        maxW="sm"
        justifyContent="center"
        centerContent
        py={10}
      >
        <Box w="full" borderWidth="1px" borderRadius="lg" p={6}>
          <VStack spacing={4} align="stretch">
            <Alert status="success" borderRadius="md">
              <AlertIcon />
              <AlertDescription>
                CLI access authorized! You can close this window and return to
                your terminal.
              </AlertDescription>
            </Alert>
          </VStack>
        </Box>
      </Container>
    )
  }

  return (
    <Container
      minH="100vh"
      maxW="sm"
      justifyContent="center"
      centerContent
      py={10}
    >
      <Box w="full" borderWidth="1px" borderRadius="lg" p={6}>
        <VStack spacing={4} align="stretch">
          <Heading size="md" textAlign="center">
            Authorize CLI Access
          </Heading>
          <Text color="gray.600">
            Logged in as <Code>{user.github_username || user.email}</Code>
          </Text>
          <Text color="gray.700">
            A Calkit CLI is requesting access to your account. Authorizing will
            create a long-lived access token and deliver it to the waiting CLI
            process.
          </Text>
          <Button
            variant="primary"
            isLoading={authorizeMutation.isPending}
            onClick={() => authorizeMutation.mutate()}
          >
            Authorize CLI
          </Button>
          <Button
            variant="ghost"
            onClick={() => navigate({ to: "/" })}
            isDisabled={authorizeMutation.isPending}
          >
            Cancel
          </Button>
        </VStack>
      </Box>
    </Container>
  )
}
