import { Box, Code, Flex, Heading, Text } from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useSearch } from "@tanstack/react-router"

import { ProjectsService } from "../../../../../client"
import type { SoftwareItem } from "../../../../../client"
import { FiHardDrive } from "react-icons/fi"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/software",
)({
  component: ProjectSoftware,
})

function SoftwareCard({ item }: { item: SoftwareItem }) {
  return (
    <Box borderWidth={1} borderRadius="lg" p={4}>
      <Heading size="sm" mb={1}>
        {item.title}
      </Heading>
      <Code fontSize="xs" color="gray.500">
        {item.path}
      </Code>
      {item.description && (
        <Text fontSize="sm" mt={2}>
          {item.description}
        </Text>
      )}
    </Box>
  )
}

function ProjectSoftware() {
  const { accountName, projectName } = Route.useParams()
  const layoutSearch = useSearch({
    from: "/_layout/$accountName/$projectName/_layout" as any,
    strict: false,
  }) as any
  const ref: string | undefined = layoutSearch?.ref
  const softwareQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "software", ref],
    queryFn: () =>
      ProjectsService.getProjectSoftware({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })

  const items = softwareQuery.data?.items ?? []

  return (
    <>
      {softwareQuery.isPending ? (
        <LoadingSpinner />
      ) : items.length === 0 ? (
        <NoArtifactFound
          icon={FiHardDrive}
          title="No software found"
          hint="Declare the code this project publishes -- a package, a script, a library -- so it can be cited and reused on its own."
          docsUrl="https://docs.calkit.org/calkit-yaml/"
        />
      ) : (
        <Box>
          <Heading size="md" mb={4}>
            Software
          </Heading>
          <Flex direction="column" gap={3}>
            {items.map((item) => (
              <SoftwareCard key={item.path} item={item} />
            ))}
          </Flex>
        </Box>
      )}
    </>
  )
}
