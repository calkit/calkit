import {
  Alert,
  AlertIcon,
  Box,
  Code,
  Flex,
  Heading,
  Link,
  Text,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { createFileRoute, useSearch } from "@tanstack/react-router"

import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import { ProjectsService } from "../../../../../client"
import type { SoftwareItem } from "../../../../../client"

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
        ownerName: accountName,
        projectName,
        ref,
      }),
  })

  const items = softwareQuery.data?.items ?? []

  return (
    <>
      {softwareQuery.isPending ? (
        <LoadingSpinner />
      ) : items.length === 0 ? (
        <Alert mt={2} status="warning" borderRadius="xl">
          <AlertIcon />
          No software has been declared as part of this project. See the
          <Link mx={1} isExternal variant="blue" href="https://docs.calkit.org">
            documentation
          </Link>
          for more information.
        </Alert>
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
