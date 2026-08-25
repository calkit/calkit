import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Code,
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
  useColorModeValue,
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
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import { pageWidthNoSidebar } from "../../lib/layout"

const projectsSearchSchema = z.object({
  page: z.number().catch(1),
})

export const Route = createFileRoute("/_layout/")({
  component: Home,
})

// A calendar date, as 2026-08-21, is what "last updated" means in a list;
// the project's history page has the full timestamps.
const formatDate = (value?: string | null) =>
  value ? new Date(value).toISOString().slice(0, 10) : ""

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
              <Th>Last updated</Th>
              <Th>Visibility</Th>
              <Th>Actions</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(5).fill(null).map((_, index) => (
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
                  <Td whiteSpace="nowrap">
                    {formatDate(project.updated ?? project.created)}
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
        Let's connect all the pieces of your research project
      </Heading>
      <Text color="ui.dim" mb={6} maxW="640px">
        Reading, collecting data, analyzing it, and writing it up, in one
        project instead of multiple. Stored as a plain Git/DVC repo, anyone can
        clone and re-run it, and it all works offline.
      </Text>
      <Box mb={10}>
        <StartPaths source="empty-state" />
      </Box>
      <FeaturedProjects heading="Or look at one that's already there" />
    </>
  )
}

// The four phases a research project cycles through, and what Calkit
// gives each one. The pitch is that they happen in one place.
const LOOP = [
  {
    title: "Read",
    body: "Start with a fresh BibTeX file or import your Zotero collection as the project's bibliography and sync it bidirectionally.",
  },
  {
    title: "Collect",
    body: "Type data in, upload it, import it by DOI, URL, or Git repo, or create it as part of the pipeline. Every dataset keeps track of where it came from.",
  },
  {
    title: "Analyze",
    body: "Plot offline or in the browser, then save as a pipeline stage with a precisely defined environment. Figures trace back to code and data.",
  },
  {
    title: "Write",
    body: "A LaTeX paper that rebuilds from the pipeline, or the Overleaf project you already have, linked so its figures and results never go stale.",
  },
]

/** The signed-out landing page. */
function LandingPage() {
  const loopBorder = useColorModeValue("gray.200", "gray.600")
  return (
    <>
      <Box mt={16} mb={12} textAlign={{ base: "center", md: "left" }}>
        <Heading size="2xl" mb={4} lineHeight="1.2">
          Take control of your research project
        </Heading>
        <Text fontSize="lg" color="ui.dim" maxW="700px" mb={6}>
          Scripts on a cluster, notebooks on a laptop, data on a shared drive, a
          paper in Overleaf, a library in Zotero, and no one sure which figure
          came from where. Calkit connects it all: lit review, data collection,
          analysis, and writing, in one reproducible project, without asking you
          to leave any of those tools behind.
        </Text>
        <HStack spacing={4} justify={{ base: "center", md: "flex-start" }}>
          <Button as={RouterLink} to="/new" variant="primary" size="lg">
            Start a project
          </Button>
          <Button as={RouterLink} to="/login" size="lg" variant="outline">
            Sign in
          </Button>
        </HStack>
      </Box>
      {/* The loop a project actually moves through, and the tool each
          phase usually lives in. One place for all four is the pitch. */}
      <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4} mb={10}>
        {LOOP.map((phase, index) => (
          <Box
            key={phase.title}
            borderWidth={1}
            borderColor={loopBorder}
            borderRadius="lg"
            p={4}
          >
            <Text fontSize="xs" color="ui.dim" mb={1}>
              {index + 1}
            </Text>
            <Heading size="sm" mb={1}>
              {phase.title}
            </Heading>
            <Text fontSize="sm" color="ui.dim">
              {phase.body}
            </Text>
          </Box>
        ))}
      </SimpleGrid>
      <SimpleGrid columns={{ base: 1, md: 3 }} spacing={6} mb={14}>
        {[
          {
            title: "No lock-in",
            body: (
              <>
                Your project is a Git/DVC repo with a <Code>calkit.yaml</Code>{" "}
                file in it. The pipeline, environments, and figures are all
                declared in files you own.
              </>
            ),
          },
          {
            title: "It all works offline",
            body: "The CLI runs pipelines, builds environments, and manages data on your machine just as easily as the web app does.",
          },
          {
            title: "Best practices, without the DIY part",
            body: "Environment management, a workflow system, versioned data, and a paper that rebuilds itself: components typically integrated manually, ready to go from day one.",
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
          Pick the one that best describes your goal:
        </Text>
        <StartPaths source="landing" />
      </Box>
      <FeaturedProjects />
    </>
  )
}

function Home() {
  const { user, isLoading } = useAuth()
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
  // A stored token means a user is on the way, and useAuth reports not-loading
  // for the tick before the request starts. Treating that gap as "signed out"
  // flashes the landing page at someone who is signed in.
  if (isLoading || (!user && isLoggedIn())) {
    return null
  }
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
  // A failed count says nothing about whether there are projects, so it
  // falls through to the table, which shows its own error, rather than
  // telling someone with twenty projects to start their first.
  return (
    <Container maxW={pageWidthNoSidebar} pb={16}>
      {projectCount === 0 && !countQuery.isError ? (
        <EmptyState />
      ) : (
        <>
          <Heading size="lg" textAlign={{ base: "center", md: "left" }} mt={12}>
            Your projects
          </Heading>
          <ProjectsTable />
        </>
      )}
      <Box mt={8}>
        <AccountSetupCard projectCount={projectCount} />
      </Box>
    </Container>
  )
}
