import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import React from "react"
import { useForm } from "react-hook-form"

import { UsersService, ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"

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
}

const Delete = ({
  type,
  id,
  isOpen,
  onClose,
  projectOwner,
  projectName,
  userId,
}: DeleteProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const cancelRef = React.useRef<HTMLButtonElement | null>(null)
  const {
    handleSubmit,
    formState: { isSubmitting },
  } = useForm()

  const deleteEntity = async (id: string) => {
    if (type === "Project") {
      await ProjectsService.deleteProjectById({
        projectId: id,
      })
    } else if (type === "User") {
      await UsersService.deleteUser({ userId: id })
    } else if (type === "Collaborator" && projectOwner && projectName) {
      // GitHub collaborators are keyed by username; GitHub-less (native)
      // members by user id.
      if (id) {
        await ProjectsService.deleteProjectCollaborator({
          githubUsername: id,
          ownerName: projectOwner,
          projectName: projectName,
        })
      } else if (userId) {
        await ProjectsService.deleteProjectNativeCollaborator({
          userId: userId,
          ownerName: projectOwner,
          projectName: projectName,
        })
      } else {
        throw new Error("No collaborator identifier")
      }
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
    },
    onError: () => {
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
