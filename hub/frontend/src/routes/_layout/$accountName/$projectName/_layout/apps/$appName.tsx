import { Alert, AlertIcon, Box, Heading, Text } from "@chakra-ui/react"
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
  return (
    <Box height="82vh" borderRadius="lg" overflow="hidden">
      <iframe
        title={app.title ?? app.name ?? "app"}
        src={src}
        width="100%"
        height="100%"
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
  return (
    <>
      <Heading size="sm" mb={1}>
        {app.title || app.name}
      </Heading>
      {app.description ? (
        <Text fontSize="sm" color="gray.500" mb={2} noOfLines={2}>
          {app.description}
        </Text>
      ) : null}
      <AppFrame app={app} gitRef={ref} />
    </>
  )
}
