import {
  Box,
  Container,
  Flex,
  Heading,
  IconButton,
  Link,
  Select,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { Link as RouterLink } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useEffect, useState } from "react"
import DeleteAlert from "../../../components/Common/DeleteAlert"
import LoadingSpinner from "../../../components/Common/LoadingSpinner"

import { ExternalLinkIcon } from "@chakra-ui/icons"
import { FaPlus, FaTrash } from "react-icons/fa"
import {
  AccountsService,
  type OrgMemberPatch,
  OrgsService,
  ProjectsService,
} from "../../../client"
import NotFound from "../../../components/Common/NotFound"
import AddMember from "../../../components/Orgs/AddMember"
import useAuth from "../../../hooks/useAuth"
import useCustomToast from "../../../hooks/useCustomToast"
import { handleError } from "../../../lib/errors"
import { capitalizeFirstLetter, safeHref } from "../../../lib/strings"

export const Route = createFileRoute("/_layout/$accountName/")({
  component: AccountPage,
})

type OrgRole = OrgMemberPatch["role"]

const ORG_ROLES: OrgRole[] = ["read", "write", "admin", "owner"]

interface UsersTableProps {
  orgName: string
  // Superusers and org owners or admins
  canManage: boolean
  // Only superusers and org owners may grant ownership or change an owner
  canManageOwners: boolean
}

function UsersTable({ orgName, canManage, canManageOwners }: UsersTableProps) {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const removeModal = useDisclosure()
  const [memberToRemove, setMemberToRemove] = useState("")
  const { isPending, data: users } = useQuery({
    queryKey: ["org-users", orgName],
    queryFn: () =>
      OrgsService.getOrgUsers({ org_name: orgName }).then(
        (response) => response.data,
      ),
  })
  const roleMutation = useMutation({
    mutationFn: ({ username, role }: { username: string; role: OrgRole }) =>
      OrgsService.updateOrgMember({
        org_name: orgName,
        username,
        orgMemberPatch: { role },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Member role updated.", "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["org-users", orgName] })
      // Changing your own role changes which controls the page shows
      queryClient.invalidateQueries({ queryKey: ["accounts", orgName] })
    },
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
              {canManage ? <Th /> : null}
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(canManage ? 4 : 3).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {users?.map((user) => {
                const canEdit =
                  canManage && (canManageOwners || user.role !== "owner")
                return (
                  <Tr key={user.name}>
                    <Td>
                      <Link as={RouterLink} to={`/${user.name}`}>
                        {user.name}
                      </Link>
                    </Td>
                    <Td>
                      {user.github_name ? (
                        <Link
                          href={`https://github.com/${user.github_name}`}
                          isExternal
                        >
                          <ExternalLinkIcon mx="2px" /> {user.github_name}
                        </Link>
                      ) : (
                        ""
                      )}
                    </Td>
                    <Td>
                      {canEdit ? (
                        <Select
                          aria-label={`Role for ${user.name}`}
                          size="sm"
                          maxW="130px"
                          value={user.role}
                          isDisabled={roleMutation.isPending}
                          onChange={(e) =>
                            roleMutation.mutate({
                              username: user.name,
                              role: e.target.value as OrgRole,
                            })
                          }
                        >
                          {ORG_ROLES.filter(
                            (role) => canManageOwners || role !== "owner",
                          ).map((role) => (
                            <option key={role} value={role}>
                              {capitalizeFirstLetter(role)}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        capitalizeFirstLetter(user.role)
                      )}
                    </Td>
                    {canManage ? (
                      <Td>
                        {canEdit ? (
                          <IconButton
                            aria-label={`Remove ${user.name}`}
                            icon={<FaTrash />}
                            size="xs"
                            variant="ghost"
                            onClick={() => {
                              setMemberToRemove(user.name)
                              removeModal.onOpen()
                            }}
                          />
                        ) : (
                          ""
                        )}
                      </Td>
                    ) : null}
                  </Tr>
                )
              })}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      <DeleteAlert
        type="Org member"
        id={memberToRemove}
        orgName={orgName}
        isOpen={removeModal.isOpen}
        onClose={removeModal.onClose}
      />
    </>
  )
}

function ProjectsTable() {
  const { accountName } = Route.useParams()
  const { isPending, data: projects } = useQuery({
    queryKey: ["projects", accountName],
    queryFn: () =>
      ProjectsService.getProjects({ owner_name: accountName }).then(
        (response) => response.data,
      ),
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
                    <Link href={safeHref(project.git_repo_url)} isExternal>
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
    queryFn: () =>
      AccountsService.getAccount({ account_name: accountName }).then(
        (response) => response.data,
      ),
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
  const { user: currentUser } = useAuth()
  const isSuperuser = Boolean(currentUser?.is_superuser)
  const canManageMembers =
    isSuperuser || ["owner", "admin"].includes(account?.role ?? "")
  const canManageOwners = isSuperuser || account?.role === "owner"

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
          {account.kind === "org" && (account.role || isSuperuser) ? (
            <Box mb={8}>
              <Flex align="center" mb={4}>
                <Heading size="md" mr={2}>
                  Members
                </Heading>
                {canManageMembers ? (
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
              <UsersTable
                orgName={account.name}
                canManage={canManageMembers}
                canManageOwners={canManageOwners}
              />
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
