import {
  Badge,
  Box,
  Button,
  Code,
  Flex,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  Heading,
  IconButton,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
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
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { FiCopy, FiTrash } from "react-icons/fi"

import {
  type ProjectInvitationCreated,
  type ProjectInvitationPost,
  ProjectsService,
} from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface ProjectRef {
  ownerName: string
  projectName: string
}

interface InviteLinksProps extends ProjectRef {
  isCreateOpen: boolean
  onCreateOpen: () => void
  onCreateClose: () => void
}

interface CreateInviteForm {
  name: string
  email: string
  role: "read" | "write"
  expires_days: string
  max_uses: string
}

function invitationStatus(invite: {
  revoked: boolean
  expires: string | null
  max_uses: number | null
  use_count: number
}): { label: string; color: string } {
  if (invite.revoked) {
    return { label: "Revoked", color: "red" }
  }
  if (invite.expires && new Date(invite.expires) < new Date()) {
    return { label: "Expired", color: "gray" }
  }
  if (invite.max_uses !== null && invite.use_count >= invite.max_uses) {
    return { label: "Used up", color: "gray" }
  }
  return { label: "Active", color: "green" }
}

const CreateInviteModal = ({
  ownerName,
  projectName,
  isOpen,
  onClose,
  onCreated,
}: ProjectRef & {
  isOpen: boolean
  onClose: () => void
  onCreated: (invite: ProjectInvitationCreated) => void
}) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateInviteForm>({
    mode: "onBlur",
    defaultValues: {
      name: "",
      email: "",
      role: "write",
      expires_days: "",
      max_uses: "",
    },
  })

  const mutation = useMutation({
    mutationFn: (data: CreateInviteForm) => {
      const requestBody: ProjectInvitationPost = {
        role: data.role,
        expires_days: data.expires_days ? Number(data.expires_days) : null,
        max_uses: data.max_uses ? Number(data.max_uses) : null,
        name: data.name || null,
        email: data.email || null,
      }
      return ProjectsService.postProjectInvitation({
        ownerName,
        projectName,
        requestBody,
      })
    },
    onSuccess: (invite) => {
      showToast(
        "Success!",
        invite.emailed
          ? `Invite link created and emailed to ${invite.email}.`
          : "Invite link created.",
        "success",
      )
      reset()
      onClose()
      onCreated(invite)
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "invitations"],
      })
    },
  })

  const onSubmit: SubmitHandler<CreateInviteForm> = (data) => {
    mutation.mutate(data)
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "md" }}
      isCentered
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
        <ModalHeader>Create invite link</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl>
            <FormLabel htmlFor="name">Label (optional)</FormLabel>
            <Input
              id="name"
              placeholder="Ex: Jane Johnson"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              {...register("name")}
            />
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.email}>
            <FormLabel htmlFor="email">Email invite to (optional)</FormLabel>
            <Input
              id="email"
              type="email"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              placeholder="collaborator@example.com"
              {...register("email", {
                pattern: {
                  value: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
                  message: "Enter a valid email address",
                },
              })}
            />
            {errors.email && (
              <FormErrorMessage>{errors.email.message}</FormErrorMessage>
            )}
          </FormControl>
          <FormControl mt={4}>
            <FormLabel htmlFor="role">Access level</FormLabel>
            <Select id="role" {...register("role")}>
              <option value="read">Read</option>
              <option value="write">Write</option>
            </Select>
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.expires_days}>
            <FormLabel htmlFor="expires_days">Expires in (days)</FormLabel>
            <Input
              id="expires_days"
              type="number"
              placeholder="Never"
              {...register("expires_days", {
                min: { value: 1, message: "Must be at least 1 day" },
                max: { value: 365, message: "Must be 365 days or fewer" },
              })}
            />
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.max_uses}>
            <FormLabel htmlFor="max_uses">Max uses</FormLabel>
            <Input
              id="max_uses"
              type="number"
              placeholder="Unlimited"
              {...register("max_uses", {
                min: { value: 1, message: "Must be at least 1" },
              })}
            />
          </FormControl>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={isSubmitting || mutation.isPending}
          >
            Create
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

