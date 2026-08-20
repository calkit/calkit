import { Box, Flex, HStack, Heading, Icon, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import {
  Outlet,
  createFileRoute,
  useNavigate,
  useParams,
} from "@tanstack/react-router"
import { MdOutlineDashboard } from "react-icons/md"
import { z } from "zod"

import { ProjectsService } from "../../../../../client"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import PageMenu from "../../../../../components/Common/PageMenu"
import Tooltip from "../../../../../components/Common/Tooltip"
import { dataOrNull } from "../../../../../lib/api"

const appsSearchSchema = z.object({
  ref: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/apps",
)({
  component: ProjectApps,
  validateSearch: (search) => appsSearchSchema.parse(search),
})

function ProjectApps() {
  const { accountName, projectName } = Route.useParams()
  const { ref } = Route.useSearch()
  const navigate = useNavigate()
  // The selected app is a path segment, since its key in calkit.yaml is its
  // identity and has to survive the app's directory being renamed
  const childParams = useParams({ strict: false }) as { appName?: string }
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
    return <LoadingSpinner height="100vh" />
  }
  const apps = appsQuery.data ?? []
  if (apps.length === 0) {
    return (
      <NoArtifactFound
        icon={MdOutlineDashboard}
        title="No apps found"
        hint="An app lets others explore your findings interactively, e.g. to make predictions from a model the project produced."
        docsUrl="https://docs.calkit.org/apps/"
      />
    )
  }
  const selectedName = childParams.appName ?? apps[0]?.name

  return (
    <Flex height="100%" gap={0}>
      {/* Left: index */}
      <PageMenu>
        <Flex align="center" mb={2}>
          <Heading size="md">Apps</Heading>
        </Flex>
        {apps.map((app) => {
          const isSelected = app.name === selectedName
          return (
            <Tooltip
              key={app.name}
              label={app.description ?? app.title ?? app.name}
              placement="right"
            >
              <HStack
                px={1}
                py={0.5}
                borderRadius="md"
                cursor="pointer"
                fontWeight={isSelected ? "semibold" : "normal"}
                _hover={{ color: "blue.500" }}
                onClick={() =>
                  navigate({
                    to: "/$accountName/$projectName/apps/$appName",
                    params: { accountName, projectName, appName: app.name },
                    search: (prev: Record<string, unknown>) => prev,
                  })
                }
                spacing={1}
              >
                <Icon as={MdOutlineDashboard} flexShrink={0} />
                <Text noOfLines={1}>{app.title || app.name}</Text>
              </HStack>
            </Tooltip>
          )
        })}
      </PageMenu>
      {/* Right: the selected app */}
      <Box flex="1" minW={0}>
        <Outlet />
      </Box>
    </Flex>
  )
}
