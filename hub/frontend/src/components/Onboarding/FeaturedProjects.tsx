import {
  Badge,
  Box,
  Flex,
  Heading,
  Link,
  LinkBox,
  LinkOverlay,
  SimpleGrid,
  Skeleton,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"

import { ProjectsService } from "../../client"

/**
 * The hub's curated example projects.
 *
 * What a newcomer needs to see is a finished project -- environment,
 * pipeline, figures, paper, all connected -- not whatever happened to be
 * created most recently. The list is configured server-side, so curating it
 * doesn't mean shipping a frontend.
 */
const FeaturedProjects = ({ heading }: { heading?: string }) => {
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const featuredQuery = useQuery({
    queryKey: ["projects", "featured"],
    queryFn: () =>
      ProjectsService.getFeaturedProjects().then((response) => response.data),
    staleTime: 5 * 60_000,
  })
  const projects = featuredQuery.data?.data ?? []
  if (!featuredQuery.isPending && !projects.length) {
    return null
  }
  return (
    <Box>
      <Flex align="baseline" gap={3} mb={1}>
        <Heading size="md">{heading ?? "See it put together"}</Heading>
        <Link as={RouterLink} to="/projects" fontSize="sm" variant="blue">
          Browse all projects →
        </Link>
      </Flex>
      <Text color="ui.dim" fontSize="sm" mb={4}>
        Real projects, each one runnable end to end from its repo.
      </Text>
      {featuredQuery.isPending ? (
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          {new Array(3).fill(null).map((_, index) => (
            <Skeleton key={index} height="118px" borderRadius="lg" />
          ))}
        </SimpleGrid>
      ) : (
        <SimpleGrid columns={{ base: 1, md: 3 }} spacing={4}>
          {projects.map((project) => (
            <LinkBox
              key={project.id}
              as="article"
              borderWidth={1}
              borderColor={borderColor}
              borderRadius="lg"
              bg={cardBg}
              p={4}
              transition="all 0.15s"
              _hover={{ borderColor: "ui.main", shadow: "md" }}
            >
              <Badge colorScheme="teal" mb={2}>
                {project.owner_account_display_name}
              </Badge>
              <Heading size="sm" mb={1} noOfLines={2}>
                <LinkOverlay
                  as={RouterLink}
                  to={`/${project.owner_account_name}/${project.name}`}
                  onClick={() =>
                    mixpanel.track("Clicked featured project", {
                      project: `${project.owner_account_name}/${project.name}`,
                    })
                  }
                >
                  {project.title}
                </LinkOverlay>
              </Heading>
              <Text fontSize="sm" color="ui.dim" noOfLines={3}>
                {project.description || "No description."}
              </Text>
            </LinkBox>
          ))}
        </SimpleGrid>
      )}
    </Box>
  )
}

export default FeaturedProjects
