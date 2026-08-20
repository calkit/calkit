import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Container,
  Flex,
  Heading,
  HStack,
  Link,
  SimpleGrid,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { useDebounce } from "use-debounce"
import { z } from "zod"

import { ProjectsService } from "../../client"
import ActionsMenu from "../../components/Common/ActionsMenu"
import ClearableInput from "../../components/Common/ClearableInput"
import AccountSetupCard from "../../components/Onboarding/AccountSetupCard"
import FeaturedProjects from "../../components/Onboarding/FeaturedProjects"
import StartPaths from "../../components/Onboarding/StartPaths"
import useAuth from "../../hooks/useAuth"
import { pageWidthNoSidebar } from "../../lib/layout"

const projectsSearchSchema = z.object({
  page: z.number().catch(1),
})

export const Route = createFileRoute("/_layout/")({
  component: Home,
})

const PER_PAGE = 5

function getOwnedProjectsQueryOptions({
  page,
  searchFor,
}: { page: number; searchFor?: string }) {
  return {
    queryFn: () =>
      ProjectsService.getOwnedProjects({
        offset: (page - 1) * PER_PAGE,
        limit: PER_PAGE,
        search_for: searchFor,
      }).then((response) => response.data),
    queryKey: ["projects", { page, searchFor }],
  }
}

