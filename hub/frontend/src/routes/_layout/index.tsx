import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Container,
  Flex,
  Heading,
  Icon,
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
  chakra,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
} from "@tanstack/react-router"
import { useEffect, useRef, useState } from "react"
import { FiArrowRight } from "react-icons/fi"
import { useDebounce } from "use-debounce"
import { z } from "zod"

import { ProjectsService } from "../../client"
import ActionsMenu from "../../components/Common/ActionsMenu"
import ClearableInput from "../../components/Common/ClearableInput"
import AccountSetupCard from "../../components/Onboarding/AccountSetupCard"
import FeaturedProjects from "../../components/Onboarding/FeaturedProjects"
import StartPaths from "../../components/Onboarding/StartPaths"
import NewProjectModal from "../../components/Projects/NewProjectModal"
import useAuth, { isLoggedIn } from "../../hooks/useAuth"
import { pageWidthNoSidebar } from "../../lib/layout"

const projectsSearchSchema = z.object({
  page: z.number().optional().catch(1),
  // Set once, by signing in. Home is the only place that knows whether the
  // account has a project yet, so it decides what a new arrival sees.
  welcome: z.boolean().optional(),
})

export const Route = createFileRoute("/_layout/")({
  component: Home,
  validateSearch: (search) => projectsSearchSchema.parse(search),
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
  const newProjectModal = useDisclosure()
  const queryClient = useQueryClient()
  const { page = 1 } = Route.useSearch()
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
        <Button variant="primary" onClick={newProjectModal.onOpen}>
          + New project
        </Button>
        <NewProjectModal
          isOpen={newProjectModal.isOpen}
          onClose={newProjectModal.onClose}
        />
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
        Make your project single-button reproducible
      </Heading>
      <Text color="ui.dim" mb={6} maxW="640px">
        Lit review, data collection, analysis, and writing all in one place.
      </Text>
      <Box mb={10}>
        <StartPaths source="empty-state" />
      </Box>
      <FeaturedProjects heading="Or take a look at some examples" />
    </>
  )
}

// The four phases a research project cycles through, and what Calkit
// gives each one. The pitch is that they happen in one place.
const LOOP = [
  {
    title: "Lit review/planning",
    body: "Add your references (optionally linking with Zotero) and come up with a plan.",
  },
  {
    title: "Data collection",
    body: "Enter manually, upload, import from elsewhere, or run simulations in self-contained environments.",
  },
  {
    title: "Analysis",
    body: "Plot in Python, R, Julia, or MATLAB. Changes to data clearly signal and rerun necessary analyses.",
  },
  {
    title: "Writing",
    body: "Quarto, LaTeX, and more, optionally linked with Overleaf. Like elsewhere, upstream changes propagate automatically.",
  },
]

/**
 * The loops over the four stages, as in the diagram on the docs home page.
 *
 * Two kinds of iteration, which is the whole point of keeping the stages in
 * one repo. The arc returning into a card is iteration within that stage;
 * the arcs reaching back over earlier cards are iteration between stages,
 * e.g. writing sending you back to the analysis or to collect more data.
 *
 * Drawn in a viewBox 800 wide so the four x positions are the centers of
 * four equal columns, then stretched to whatever the grid is actually
 * wide. Hidden below `md`, where the grid drops to two columns and the
 * arcs would point at the wrong cards.
 */