const InviteLinks = ({
  ownerName,
  projectName,
  isCreateOpen,
  onCreateOpen,
  onCreateClose,
}: InviteLinksProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [created, setCreated] = useState<ProjectInvitationCreated | null>(null)
  const { isPending, data: invitations } = useQuery({
    queryKey: ["projects", ownerName, projectName, "invitations"],
    queryFn: () =>
      ProjectsService.getProjectInvitations({ ownerName, projectName }),
  })

  const revokeMutation = useMutation({
    mutationFn: (invitationId: string) =>
      ProjectsService.deleteProjectInvitation({
        ownerName,
        projectName,
        invitationId,
      }),
    onSuccess: () => {
      showToast("Success!", "Invite link revoked.", "success")
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", ownerName, projectName, "invitations"],
      })
    },
  })

  const copyLink = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url)
      showToast("Copied", "Invite link copied to clipboard.", "success")
    } catch {
      showToast(
        "Copy failed",
        "Could not copy the link. Copy it manually.",
        "error",
      )
    }
  }

  return (
    <Box mt={10}>
      <Flex align="center" justify="space-between" mb={2}>
        <Heading size="md">Invite links</Heading>
        <Button variant="primary" onClick={onCreateOpen}>
          Create invite link
        </Button>
      </Flex>
      <Text fontSize="sm" color="ui.dim" mb={4}>
        Share a link to let people join this project, including collaborators
        without a GitHub account.
      </Text>
      {created && (
        <Box
          borderWidth="1px"
          borderRadius="md"
          borderColor="green.300"
          p={3}
          mb={4}
        >
          <Text fontSize="sm" mb={1}>
            New invite link (copy it now; it won't be shown again):
          </Text>
          <HStack>
            <Code flex="1" isTruncated p={2}>
              {created.url}
            </Code>
            <IconButton
              aria-label="Copy invite link"
              icon={<FiCopy />}
              onClick={() => copyLink(created.url)}
            />
          </HStack>
        </Box>
      )}
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th width="26%">Label</Th>
              <Th width="14%">Access</Th>
              <Th width="14%">Status</Th>
              <Th width="14%">Uses</Th>
              <Th width="22%">Expires</Th>
              <Th width="10%">Actions</Th>
            </Tr>
          </Thead>
          {isPending ? (
            <Tbody>
              <Tr>
                {new Array(6).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            </Tbody>
          ) : (
            <Tbody>
              {invitations?.length ? (
                invitations.map((invite) => {
                  const status = invitationStatus(invite)
                  return (
                    <Tr key={invite.id}>
                      <Td>
                        {invite.name ? (
                          <Text fontSize="sm">{invite.name}</Text>
                        ) : (
                          <Text fontSize="sm" color="ui.dim">
                            Link
                          </Text>
                        )}
                        {invite.email ? (
                          <Text fontSize="xs" color="ui.dim">
                            emailed to {invite.email}
                          </Text>
                        ) : null}
                      </Td>
                      <Td>{invite.role_name}</Td>
                      <Td>
                        <Badge colorScheme={status.color}>{status.label}</Badge>
                      </Td>
                      <Td>
                        {invite.use_count}
                        {invite.max_uses !== null
                          ? ` / ${invite.max_uses}`
                          : ""}
                      </Td>
                      <Td>
                        {invite.expires
                          ? new Date(invite.expires).toLocaleDateString()
                          : "Never"}
                      </Td>
                      <Td>
                        <IconButton
                          aria-label="Revoke invite link"
                          icon={<FiTrash />}
                          variant="ghost"
                          color="ui.danger"
                          isDisabled={invite.revoked}
                          isLoading={
                            revokeMutation.isPending &&
                            revokeMutation.variables === invite.id
                          }
                          onClick={() => revokeMutation.mutate(invite.id)}
                        />
                      </Td>
                    </Tr>
                  )
                })
              ) : (
                <Tr>
                  <Td colSpan={6}>
                    <Text color="ui.dim">No invite links yet.</Text>
                  </Td>
                </Tr>
              )}
            </Tbody>
          )}
        </Table>
      </TableContainer>
      <CreateInviteModal
        ownerName={ownerName}
        projectName={projectName}
        isOpen={isCreateOpen}
        onClose={onCreateClose}
        onCreated={setCreated}
      />
    </Box>
  )
}

export default InviteLinks
