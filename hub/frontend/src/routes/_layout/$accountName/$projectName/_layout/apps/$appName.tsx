import { Alert, AlertIcon, Box, Flex, Heading, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"

import { type ProjectApp, ProjectsService } from "../../../../../../client"
import LoadingSpinner from "../../../../../../components/Common/LoadingSpinner"
import { dataOrNull } from "../../../../../../lib/api"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/apps/$appName",
)({
  component: ProjectApp_,
})

function AppFrame({ app, gitRef }: { app: ProjectApp; gitRef?: string }) {
  // The API returns a path relative to its own base, not to the frontend,
  // and the app has to be served from the ref being viewed or it resolves
  // against the default branch
  const src =
    `${import.meta.env.VITE_API_URL}${app.url}` +
    (gitRef ? `?ref=${encodeURIComponent(gitRef)}` : "")
  // Takes whatever the header leaves rather than claiming a height of its
  // own, so the title and description can't push the app past the viewport
  return (
    <Box flex="1" minH={0} borderRadius="lg" overflow="hidden">
      <iframe
        title={app.title ?? app.name ?? "app"}
        src={src}
        width="100%"
        height="100%"
        // Project-supplied HTML/JS, so deny it the top-level page, forms
        // and modals. allow-same-origin is required: the app runs Python in
        // a web worker, and a worker script must be same-origin, which an
        // opaque origin can never satisfy. It grants the app the API's
        // origin, not the frontend's, and auth here is a bearer header
        // rather than a cookie.
        sandbox="allow-scripts allow-same-origin allow-popups"
        style={{ borderRadius: "10px" }}
      />
    </Box>
  )
}

function ProjectApp_() {
  const { accountName, projectName, appName } = Route.useParams()
  const { ref } = Route.useSearch()
  // Same key as the parent's, so this is a cache hit rather than a refetch
  const appsQuery = useQuery({
    queryKey: [accountName, projectName, "apps", ref],
    queryFn: () =>
      ProjectsService.getProjectApps({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then(dataOrNull),
  })
  if (appsQuery.isPending) {
    return <LoadingSpinner height="50vh" />
  }
  const app = (appsQuery.data ?? []).find((a) => a.name === appName)
  if (!app || !app.url) {
    return (
      <Alert mt={2} status="warning" borderRadius="xl">
        <AlertIcon />
        No app named "{appName}" in this project.
      </Alert>
    )
  }
  // The height budget lives here, on everything shown for the app, so a
  // long description eats into the frame rather than overflowing the page
  return (
    <Flex direction="column" height="84vh">
      <Heading size="sm" mb={1} flexShrink={0}>
        {app.title || app.name}
      </Heading>
      {app.description ? (
        <Text
          fontSize="sm"
          color="gray.500"
          mb={2}
          noOfLines={2}
          flexShrink={0}
        >
          {app.description}
        </Text>
      ) : null}
      <AppFrame app={app} gitRef={ref} />
    </Flex>
  )
}
