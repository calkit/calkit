import {
  Button,
  Container,
  Divider,
  FormControl,
  FormErrorMessage,
  HStack,
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

import mixpanel from "mixpanel-browser"
import { useEffect, useRef } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { FaGithub, FaGoogle } from "react-icons/fa"
import { z } from "zod"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"

import Logo from "/assets/images/calkit-no-bg.svg"
import { UsersService, type ApiError } from "../../client"
import {
  consumeGitHubOAuthState,
  consumeGitHubReturnTo,
  createGitHubOAuthState,
  getGitHubRedirectUri,
} from "../../lib/github"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import { popPostLoginRedirect } from "../../lib/auth"
import {
  createGoogleOAuthState,
  getGoogleAuthUrl,
  getGoogleRedirectUri,
} from "../../lib/google"

const githubAuthParamsSchema = z.object({
  code: z.string().optional(),
  state: z.string().optional(),
})

export const Route = createFileRoute("/login/")({
  component: Login,
  beforeLoad: async () => {
    // A logged-in user arriving with an OAuth code is connecting GitHub to
    // their existing account, not signing in, so let the component handle
    // it rather than bouncing them away
    const hasOAuthCode = new URLSearchParams(window.location.search).has("code")
    if (isLoggedIn() && !hasOAuthCode) {
      const stored = popPostLoginRedirect()
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
        requestBody: { code, redirect_uri: getGitHubRedirectUri() },
      }),
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
    onError: (err: ApiError) => {
      handleError(err, showToast)
      setTimeout(() => {
        navigate({ to: "/settings", search: { tab: "connected-accounts" } })
      }, 3000)
    },
  })

  const clientId = import.meta.env.VITE_GH_CLIENT_ID

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
        }
      }
    }
  }, [])

  const handleLoginClicked = () => {
    mixpanel.track("Clicked login")
    const state = createGitHubOAuthState()
    location.href = `https://github.com/login/oauth/authorize?client_id=${clientId}&state=${state}`
  }

  const handleGoogleLoginClicked = () => {
    mixpanel.track("Clicked Google login")
    const params = new URLSearchParams({
      client_id: String(import.meta.env.VITE_GOOGLE_CLIENT_ID),
      redirect_uri: getGoogleRedirectUri(),
      response_type: "code",
      scope: "openid email profile",
      state: createGoogleOAuthState(),
      access_type: "offline",
      prompt: "consent",
    })
    location.href = `${getGoogleAuthUrl()}?${params.toString()}`
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
        <Button
          width="full"
          variant="primary"
          isLoading={loginGitHubMutation.isPending}
          onClick={handleLoginClicked}
          rightIcon={<FaGithub />}
        >
          Sign in with GitHub
        </Button>
        <Button
          width="full"
          isLoading={loginGoogleMutation.isPending}
          onClick={handleGoogleLoginClicked}
          rightIcon={<FaGoogle />}
        >
          Sign in with Google
        </Button>
        <HStack width="full">
          <Divider />
          <Text fontSize="xs" color="ui.dim" whiteSpace="nowrap">
            or
          </Text>
          <Divider />
        </HStack>
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
          <Link as={RouterLink} to="/signup" variant="default">
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