function ProjectsTable() {
  const queryClient = useQueryClient()
  const { page } = projectsSearchSchema.parse(Route.useSearch())
  const navigate = useNavigate({ from: Route.fullPath })
  const setPage = (page: number) =>
    navigate({ search: (prev) => ({ ...prev, page }) })
  const [searchForText, setSearchForText] = useState("")
  const [searchFor] = useDebounce(searchForText, 400)

  const {
    data: projects,
    isPending,
    isPlaceholderData,
  } = useQuery({
    ...getOwnedProjectsQueryOptions({ page, searchFor }),
    placeholderData: (prevData) => prevData,
  })

  const hasNextPage = !isPlaceholderData && projects?.data.length === PER_PAGE
  const hasPreviousPage = page > 1

  useEffect(() => {
    if (hasNextPage) {
      queryClient.prefetchQuery(
        getOwnedProjectsQueryOptions({ page: page + 1 }),
      )
    }
  }, [page, queryClient, hasNextPage])

  return (
    <>
      <Flex alignItems="center" py={4} gap={4}>
        <Button variant="primary" as={RouterLink} to="/new">
          + New project
        </Button>
        <ClearableInput
          placeholder="Search..."
          width="33%"
          value={searchForText ?? ""}
          onValueChange={setSearchForText}
        />
      </Flex>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Title</Th>
              <Th>GitHub URL</Th>
              <Th>Description</Th>
              <Th>Visibility</Th>
              <Th>Actions</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(4).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {projects?.data.map((project) => (
                <Tr key={project.id} opacity={isPlaceholderData ? 0.5 : 1}>
                  <Td isTruncated maxWidth="150px">
                    <Link
                      as={RouterLink}
                      to={`/${project.owner_account_name}/${project.name}`}
                    >
                      {project.title}
                    </Link>
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    <Link href={project.git_repo_url} isExternal>
                      <ExternalLinkIcon mx="2px" /> {project.git_repo_url}
                    </Link>
                  </Td>
                  <Td
                    color={!project.description ? "ui.dim" : "inherit"}
                    isTruncated
                    maxWidth="150px"
                  >
                    {project.description || "N/A"}
                  </Td>
                  <Td>{project.is_public ? "Public" : "Private"}</Td>
                  <Td>
                    <ActionsMenu type={"Project"} value={project} />
                  </Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      <Flex
        gap={4}
        alignItems="center"
        mt={4}
        direction="row"
        justifyContent="flex-end"
      >
        <Button onClick={() => setPage(page - 1)} isDisabled={!hasPreviousPage}>
          Previous
        </Button>
        <span>Page {page}</span>
        <Button isDisabled={!hasNextPage} onClick={() => setPage(page + 1)}>
          Next
        </Button>
      </Flex>
    </>
  )
}

/**
 * What a signed-in user sees before they have anything.
 *
 * An empty table says "you have no projects" and leaves the reader to work
 * out what to do about it. The three start paths say what Calkit is for by
 * describing the situations people show up in.
 */
function EmptyState() {
  return (
    <>
      <Heading size="lg" mt={12} mb={2}>
        Let's get your research in one place
      </Heading>
      <Text color="ui.dim" mb={6} maxW="640px">
        Code, data, environments, figures, and the paper, all in one project
        that anyone can clone and re-run. It stays a plain Git repo the whole
        time, and every part of it works with this page closed.
      </Text>
      <Box mb={10}>
        <StartPaths />
      </Box>
      <FeaturedProjects heading="Or look at one that's already there" />
    </>
  )
}

/** The signed-out landing page. */
function LandingPage() {
  return (
    <>
      <Box mt={16} mb={12} textAlign={{ base: "center", md: "left" }}>
        <Heading size="2xl" mb={4} lineHeight="1.2">
          Take control of your research project
        </Heading>
        <Text fontSize="lg" color="ui.dim" maxW="700px" mb={6}>
          Scripts on a laptop, data on a shared drive, a paper in Overleaf, a
          library in Zotero, and no one sure which figure came from which run.
          Calkit connects those pieces into one reproducible project — without
          asking you to leave any of them behind.
        </Text>
        <HStack spacing={4} justify={{ base: "center", md: "flex-start" }}>
          <Link as={RouterLink} to="/new">
            <Button variant="primary" size="lg">
              Start a project
            </Button>
          </Link>
          <Link as={RouterLink} to="/login">
            <Button size="lg" variant="ghost">
              Sign in
            </Button>
          </Link>
        </HStack>
      </Box>
      <SimpleGrid columns={{ base: 1, md: 3 }} spacing={6} mb={14}>
        {[
          {
            title: "Nothing gets locked in",
            body: "Your project is a Git repo with a calkit.yaml in it. The pipeline, environments, and figures are all declared in files you own.",
          },
          {
            title: "It all works offline",
            body: "The CLI runs pipelines, builds environments, and manages data on your machine. This site is where the work becomes visible to everyone else.",
          },
          {
            title: "Best practice, without the setup",
            body: "Environments, a DAG, versioned data, and a paper that rebuilds itself — the things a careful researcher wires together by hand, ready to go.",
          },
        ].map((item) => (
          <Box key={item.title}>
            <Heading size="sm" mb={2}>
              {item.title}
            </Heading>
            <Text fontSize="sm" color="ui.dim">
              {item.body}
            </Text>
          </Box>
        ))}
      </SimpleGrid>
      <Box mb={12}>
        <Heading size="md" mb={1}>
          Where are you starting?
        </Heading>
        <Text color="ui.dim" fontSize="sm" mb={4}>
          Pick the one that sounds like you. You'll sign up on the way, and come
          back to where you left off.
        </Text>
        <StartPaths />
      </Box>
      <FeaturedProjects />
    </>
  )
}

function Home() {
  const { user } = useAuth()
  // Only the count is needed to choose between the empty state and the
  // table, so this asks for one row rather than sharing the table's query,
  // whose key varies with the search box.
  const countQuery = useQuery({
    queryKey: ["projects", "owned-count"],
    queryFn: () =>
      ProjectsService.getOwnedProjects({ limit: 1 }).then(
        (response) => response.data,
      ),
    enabled: Boolean(user),
  })
  const projectCount = countQuery.data?.count ?? 0
  if (!user) {
    return (
      <Container maxW="1000px" pb={16}>
        <LandingPage />
      </Container>
    )
  }
  if (countQuery.isPending) {
    return null
  }
  return (
    <Container maxW={pageWidthNoSidebar} pb={16}>
      {projectCount === 0 ? (
        <EmptyState />
      ) : (
        <>
          <Heading size="lg" textAlign={{ base: "center", md: "left" }} mt={12}>
            Your projects
          </Heading>
          <ProjectsTable />
        </>
      )}
      <Box mt={8} maxW="720px">
        <AccountSetupCard projectCount={projectCount} />
      </Box>
    </Container>
  )
}
