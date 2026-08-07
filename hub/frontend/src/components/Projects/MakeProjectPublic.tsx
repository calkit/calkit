import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogContent,
  AlertDialogOverlay,
  Button,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import { useRef } from "react"

import {
  type ApiError,
  type ProjectPatch,
  type ProjectPublic,
  ProjectsService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface MakeProjectPublicProps {
  project: ProjectPublic
  isOpen: boolean
  onClose: () => void
}

const MakeProjectPublic = ({
  project,
  isOpen,
  onClose,
}: MakeProjectPublicProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const {
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<ProjectPatch>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: project,
  })

  const mutation = useMutation({
    mutationFn: (data: ProjectPatch) =>
      ProjectsService.patchProject({
        ownerName: project.owner_account_name,
        projectName: project.name,
        requestBody: data,
      }),
    onSuccess: () => {
      showToast("Success!", "Project updated successfully.", "success")
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["projects"] })
    },
  })

  const onSubmit: SubmitHandler<ProjectPatch> = async () => {
    mutation.mutate({ is_public: true })
  }

  const cancelRef = useRef(null)

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
            <AlertDialogHeader>Make project public</AlertDialogHeader>
            <AlertDialogBody>
              Are you sure? You will not be able to undo this action.
            </AlertDialogBody>
            <AlertDialogFooter gap={3}>
              <Button
                variant="danger"
                type="submit"
                isLoading={isSubmitting || mutation.isPending}
              >
                Make public
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

export default MakeProjectPublic
