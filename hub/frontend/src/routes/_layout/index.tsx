import {
  Box,
  Button,
  Container,
  Flex,
  Heading,
  Link,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  Text,
} from "@chakra-ui/react"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  useNavigate,
  Link as RouterLink,
} from "@tanstack/react-router"
import { useEffect, useState } from "react"
import { z } from "zod"
import { useDebounce } from "use-debounce"

import { ProjectsService } from "../../client"
import ActionsMenu from "../../components/Common/ActionsMenu"
import Navbar from "../../components/Common/Navbar"
import NewProject from "../../components/Projects/NewProject"
import { pageWidthNoSidebar } from "../../lib/layout"
import useAuth from "../../hooks/useAuth"
import ClearableInput from "../../components/Common/ClearableInput"

const projectsSearchSchema = z.object({
  page: z.number().catch(1),
})

export const Route = createFileRoute("/_layout/")({
  component: Projects,
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
        searchFor,
      }),
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
      <Flex alignItems="center">
        <Box mr={4}>
          <Navbar verb={"New"} type={"project"} addModalAs={NewProject} />
        </Box>
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

function PublicProjectsTable() {
  const projectsRequest = useQuery({
    queryKey: ["projects-logged-out"],
    queryFn: () =>
      ProjectsService.getProjects({
        limit: 5,
      }),
  })
  const isPending = projectsRequest.isPending
  const projects = projectsRequest.data
  const isPlaceholderData = projectsRequest.isPlaceholderData

  return (
    <>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Owner</Th>
              <Th>Title</Th>
              <Th>Description</Th>
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
                  <Td isTruncated maxWidth="80px">
                    {project.owner_account_display_name}
                  </Td>
                  <Td isTruncated maxWidth="200px">
                    <Link
                      as={RouterLink}
                      to={`/${project.owner_account_name}/${project.name}`}
                    >
                      {project.title}
                    </Link>
                  </Td>
                  <Td
                    color={!project.description ? "ui.dim" : "inherit"}
                    isTruncated
                    maxWidth="250px"
                  >
                    {project.description || "N/A"}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
    </>
  )
}

function Projects() {
  const { user } = useAuth()
  return (
    <Container maxW={user ? pageWidthNoSidebar : "65%"}>
      {user ? (
        <>
          <Heading size="lg" textAlign={{ base: "center", md: "left" }} mt={12}>
            Your projects
          </Heading>
          <ProjectsTable />
        </>
      ) : (
        <>
          <Heading
            size="lg"
            textAlign={{ base: "center", md: "left" }}
            mt={12}
            mb={4}
          >
            👋 Hi there!
          </Heading>
          <Text>
            Welcome to the Calkit Cloud, where you can create, discover, share,
            and collaborate on research projects. If you're ready to get
            started, click the button below:
          </Text>
          <Box
            alignItems="center"
            alignContent="center"
            textAlign="center"
            mt={2}
          >
            <Link as={RouterLink} to={"/login"}>
              <Button variant="primary">🚀 Let's go!</Button>
            </Link>
          </Box>
          <Text mt={6} mb={6}>
            If you'd like to do some exploring first, here are some projects you
            might find interesting:
          </Text>
          <PublicProjectsTable />
        </>
      )}
    </Container>
  )
}
