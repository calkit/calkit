import LoadingSpinner from "../../../components/Common/LoadingSpinner"
import {
  Box,
  Container,
  Flex,
  Heading,
  IconButton,
  Link,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
  useDisclosure,
} from "@chakra-ui/react"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"

import { AccountsService, OrgsService, ProjectsService } from "../../../client"
import NotFound from "../../../components/Common/NotFound"
import { ExternalLinkIcon } from "@chakra-ui/icons"
import { capitalizeFirstLetter } from "../../../lib/strings"
import { FaPlus } from "react-icons/fa"
import AddMember from "../../../components/Orgs/AddMember"

export const Route = createFileRoute("/_layout/$accountName/")({
  component: AccountPage,
})

function UsersTable() {
  const { accountName } = Route.useParams()
  const { isPending, data: users } = useQuery({
    queryKey: ["org-users", accountName],
    queryFn: () => OrgsService.getOrgUsers({ orgName: accountName }),
  })
  return (
    <>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Name</Th>
              <Th>GitHub name</Th>
              <Th>Role</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(3).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {users?.map((user) => (
                <Tr key={user.name}>
                  <Td>
                    <Link as={RouterLink} to={`/${user.name}`}>
                      {user.name}
                    </Link>
                  </Td>
                  <Td>
                    <Link
                      href={`https://github.com/${user.github_name}`}
                      isExternal
                    >
                      <ExternalLinkIcon mx="2px" /> {user.github_name}
                    </Link>
                  </Td>
                  <Td>{capitalizeFirstLetter(user.role)}</Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
    </>
  )
}

function ProjectsTable() {
  const { accountName } = Route.useParams()
  const { isPending, data: projects } = useQuery({
    queryKey: ["projects", accountName],
    queryFn: () => ProjectsService.getProjects({ ownerName: accountName }),
  })

  return (
    <>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Title</Th>
              <Th>GitHub URL</Th>
              <Th>Description</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(3).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {projects?.data.map((project) => (
                <Tr key={project.id}>
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
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
    </>
  )
}

function AccountPage() {
  const { accountName } = Route.useParams()
  const navigate = useNavigate({ from: Route.fullPath })
  const { isPending, data: account } = useQuery({
    queryKey: ["accounts", accountName],
    queryFn: () => AccountsService.getAccount({ accountName }),
    retry: (failureCount, error: any) => {
      const status =
        error?.status ?? error?.response?.status ?? error?.statusCode ?? null
      // Don't retry on 404, otherwise allow up to 3 attempts
      if (status === 404) return false
      return failureCount < 3
    },
  })
  useEffect(() => {
    if (!account?.name) return
    if (accountName !== account.name) {
      navigate({
        params: { accountName: account.name },
        replace: true,
      })
    }
  }, [account, accountName, navigate])
  const { isOpen, onOpen, onClose } = useDisclosure()

  return (
    <Box>
      {isPending ? (
        <LoadingSpinner height="100vh" />
      ) : !account?.name ? (
        <>
          <NotFound />
        </>
      ) : (
        <Container maxW={{ base: "90%", md: "60%" }} pb={10}>
          <Heading
            size="lg"
            textAlign={{ base: "center", md: "left" }}
            pt={12}
            mb={4}
          >
            {account.display_name}
            {/* TODO: Show icons indicating user/org and role */}
          </Heading>
          {/* Add a users table if this is an org */}
          {account.kind === "org" && account.role ? (
            <Box mb={8}>
              <Flex align="center" mb={4}>
                <Heading size="md" mr={2}>
                  Members
                </Heading>
                {["owner", "admin"].includes(account.role) ? (
                  <IconButton
                    aria-label="Add member"
                    height="25px"
                    width="28px"
                    icon={<FaPlus />}
                    size={"xs"}
                    onClick={onOpen}
                    variant="primary"
                  />
                ) : (
                  ""
                )}
              </Flex>
              <UsersTable />
              <AddMember
                isOpen={isOpen}
                onClose={onClose}
                orgName={account.name}
              />
            </Box>
          ) : (
            ""
          )}
          {/* Add a projects table */}
          <Heading size="md" mb={4}>
            Projects
          </Heading>
          <ProjectsTable />
        </Container>
      )}
    </Box>
  )
}
