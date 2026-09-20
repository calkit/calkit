import { Box, Button, Container, Flex, Link } from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { Outlet, createFileRoute } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import { useEffect, useRef, useSyncExternalStore } from "react"
import LoadingSpinner from "../components/Common/LoadingSpinner"

import { type UserPublic, UsersService } from "../client"
import Topbar from "../components/Common/Topbar"
import PickSubscription from "../components/UserSettings/PickSubscription"
import useAuth from "../hooks/useAuth"
import {
  getAnalyticsConsent,
  reconcileAnalyticsConsent,
  setAnalyticsConsent,
  subscribeAnalyticsConsent,
} from "../lib/analytics"
import { isAuthenticationError } from "../lib/auth"
import { appName } from "../lib/core"
import { setGitHubReturnTo } from "../lib/github"

export const Route = createFileRoute("/_layout")({
  component: Layout,
})

function InstallGitHubApp() {
  return (
    <>
      <Flex height="100vh" width="full" justify="center" align="center">
        <Link href={`https://github.com/apps/${appName}/installations/new`}>
          <Button variant={"primary"}>Add the Calkit app to GitHub</Button>
        </Link>
      </Flex>
    </>
  )
}

// Keeps this browser's analytics consent and the account's in step, since the
// server checks the account's before sending its own events
function useAccountAnalyticsConsent(user: UserPublic | null | undefined) {
  const queryClient = useQueryClient()
  const consent = useSyncExternalStore(
    subscribeAnalyticsConsent,
    getAnalyticsConsent,
  )
  const seenUserId = useRef<string | null>(null)
  useEffect(() => {
    if (!user) {
      seenUserId.current = null
      return
    }
    const firstSeen = seenUserId.current !== user.id
    seenUserId.current = user.id
    const action = reconcileAnalyticsConsent(
      user.analytics_consent,
      consent,
      firstSeen,
    )
    if (!action) return
    if ("apply" in action) {
      setAnalyticsConsent(action.apply)
    } else {
      UsersService.updateCurrentUser({
        userUpdateMe: { analytics_consent: action.save },
      }).then((response) =>
        queryClient.setQueryData(["currentUser"], response.data),
      )
    }
  }, [user, consent, queryClient])
}

function Layout() {
  const { isLoading, user, logout } = useAuth()
  useAccountAnalyticsConsent(user)
  if (user) {
    mixpanel.identify(user.id)
    mixpanel.people.set({
      $name: user.full_name,
      $email: user.email,
      $github_username: user.github_username,
      $plan_name: user.subscription?.plan_name,
    })
  }
  // GitHub-less users (email/Google signups) don't have — and can't install —
  // the GitHub App, so the install gate only applies to GitHub users.
  const isGithubUser = Boolean(user?.github_username)
  const ghAppInstalledQuery = useQuery({
    queryKey: ["user", "github-app-installations"],
    queryFn: () =>
      UsersService.getUserGithubAppInstallations().then(
        (response) => response.data,
      ),
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    enabled: Boolean(user) && isGithubUser,
    retry: (failureCount, error: any) => {
      if (isAuthenticationError(error)) return false
      return failureCount < 1
    },
  })
  if (ghAppInstalledQuery.error) {
    if (isAuthenticationError(ghAppInstalledQuery.error)) {
      logout()
    }
  }
  // Check that GitHub users have at least one installation
  const ghAppNotInstalled =
    isGithubUser &&
    ghAppInstalledQuery.data &&
    !ghAppInstalledQuery.data.total_count
  if (ghAppNotInstalled) {
    // Installing the app sends the browser away and brings it back through
    // the OAuth callback. Without this it lands on the settings page, which
    // for someone who just created a project is nowhere near what they were
    // doing.
    setGitHubReturnTo(`${location.pathname}${location.search}${location.hash}`)
    location.href = `https://github.com/apps/${appName}/installations/new`
  }

  return (
    <Box>
      {isLoading || (isGithubUser && ghAppInstalledQuery.isPending) ? (
        <LoadingSpinner height="100vh" />
      ) : (
        <>
          {ghAppNotInstalled ? (
            <InstallGitHubApp />
          ) : (
            <>
              {/* If the user doesn't have a subscription, they need to pick one */}
              {!user || user?.subscription ? (
                <Box>
                  <Topbar />
                  <Container px={0} maxW="full">
                    <Outlet />
                  </Container>
                </Box>
              ) : (
                <PickSubscription
                  user={user}
                  containerProps={{
                    display: "flex",
                    alignItems: "center",
                    alignContent: "center",
                    justifyContent: "center",
                    height: "100vh",
                    width: "full",
                  }}
                />
              )}
            </>
          )}
        </>
      )}
    </Box>
  )
}
