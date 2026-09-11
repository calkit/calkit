import { Flex, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"

import { ProjectsService } from "../../../../../../client"
import LoadingSpinner from "../../../../../../components/Common/LoadingSpinner"
import { dataOrNull } from "../../../../../../lib/api"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/apps/",
)({
  component: AppsIndex,
})

function AppsIndex() {
  const { accountName, projectName } = Route.useParams()
  const { ref } = Route.useSearch()
  const navigate = useNavigate()
  const appsQuery = useQuery({
    queryKey: [accountName, projectName, "apps", ref],
    queryFn: () =>
      ProjectsService.getProjectApps({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then(dataOrNull),
  })
  const first = appsQuery.data?.[0]
  // Land on an app rather than an empty panel, the way the presentations
  // index selects the first item
  useEffect(() => {
    if (!first) return
    navigate({
      to: "/$accountName/$projectName/apps/$appName",
      params: { accountName, projectName, appName: first.name },
      search: (prev: Record<string, unknown>) => prev,
      replace: true,
    })
  }, [first, accountName, projectName, navigate])
  if (appsQuery.isPending) {
    return <LoadingSpinner height="50vh" />
  }
  return (
    <Flex align="center" justify="center" height="300px" color="gray.500">
      <Text>Select an app</Text>
    </Flex>
  )
}
