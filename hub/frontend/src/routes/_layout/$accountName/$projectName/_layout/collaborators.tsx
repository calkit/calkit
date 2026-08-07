import {
  Box,
  Heading,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Th,
  Thead,
  Badge,
  Menu,
  MenuItem,
  MenuButton,
  Tr,
  useDisclosure,
  Button,
  MenuList,
} from "@chakra-ui/react"
import { BsThreeDotsVertical } from "react-icons/bs"
import { FiTrash } from "react-icons/fi"
import { createFileRoute, useNavigate } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { z } from "zod"

import Navbar from "../../../../../components/Common/Navbar"
import AddCollaborator from "../../../../../components/Projects/AddCollaborator"
import InviteLinks from "../../../../../components/Projects/InviteLinks"
import { ProjectsService } from "../../../../../client"
import useAuth from "../../../../../hooks/useAuth"
import useProject from "../../../../../hooks/useProject"
import Delete from "../../../../../components/Common/DeleteAlert"

const collaboratorsSearchSchema = z.object({
  add_collaborator: z.boolean().optional(),
  create_invite: z.boolean().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/collaborators",
)({
  component: Collaborators,
  validateSearch: (search) => collaboratorsSearchSchema.parse(search),
})

interface ActionsMenuProps {
  ownerName: string
  projectName: string
  githubUsername?: string | null
  userId?: string | null
  disabled?: boolean
}

const ActionsMenu = ({
  ownerName,
  projectName,
  githubUsername,
  userId,
  disabled,
}: ActionsMenuProps) => {
  const deleteModal = useDisclosure()

  return (
    <>
      <Menu>
        <MenuButton
          isDisabled={disabled}
          as={Button}
          rightIcon={<BsThreeDotsVertical />}
          variant="unstyled"
        />
        <MenuList>
          <MenuItem
            onClick={deleteModal.onOpen}
            icon={<FiTrash fontSize="16px" />}
            color="ui.danger"
          >
            Remove collaborator
          </MenuItem>
        </MenuList>
        <Delete
          type={"Collaborator"}
          id={githubUsername ?? ""}
          userId={userId}
          projectOwner={ownerName}
          projectName={projectName}
          isOpen={deleteModal.isOpen}
          onClose={deleteModal.onClose}
        />
      </Menu>
    </>
  )
}

function Collaborators() {
  const { accountName, projectName } = Route.useParams()
  const { add_collaborator, create_invite } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { user: currentUser } = useAuth()
  // Managing collaborators/invites is admin-only (the API enforces this too).
  const { userHasAdminAccess } = useProject(accountName, projectName)
  const { isPending, data: collaborators } = useQuery({
    queryKey: ["projects", accountName, projectName, "collaborators"],
    queryFn: () =>
      ProjectsService.getProjectCollaborators({
        ownerName: accountName,
        projectName: projectName,
      }),
  })

  return (
    <Box>
      <Heading size={"md"}>Collaborators</Heading>
      {userHasAdminAccess && (
        <Navbar
          type="collaborator"
          addModalAs={AddCollaborator}
          isOpen={!!add_collaborator}
          onOpen={() =>
            navigate({
              search: (prev) => ({ ...prev, add_collaborator: true }),
            })
          }
          onClose={() =>
            navigate({
              search: (prev) => ({ ...prev, add_collaborator: undefined }),
            })
          }
        />
      )}
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th width="20%">Username</Th>
              <Th width="20%">Full name</Th>
              <Th width="50%">Email</Th>
              <Th width="10%">Access</Th>
              <Th width="10%">Actions</Th>
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
              {collaborators?.map((collaborator) => (
                <Tr key={collaborator.user_id ?? collaborator.github_username}>
                  <Td isTruncated maxWidth="150px">
                    {collaborator.github_username || collaborator.account_name}
                  </Td>
                  <Td
                    color={!collaborator.full_name ? "ui.dim" : "inherit"}
                    isTruncated
                    maxWidth="150px"
                  >
                    {collaborator.full_name || "N/A"}
                    {currentUser?.id === collaborator.user_id && (
                      <Badge ml="1" colorScheme="teal">
                        You
                      </Badge>
                    )}
                  </Td>
                  <Td isTruncated maxWidth="150px">
                    {collaborator.email}
                  </Td>
                  <Td>{collaborator.access_level}</Td>
                  <Td>
                    {userHasAdminAccess && (
                      <ActionsMenu
                        ownerName={accountName}
                        projectName={projectName}
                        githubUsername={collaborator.github_username}
                        userId={collaborator.user_id}
                        disabled={currentUser?.id === collaborator.user_id}
                      />
                    )}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      {/* Invite links are an admin-only management feature; the list endpoint
          requires admin, so don't render (or fire its query) for others. */}
      {userHasAdminAccess && (
        <InviteLinks
          ownerName={accountName}
          projectName={projectName}
          isCreateOpen={!!create_invite}
          onCreateOpen={() =>
            navigate({ search: (prev) => ({ ...prev, create_invite: true }) })
          }
          onCreateClose={() =>
            navigate({
              search: (prev) => ({ ...prev, create_invite: undefined }),
            })
          }
        />
      )}
    </Box>
  )
}
