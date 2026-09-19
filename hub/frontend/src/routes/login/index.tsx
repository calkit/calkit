import {
  Button,
  Container,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Image,
  Input,
  Link,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { z } from "zod"

import type { AxiosError } from "axios"
import Logo from "/assets/images/calkit-no-bg.svg"
import { LoginService, UsersService } from "../../client"
import LoadingSpinner from "../../components/Common/LoadingSpinner"
import OAuthButtons from "../../components/Common/OAuthButtons"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { getAnalyticsConsentToSave } from "../../lib/analytics"
import {
  peekPostLoginRedirect,
  popPostLoginRedirect,
  storeTokens,
} from "../../lib/auth"
import { handleError } from "../../lib/errors"
import {
  consumeGitHubOAuthState,
  consumeGitHubReturnTo,
  getGitHubRedirectUri,
} from "../../lib/github"

const searchSchema = z.object({
  code: z.string().optional(),
  state: z.string().optional(),
  /** Show the create-an-account form rather than the sign-in one. */
  create: z.boolean().optional(),
})

export const Route = createFileRoute("/login/")({
  component: Auth,
  validateSearch: (search) => searchSchema.parse(search),
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      return
    }
    // A signed-in user is only here to connect GitHub, which needs both
    // halves of the handshake. A code with no state is the GitHub App
    // install coming back, and there's nothing to exchange.
    const params = new URLSearchParams(window.location.search)
    if (!(params.has("code") && params.has("state"))) {
      const stored = popPostLoginRedirect() || consumeGitHubReturnTo()
      throw redirect({ to: stored || "/" })
    }
  },
})

interface AuthForm {
  full_name: string
  email: string
  password: string
}

/**
 * One page for signing in and for creating an account.
 *
 * GitHub and Google both create the account on first use, so the two were
 * never separate flows; only the email form differs, and it differs by one
 * field. Keeping them apart meant two pages that had to agree about where
 * to go afterwards, which is where the redirect bugs lived.
 */
