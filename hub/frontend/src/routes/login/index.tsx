import {
  Button,
  Container,
  FormControl,
  FormErrorMessage,
  Image,
  Input,
  Link,
  Text,
} from "@chakra-ui/react"
import {
  Link as RouterLink,
  createFileRoute,
  redirect,
} from "@tanstack/react-router"

import { useEffect, useRef, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { z } from "zod"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import type { AxiosError } from "axios"
import Logo from "/assets/images/calkit-no-bg.svg"
import { UsersService } from "../../client"
import LoadingSpinner from "../../components/Common/LoadingSpinner"
import OAuthButtons from "../../components/Common/OAuthButtons"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { popPostLoginRedirect } from "../../lib/auth"
import { handleError } from "../../lib/errors"
import {
  consumeGitHubOAuthState,
  consumeGitHubReturnTo,
  getGitHubRedirectUri,
} from "../../lib/github"

const githubAuthParamsSchema = z.object({
  code: z.string().optional(),
  state: z.string().optional(),
})

export const Route = createFileRoute("/login/")({
  component: Login,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      return
    }
    // A logged-in user is only here to connect GitHub to their account, and
    // that needs both halves of the handshake. Landing here with a code but
    // no state (the GitHub App install sends one back, since we never
    // started an OAuth flow) leaves nothing to exchange, and rendering the
    // sign-in form at that point looks exactly like having been signed out.
    const params = new URLSearchParams(window.location.search)
    const connecting = params.has("code") && params.has("state")
    if (!connecting) {
      const stored = popPostLoginRedirect() || consumeGitHubReturnTo()
      throw redirect({ to: stored || "/" })
    }
  },
  validateSearch: (search) => githubAuthParamsSchema.parse(search),
})

interface EmailLoginForm {
  username: string
  password: string
}

function Login() {
  const {
    loginGitHubMutation,
    loginGoogleMutation,
    loginMutation,
    error,
    resetError,
  } = useAuth()
  const { code: ghAuthCode, state: ghAuthStateRecv } = Route.useSearch()
  const isMounted = useRef(false)
  // Coming back from GitHub, the sign-in form is the wrong thing to show:
  // the user is already signed in and only connecting an account, and a
  // sign-in page at that moment reads as having been signed out. Cleared if
  // the code turns out to be unusable, which puts the form back.
  const [handlingOAuth, setHandlingOAuth] = useState(Boolean(ghAuthCode))
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<EmailLoginForm>({ mode: "onBlur" })
  const onEmailLogin: SubmitHandler<EmailLoginForm> = (data) => {
    resetError()
    loginMutation.mutate(data)
  }

  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const showToast = useCustomToast()
  // The GitHub callback lands here for both intents; when already signed in
  // we're linking GitHub to this account rather than logging in
  const githubConnectMutation = useMutation({
    mutationFn: (code: string) =>
      UsersService.postUserGithubAuth({
        oAuthCodeExchange: { code, redirect_uri: getGitHubRedirectUri() },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "GitHub account connected.", "success")
      queryClient.invalidateQueries({
        queryKey: ["user", "connected-accounts"],
      })
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      // Back to whatever the user was doing, else the settings tab
      const returnTo = consumeGitHubReturnTo()
      if (returnTo) {
        window.location.replace(returnTo)
        return
      }
      navigate({ to: "/settings", search: { tab: "connected-accounts" } })
    },
    onError: (err: AxiosError) => {
      setHandlingOAuth(false)
      handleError(err, showToast)
      // Back to what was interrupted, where the connect prompt is still up
      const returnTo = consumeGitHubReturnTo()
      setTimeout(() => {
        if (returnTo) {
          window.location.replace(returnTo)
          return
        }
        navigate({ to: "/settings", search: { tab: "connected-accounts" } })
      }, 3000)
    },
  })

  useEffect(() => {
    if (!isMounted.current) {
      isMounted.current = true
      if (ghAuthCode) {
        const storedState = consumeGitHubOAuthState()
        if (ghAuthStateRecv && storedState && ghAuthStateRecv === storedState) {
          try {
            if (isLoggedIn()) {
              githubConnectMutation.mutate(ghAuthCode)
              return
            }
            loginGitHubMutation.mutate({
              code: ghAuthCode,
              redirectUri: getGitHubRedirectUri(),
            })
          } catch {
            // Error should be handled in the mutation
          }
        } else {
          console.error("OAuth state mismatch — possible CSRF attempt")
          setHandlingOAuth(false)
        }
      }
    }
  }, [])

  // The connect mutation clears this itself; a failed sign-in is reported
  // through useAuth, so watch its error too rather than spinning forever.
  if (handlingOAuth && !loginGitHubMutation.isError) {
    return <LoadingSpinner height="100vh" />
  }

  return (
    <>
      <Container
        h="100vh"
        maxW="xs"
        justifyContent="center"
        gap={4}
        centerContent
      >
        <Image
          src={Logo}
          alt="Logo"
          height="150px"
          alignSelf="center"
          mb={-9}
        />
        <OAuthButtons
          verb="Sign in"
          page="login"
          githubLoading={loginGitHubMutation.isPending}
          googleLoading={loginGoogleMutation.isPending}
        />
        <form onSubmit={handleSubmit(onEmailLogin)} style={{ width: "100%" }}>
          <FormControl isInvalid={Boolean(error)} mb={3}>
            <Input
              type="email"
              placeholder="Email"
              {...register("username", { required: true })}
            />
          </FormControl>
          <FormControl isInvalid={Boolean(error)} mb={3}>
            <Input
              type="password"
              placeholder="Password"
              {...register("password", { required: true })}
            />
            {error && <FormErrorMessage>{error}</FormErrorMessage>}
          </FormControl>
          <Button
            type="submit"
            width="full"
            isLoading={isSubmitting || loginMutation.isPending}
          >
            Sign in with email
          </Button>
        </form>
        <Text fontSize="sm">
          New to Calkit?{" "}
          <Link as={RouterLink} to="/signup" variant="blue">
            Create an account.
          </Link>
        </Text>
        <Text fontSize={10} mt={-1}>
          <Link isExternal variant="default" href="https://calkit.org">
            Learn more
          </Link>
        </Text>
      </Container>
    </>
  )
}
