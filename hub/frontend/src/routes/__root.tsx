import {
  Box,
  Button,
  Flex,
  HStack,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { Outlet, createRootRoute } from "@tanstack/react-router"
import React, { Suspense, useState } from "react"

import NotFound from "../components/Common/NotFound"
import useSubmitOnCmdEnter from "../hooks/useSubmitOnCmdEnter"
import {
  type AnalyticsConsent,
  analyticsEnabled,
  getAnalyticsConsent,
  setAnalyticsConsent,
} from "../lib/analytics"

const loadDevtools = () =>
  Promise.all([
    import("@tanstack/router-devtools"),
    import("@tanstack/react-query-devtools"),
  ]).then(([routerDevtools, reactQueryDevtools]) => {
    return {
      default: () => (
        <>
          <routerDevtools.TanStackRouterDevtools />
          <reactQueryDevtools.ReactQueryDevtools />
        </>
      ),
    }
  })

const TanStackDevtools =
  process.env.NODE_ENV === "production" ? () => null : React.lazy(loadDevtools)

// Shown on every route, including login and signup, until the visitor answers.
// It doesn't block the page, and rejecting is as prominent as accepting, since
// consent only counts if saying no is just as easy.
function AnalyticsConsentBanner() {
  const [answered, setAnswered] = useState(() => getAnalyticsConsent() !== null)
  const bg = useColorModeValue("gray.100", "gray.800")
  const borderColor = useColorModeValue("gray.300", "gray.600")
  if (!analyticsEnabled || answered) return null
  const answer = (consent: AnalyticsConsent) => {
    setAnalyticsConsent(consent)
    setAnswered(true)
  }
  return (
    <Box
      role="region"
      aria-label="Analytics consent"
      position="fixed"
      bottom={0}
      left={0}
      right={0}
      zIndex="banner"
      bg={bg}
      borderTopWidth={1}
      borderColor={borderColor}
      px={6}
      py={4}
    >
      <Flex
        maxW="6xl"
        mx="auto"
        gap={4}
        direction={{ base: "column", md: "row" }}
        align={{ base: "stretch", md: "center" }}
      >
        <Text fontSize="sm" flex={1}>
          With your permission, Calkit uses Mixpanel to learn how the hub is
          used: the pages you visit and features you use, along with your
          browser, device, and approximate location. If you're signed in, this
          is linked to your account, including your name and email. It relies on
          storage in your browser, so it stays off unless you accept. You can
          change your choice at any time under Settings → Privacy.
        </Text>
        <HStack spacing={2} justify="flex-end">
          <Button size="sm" onClick={() => answer("denied")}>
            Reject
          </Button>
          <Button size="sm" onClick={() => answer("granted")}>
            Accept
          </Button>
        </HStack>
      </Flex>
    </Box>
  )
}

function Root() {
  useSubmitOnCmdEnter()
  return (
    <>
      <Outlet />
      <AnalyticsConsentBanner />
      <Suspense>
        <TanStackDevtools />
      </Suspense>
    </>
  )
}

export const Route = createRootRoute({
  component: Root,
  notFoundComponent: () => <NotFound />,
})