function LoopArcs() {
  const color = useColorModeValue("gray.400", "gray.500")
  const centers = [100, 300, 500, 700]
  // A cubic whose control points share a y only reaches three quarters of
  // the way to it, so these are the control values that put each arc where
  // the comment says. Longer reaches ride higher and start and land further
  // out, so no two arcs touch and the arrowheads don't stack up.
  const BASE = 80
  const spans = [
    { from: 1, to: 0, peak: 35, out: 40 }, // tops out around y=46
    { from: 2, to: 1, peak: 35, out: 40 },
    { from: 3, to: 2, peak: 35, out: 40 },
    { from: 2, to: 0, peak: 11, out: 56 }, // around y=28
    { from: 3, to: 1, peak: 11, out: 56 },
    { from: 3, to: 0, peak: -13, out: 72 }, // around y=10
  ]
  return (
    <Box
      display={{ base: "none", md: "block" }}
      color={color}
      aria-hidden="true"
    >
      <chakra.svg
        viewBox={`0 0 800 ${BASE}`}
        width="100%"
        height={`${BASE}px`}
        preserveAspectRatio="none"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        sx={{ "& path": { vectorEffect: "non-scaling-stroke" } }}
      >
        <title>Iteration within each stage and back to earlier stages</title>
        <defs>
          <marker
            id="loop-arrowhead"
            viewBox="0 0 8 8"
            refX={7}
            refY={4}
            markerWidth={5}
            markerHeight={5}
            orient="auto"
          >
            <path d="M0 0 L8 4 L0 8 z" fill="currentColor" stroke="none" />
          </marker>
        </defs>
        {spans.map(({ from, to, peak, out }) => {
          const sx = centers[from] - out
          const ex = centers[to] + out
          return (
            <path
              key={`${from}-${to}`}
              d={`M ${sx} ${BASE} C ${sx} ${peak}, ${ex} ${peak}, ${ex} ${BASE}`}
              markerEnd="url(#loop-arrowhead)"
            />
          )
        })}
        {/* Iteration within a stage: a short loop back into the same card */}
        {centers.map((cx) => (
          <path
            key={cx}
            d={`M ${cx + 12} ${BASE} C ${cx + 18} 56, ${cx - 18} 56, ${cx - 12} ${BASE}`}
            markerEnd="url(#loop-arrowhead)"
          />
        ))}
      </chakra.svg>
    </Box>
  )
}

/** The signed-out landing page. */
function LandingPage() {
  const loopBorder = useColorModeValue("gray.200", "gray.600")
  return (
    <>
      <Box mt={16} mb={12} textAlign={{ base: "center", md: "left" }}>
        <Heading size="2xl" mb={4} lineHeight="1.2">
          Single-button reproducible research
        </Heading>
        <Text fontSize="lg" color="ui.dim">
          All stages and context in one project repository, connected by an
          environment-aware pipeline that can be verified with a single command.
          Work locally or on the web. Totally open-source with zero lock-in.
        </Text>
        <Button
          as={RouterLink}
          to="/login"
          variant="primary"
          size="lg"
          mt={7}
          px={8}
          height={14}
          fontSize="lg"
          rightIcon={<Icon as={FiArrowRight} />}
          boxShadow="lg"
          transition="transform 0.15s, box-shadow 0.15s"
          _hover={{ transform: "translateY(-2px)", boxShadow: "xl" }}
        >
          Get started
        </Button>
      </Box>
      {/* The loop a project actually moves through, and the tool each
          phase usually lives in. One place for all four is the pitch. */}
      <Box mb={4}>
        <Heading size="md" mb={1}>
          Faster iteration from tighter integration
        </Heading>
        <Text color="ui.dim" fontSize="sm">
          Change the data and the analysis, figures, and paper all follow
          without manually transferring data between different apps or
          platforms. Collaborate and iterate within and across stages
          seamlessly.
        </Text>
      </Box>
      <LoopArcs />
      <SimpleGrid columns={{ base: 2, md: 4 }} spacing={4} mb={8}>
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
      <FeaturedProjects />
    </>
  )
}

function Home() {
  const { user, isLoading } = useAuth()
  const navigate = useNavigate()
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
  // Signing in sends everyone here; an account with nothing in it gets the
  // new-project form over the top, and everyone else just gets their
  // projects. The flag is dropped either way, so a refresh or a later visit
  // doesn't reopen it.
  const { welcome } = Route.useSearch()
  const newProjectModal = useDisclosure()
  // Acted on once and only once. Creating a project refetches the count,
  // which runs this again, and a second navigate would land on home over
  // the project that was just opened.
  const welcomeHandled = useRef(false)
  useEffect(() => {
    if (welcomeHandled.current || !welcome || !countQuery.isSuccess) return
    welcomeHandled.current = true
    if (projectCount === 0) {
      newProjectModal.onOpen()
    }
    navigate({ to: "/", search: { welcome: undefined }, replace: true })
  }, [welcome, countQuery.isSuccess, projectCount, navigate, newProjectModal])
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
      {/* Installing and connecting things is asked once there's a project
          to use them on, not on the first signed-in page */}
      {projectCount > 0 ? (
        <Box mt={8}>
          <AccountSetupCard projectCount={projectCount} />
        </Box>
      ) : null}
      <NewProjectModal
        isOpen={newProjectModal.isOpen}
        onClose={newProjectModal.onClose}
      />
    </Container>
  )
}
