import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
  Checkbox,
  Link,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import React from "react"
import { useForm } from "react-hook-form"

import {
  OrgsService,
  ProjectsService,
  StorageService,
  UsersService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import {
  getStorageLabel,
  getStorageServiceName,
  getStorageUrl,
} from "../../lib/storage"

interface DeleteProps {
  type: string
  id: string
  isOpen: boolean
  onClose: () => void
  projectOwner?: string
  projectName?: string
  // For a GitHub-less (native) collaborator, whose removal is keyed by user id
  // rather than a GitHub username.
  userId?: string | null
  // For an org member, whose removal is keyed by username
  orgName?: string
  // Called once the deletion succeeds, e.g., to leave a page for what's gone
  onDeleted?: () => void
}

const Delete = ({
  type,
  id,
  isOpen,
  onClose,
  projectOwner,
  projectName,
  userId,
  orgName,
  onDeleted,
}: DeleteProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cancelRef = React.useRef<HTMLButtonElement | null>(null)
  const {
    handleSubmit,
    formState: { isSubmitting },
  } = useForm()
  // Files in Calkit Hub storage can go with it, but never connected storage
  const [deleteHubStorage, setDeleteHubStorage] = React.useState(false)
  const storageQuery = useQuery({
    queryKey: ["projects", projectOwner, projectName, "storage"],
    queryFn: () =>
      StorageService.getProjectStorage({
        owner_name: projectOwner as string,
        project_name: projectName as string,
      }).then((response) => response.data),
    enabled: isOpen && type === "Project" && !!projectOwner && !!projectName,
  })
  const connectedStorage = storageQuery.data
    ? [
        ...(storageQuery.data.dvc ? [storageQuery.data.dvc] : []),
        ...storageQuery.data.previous,
      ]
    : []

  const deleteEntity = async (id: string) => {
    if (type === "Project") {
      await ProjectsService.deleteProjectById({
        project_id: id,
        delete_hub_storage: deleteHubStorage,
      }).then((response) => response.data)
    } else if (type === "User") {
      await UsersService.deleteUser({ user_id: id }).then(
        (response) => response.data,
      )
    } else if (type === "Collaborator" && projectOwner && projectName) {
      // GitHub collaborators are keyed by username; GitHub-less (native)
      // members by user id.
      if (id) {
        await ProjectsService.deleteProjectCollaborator({
          github_username: id,
          owner_name: projectOwner,
          project_name: projectName,
        }).then((response) => response.data)
      } else if (userId) {
        await ProjectsService.deleteProjectNativeCollaborator({
          user_id: userId,
          owner_name: projectOwner,
          project_name: projectName,
        }).then((response) => response.data)
      } else {
        throw new Error("No collaborator identifier")
      }
    } else if (type === "Org member" && orgName) {
      await OrgsService.deleteOrgMember({
        org_name: orgName,
        username: id,
      }).then((response) => response.data)
    } else if (type === "Question" && projectOwner && projectName) {
      await ProjectsService.deleteProjectQuestion({
        owner_name: projectOwner,
        project_name: projectName,
        number: Number(id),
      }).then((response) => response.data)
    } else {
      throw new Error(`Unexpected type: ${type}`)
    }
  }

  const mutation = useMutation({
    mutationFn: deleteEntity,
    onSuccess: () => {
      showToast(
        "Success",
        `The ${type.toLowerCase()} was deleted successfully.`,
        "success",
      )
      onClose()
      onDeleted?.()
    },
    onError: (err: AxiosError) => {
      // Some refusals have a reason worth showing, e.g., an org member who's
      // its last owner, or project storage that can't be reached
      if (type === "Org member" || type === "Project") {
        handleError(err, showToast)
        return
      }
      showToast(
        "An error occurred.",
        `An error occurred while deleting the ${type.toLowerCase()}.`,
        "error",
      )
    },
    onSettled: () => {
      if (["Project", "User"].includes(type)) {
        queryClient.invalidateQueries({
          queryKey: [type === "Project" ? "projects" : "users"],
        })
      }
      if (type === "Collaborator") {
        queryClient.invalidateQueries({
          queryKey: ["projects", projectOwner, projectName, "collaborators"],
        })
      }
      if (type === "Org member") {
        queryClient.invalidateQueries({ queryKey: ["org-users", orgName] })
        // Removing yourself takes away your role on the org page
        queryClient.invalidateQueries({ queryKey: ["accounts", orgName] })
      }
      if (type === "Question") {
        queryClient.invalidateQueries({
          queryKey: ["projects", projectOwner, projectName, "questions"],
        })
      }
    },
  })

  const onSubmit = async () => {
    mutation.mutate(id)
  }

  return (
    <>
      <AlertDialog
        isOpen={isOpen}
        onClose={onClose}
        leastDestructiveRef={cancelRef}
        size={{ base: "sm", md: "md" }}
        isCentered
        motionPreset="none"
      >
        <AlertDialogOverlay>
          <AlertDialogContent as="form" onSubmit={handleSubmit(onSubmit)}>
            <AlertDialogHeader>Delete {type.toLowerCase()}</AlertDialogHeader>
            <AlertDialogBody>
              {type === "User" && (
                <span>
                  All items associated with this user will also be{" "}
                  <strong>permanently deleted. </strong>
                </span>
              )}
              Are you sure? You will not be able to undo this action.
              {type === "Project" && (
                <>
                  <Checkbox
                    mt={4}
                    isChecked={deleteHubStorage}
                    onChange={(e) => setDeleteHubStorage(e.target.checked)}
                  >
                    Delete files in Calkit Hub storage
                  </Checkbox>
                  {connectedStorage.length > 0 && (
                    <Text mt={2} fontSize="sm" color="ui.dim">
                      Connected storage stays. To delete, go to{" "}
                      {connectedStorage.map((r, i) => (
                        <React.Fragment key={r.id}>
                          {i > 0 && ", "}
                          <Link href={getStorageUrl(r)} isExternal>
                            {getStorageServiceName(r.kind)} {getStorageLabel(r)}
                          </Link>
                        </React.Fragment>
                      ))}
                    </Text>
                  )}
                </>
              )}
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button
                variant="danger"
                type="submit"
                isLoading={isSubmitting || mutation.isPending}
              >
                Delete
              </Button>
              <Button
                ref={cancelRef}
                onClick={onClose}
                isDisabled={isSubmitting}
              >
                Cancel
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </>
  )
}

export default Delete