function Auth() {
  const {
    loginGitHubMutation,
    loginGoogleMutation,
    loginMutation,
    error,
    resetError,
  } = useAuth()
  const { code: ghAuthCode, state: ghAuthStateRecv, create } = Route.useSearch()
  const navigate = useNavigate()
  const isMounted = useRef(false)
  const creating = Boolean(create)
  // Somewhere specific to be (an invite, a project someone shared) is the
  // only case where an account that can't own a project is any use, since
  // owning one still needs a GitHub repo.
  const projectIsNext = peekPostLoginRedirect() === null
  const githubOnly = creating && projectIsNext
  const showToast = useCustomToast()
  const [handlingOAuth, setHandlingOAuth] = useState(Boolean(ghAuthCode))
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AuthForm>({ mode: "onBlur" })

  const signUpMutation = useMutation({
    mutationFn: async (data: AuthForm) => {
      const analytics_consent = getAnalyticsConsentToSave()
      await UsersService.registerUser({
        userRegister: {
          email: data.email,
          password: data.password,
          full_name: data.full_name,
          analytics_consent,
        },
      }).then((response) => response.data)
      const resp = await LoginService.loginAccessToken({
        bodyLoginLoginAccessToken: {
          username: data.email,
          password: data.password,
          analytics_consent,
        },
      }).then((response) => response.data)
      storeTokens(resp.access_token, resp.refresh_token)
    },
    onSuccess: () => {
      const redirectTo = popPostLoginRedirect()
      // Home shows the start cards to an account with no projects and the
      // project list to everyone else, so it needs nothing from here.
      navigate({ to: redirectTo || "/" })
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })

  const queryClient = useQueryClient()
  // The GitHub callback lands here for both intents; already signed in means
  // linking GitHub to this account rather than signing in
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
    if (isMounted.current) return
    isMounted.current = true
    if (!ghAuthCode) return
    const storedState = consumeGitHubOAuthState()
    if (!(ghAuthStateRecv && storedState && ghAuthStateRecv === storedState)) {
      console.error("OAuth state mismatch — possible CSRF attempt")
      setHandlingOAuth(false)
      return
    }
    if (isLoggedIn()) {
      githubConnectMutation.mutate(ghAuthCode)
      return
    }
    loginGitHubMutation.mutate({
      code: ghAuthCode,
      redirectUri: getGitHubRedirectUri(),
    })
  }, [])

  const onSubmit: SubmitHandler<AuthForm> = (data) => {
    if (creating) {
      signUpMutation.mutate(data)
      return
    }
    resetError()
    loginMutation.mutate({ username: data.email, password: data.password })
  }

  // The connect mutation clears this itself; a failed sign-in is reported
  // through useAuth, so watch its error too rather than spinning forever.
  if (handlingOAuth && !loginGitHubMutation.isError) {
    return <LoadingSpinner height="100vh" />
  }

  return (
    <Container
      h="100vh"
      maxW="xs"
      justifyContent="center"
      gap={3}
      centerContent
    >
      <Image src={Logo} alt="Logo" height="120px" alignSelf="center" mb={-4} />
      <OAuthButtons
        verb={creating ? "Sign up" : "Sign in"}
        page={creating ? "signup" : "login"}
        githubLoading={loginGitHubMutation.isPending}
        googleLoading={loginGoogleMutation.isPending}
        githubOnly={githubOnly}
        showDivider={!githubOnly}
      />
      {githubOnly ? (
        <Text fontSize="xs" color="ui.dim" textAlign="center">
          Your code will live on GitHub, so an account there is required.
        </Text>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} style={{ width: "100%" }}>
          {creating ? (
            <FormControl isInvalid={!!errors.full_name} mb={3}>
              <FormLabel htmlFor="full_name">Name</FormLabel>
              <Input
                id="full_name"
                {...register("full_name", { required: "Name is required" })}
                placeholder="Your name"
              />
              {errors.full_name && (
                <FormErrorMessage>{errors.full_name.message}</FormErrorMessage>
              )}
            </FormControl>
          ) : null}
          <FormControl isInvalid={!!errors.email || Boolean(error)} mb={3}>
            {creating ? <FormLabel htmlFor="email">Email</FormLabel> : null}
            <Input
              id="email"
              type="email"
              placeholder={creating ? "you@example.com" : "Email"}
              {...register("email", { required: "Email is required" })}
            />
            {errors.email && (
              <FormErrorMessage>{errors.email.message}</FormErrorMessage>
            )}
          </FormControl>
          <FormControl isInvalid={!!errors.password || Boolean(error)} mb={4}>
            {creating ? (
              <FormLabel htmlFor="password">Password</FormLabel>
            ) : null}
            <Input
              id="password"
              type="password"
              placeholder={creating ? "Choose a password" : "Password"}
              {...register("password", {
                required: "Password is required",
                ...(creating
                  ? {
                      minLength: { value: 8, message: "At least 8 characters" },
                    }
                  : {}),
              })}
            />
            {errors.password && (
              <FormErrorMessage>{errors.password.message}</FormErrorMessage>
            )}
            {error && <FormErrorMessage>{error}</FormErrorMessage>}
          </FormControl>
          <Button
            variant={creating ? "primary" : undefined}
            type="submit"
            width="full"
            isLoading={
              isSubmitting ||
              loginMutation.isPending ||
              signUpMutation.isPending
            }
          >
            {creating ? "Create account" : "Sign in with email"}
          </Button>
        </form>
      )}
      <Text fontSize="sm">
        {creating ? "Already have an account? " : "New to Calkit? "}
        <Link
          as="button"
          type="button"
          variant="blue"
          onClick={() =>
            navigate({
              to: "/login",
              search: { create: creating ? undefined : true },
            })
          }
        >
          {creating ? "Sign in" : "Create an account."}
        </Link>
      </Text>
    </Container>
  )
}
