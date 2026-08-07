import { Box, Button, Container, Flex, Link } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Outlet, createFileRoute } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import LoadingSpinner from "../components/Common/LoadingSpinner"

import { UsersService } from "../client"
import Topbar from "../components/Common/Topbar"
import PickSubscription from "../components/UserSettings/PickSubscription"
import useAuth from "../hooks/useAuth"
import { isAuthenticationError } from "../lib/auth"
import { appName } from "../lib/core"

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

function Layout() {
  const { isLoading, user, logout } = useAuth()
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
    queryFn: () => UsersService.getUserGithubAppInstallations(),
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
